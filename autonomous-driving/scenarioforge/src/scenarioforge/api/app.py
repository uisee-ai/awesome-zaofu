from __future__ import annotations

import hmac
import json
import os
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from scenarioforge.compiler import CompilationError, compile_scenario
from scenarioforge.oracle import ToleranceProfile, compare_bundles, verify_exact_replay
from scenarioforge.replay import ReplayLoadError, load_replay_bundle
from scenarioforge.runtime import JobManager
from scenarioforge.spec import (
    RunRequest,
    ScenarioInputError,
    canonical_scenario,
    export_scenario,
    load_scenario,
)


_BUNDLE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SAMPLE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,127}$")
_SAMPLE_JSON_FILE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.json$")
_UNSAFE_TEXT = re.compile(
    r"(?:<\s*script\b|javascript\s*:|on(?:error|load)\s*=|secret[_-]?canary|"
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|AKIA[0-9A-Z]{16}|\x80\x04)",
    re.IGNORECASE,
)
_MAX_REQUEST_BYTES = 2_097_152
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


class JobService(Protocol):
    def submit(self, compiled: object, output_root: Path, *, job_id: str) -> object: ...

    def get(self, job_id: str) -> object: ...

    def cancel(self, job_id: str) -> object: ...


@dataclass(frozen=True)
class ApiConfig:
    bundle_root: Path
    run_output_root: Path
    allowed_origin: str
    capability_token: str
    csrf_token: str
    sample_root: Path = Path("samples")
    job_manager: JobService | None = None

    @classmethod
    def from_environment(cls) -> ApiConfig:
        return cls(
            bundle_root=Path(os.environ.get("SCENARIOFORGE_BUNDLE_ROOT", "evidence/runtime/metadrive-smoke")),
            run_output_root=Path(os.environ.get("SCENARIOFORGE_RUN_ROOT", "evidence/web/runs")),
            allowed_origin=os.environ.get("SCENARIOFORGE_ALLOWED_ORIGIN", "http://127.0.0.1:4173"),
            capability_token=os.environ.get("SCENARIOFORGE_CAPABILITY_TOKEN", ""),
            csrf_token=os.environ.get("SCENARIOFORGE_CSRF_TOKEN", ""),
        )


class _RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ScenarioDocument(_RequestModel):
    source: str = Field(max_length=1_048_576)
    media_type: str = Field(max_length=128)


class ScenarioExport(ScenarioDocument):
    format: Literal["json", "yaml"]


class RunControl(ScenarioDocument):
    request: dict[str, Any]


class ReplayRequest(_RequestModel):
    bundle_id: str = Field(max_length=128)


class CompareRequest(_RequestModel):
    baseline_bundle_id: str = Field(max_length=128)
    candidate_bundle_id: str = Field(max_length=128)
    profile: dict[str, Any]


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def _safe_compare(candidate: str | None, expected: str) -> bool:
    return bool(expected) and candidate is not None and hmac.compare_digest(candidate, expected)


def _host_without_port(host: str) -> str:
    if host.startswith("[") and "]" in host:
        return host[1 : host.index("]")]
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


def _secure(response: JSONResponse, origin: str | None, allowed_origin: str) -> JSONResponse:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    response.headers["Cross-Origin-Resource-Policy"] = "same-site"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    if origin == allowed_origin:
        response.headers["Access-Control-Allow-Origin"] = allowed_origin
        response.headers["Vary"] = "Origin"
    return response


def _reject_unsafe_text(*values: str) -> None:
    if any(_UNSAFE_TEXT.search(value) for value in values):
        raise ReplayLoadError("unsafe_input", "input contains a forbidden active-content or secret marker")


def _validation_payload(error: ScenarioInputError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"valid": False, "diagnostics": error.diagnostics},
    )


def _snapshot_payload(snapshot: object) -> dict[str, Any]:
    return snapshot.model_dump(mode="json") if hasattr(snapshot, "model_dump") else dict(snapshot)


def _bundle_path(root: Path, bundle_id: str) -> Path:
    if not _BUNDLE_ID.fullmatch(bundle_id) or bundle_id in {".", ".."}:
        raise ReplayLoadError("invalid_bundle_id", "bundle id is invalid")
    return root / bundle_id


def _sample_catalog(root: Path) -> dict[str, Any]:
    catalog = json.loads((root / "catalog.json").read_text(encoding="utf-8"))
    if not isinstance(catalog, dict) or not isinstance(catalog.get("samples"), list):
        raise ValueError("sample catalog has an invalid shape")
    return catalog


def _sample_document(root: Path, sample_id: str) -> str:
    if not _SAMPLE_ID.fullmatch(sample_id):
        raise FileNotFoundError("sample id is invalid")
    catalog = _sample_catalog(root)
    entry = next(
        (
            item
            for item in catalog["samples"]
            if isinstance(item, dict) and item.get("id") == sample_id
        ),
        None,
    )
    json_file = entry.get("json") if isinstance(entry, dict) else None
    if not isinstance(json_file, str) or not _SAMPLE_JSON_FILE.fullmatch(json_file):
        raise FileNotFoundError("sample document is unavailable")
    root_path = root.resolve()
    document_path = (root_path / json_file).resolve()
    if document_path.parent != root_path:
        raise FileNotFoundError("sample document is outside sample root")
    return document_path.read_text(encoding="utf-8")


def create_app(config: ApiConfig) -> FastAPI:
    app = FastAPI(
        title="ScenarioForge loopback API",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.middleware("http")
    async def local_security_boundary(request: Request, call_next: Callable[..., object]):
        origin = request.headers.get("origin")
        host = _host_without_port(request.headers.get("host", ""))
        client_host = request.client.host if request.client else ""
        denial: JSONResponse | None = None
        if host not in _LOOPBACK_HOSTS or client_host not in _LOOPBACK_HOSTS:
            denial = _error(403, "loopback_denied", "API access is restricted to loopback")
        elif origin != config.allowed_origin:
            denial = _error(403, "origin_denied", "request origin is not allowed")
        elif request.method == "OPTIONS":
            denial = JSONResponse(status_code=204, content=None)
            denial.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            denial.headers["Access-Control-Allow-Headers"] = (
                "Content-Type, X-ScenarioForge-Capability, X-ScenarioForge-CSRF"
            )
            denial.headers["Access-Control-Max-Age"] = "600"
        elif not _safe_compare(
            request.headers.get("x-scenarioforge-capability"), config.capability_token
        ):
            denial = _error(403, "capability_denied", "capability authentication failed")
        elif request.method not in {"GET", "HEAD"} and not _safe_compare(
            request.headers.get("x-scenarioforge-csrf"), config.csrf_token
        ):
            denial = _error(403, "csrf_denied", "CSRF verification failed")
        else:
            content_length = request.headers.get("content-length")
            if content_length and (not content_length.isdigit() or int(content_length) > _MAX_REQUEST_BYTES):
                denial = _error(413, "request_too_large", "request exceeds the local API limit")
        response = denial if denial is not None else await call_next(request)
        return _secure(response, origin, config.allowed_origin)

    @app.exception_handler(RequestValidationError)
    async def request_validation_error(_request: Request, _error_value: RequestValidationError):
        return _error(422, "request_invalid", "request does not match the API schema")

    @app.exception_handler(Exception)
    async def concealed_internal_error(_request: Request, _error_value: Exception):
        return _error(500, "internal_error", "local operation failed")

    jobs = config.job_manager or JobManager()

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ready"}

    @app.get("/api/samples")
    def samples() -> dict[str, Any]:
        try:
            catalog = _sample_catalog(config.sample_root)
        except (OSError, ValueError, json.JSONDecodeError):
            return _error(404, "sample_catalog_unavailable", "sample catalog is unavailable")
        return catalog

    @app.get("/api/samples/{sample_id:path}")
    def sample_document(sample_id: str):
        try:
            source = _sample_document(config.sample_root, sample_id)
        except (OSError, ValueError, json.JSONDecodeError):
            return _error(404, "sample_not_found", "sample document is unavailable")
        return {"id": sample_id, "media_type": "application/json", "source": source}

    @app.post("/api/scenarios/validate")
    def validate_scenario(document: ScenarioDocument):
        try:
            _reject_unsafe_text(document.source, document.media_type)
            scenario = load_scenario(document.source, document.media_type)
        except ReplayLoadError as error:
            return _error(400, error.code, str(error))
        except ScenarioInputError as error:
            return _validation_payload(error)
        canonical = canonical_scenario(scenario)
        return {
            "valid": True,
            "diagnostics": [],
            "canonical": {
                "digest": canonical.digest,
                "scenario": json.loads(canonical.bytes),
            },
        }

    @app.post("/api/scenarios/export")
    def export(document: ScenarioExport):
        try:
            _reject_unsafe_text(document.source, document.media_type)
            scenario = load_scenario(document.source, document.media_type)
        except ReplayLoadError as error:
            return _error(400, error.code, str(error))
        except ScenarioInputError as error:
            return _validation_payload(error)
        return {"format": document.format, "document": export_scenario(scenario, document.format)}

    @app.post("/api/runs", status_code=202)
    def run(document: RunControl):
        try:
            _reject_unsafe_text(document.source, document.media_type)
            scenario = load_scenario(document.source, document.media_type)
            request = RunRequest.model_validate(document.request)
            compiled = compile_scenario(scenario, request)
        except ReplayLoadError as error:
            return _error(400, error.code, str(error))
        except ScenarioInputError as error:
            return _validation_payload(error)
        except (ValidationError, CompilationError):
            return _error(422, "run_request_invalid", "run request cannot be compiled")
        run_id = f"run-{uuid.uuid4().hex}"
        return _snapshot_payload(jobs.submit(compiled, config.run_output_root, job_id=run_id))

    @app.get("/api/runs/{job_id}")
    def run_status(job_id: str):
        try:
            return _snapshot_payload(jobs.get(job_id))
        except KeyError:
            return _error(404, "job_not_found", "job id is unknown")

    @app.post("/api/runs/{job_id}/cancel")
    def cancel_run(job_id: str):
        try:
            return _snapshot_payload(jobs.cancel(job_id))
        except KeyError:
            return _error(404, "job_not_found", "job id is unknown")

    @app.post("/api/replays/load")
    def replay(request: ReplayRequest):
        try:
            result = load_replay_bundle(_bundle_path(config.bundle_root, request.bundle_id))
        except ReplayLoadError as error:
            status = 400 if error.code == "invalid_bundle_id" else 404 if error.code == "bundle_not_found" else 422
            return _error(status, error.code, str(error))
        return result.model_dump(mode="json")

    @app.post("/api/replays/verify")
    def verify_replay(request: ReplayRequest):
        try:
            return verify_exact_replay(_bundle_path(config.bundle_root, request.bundle_id)).model_dump(
                mode="json"
            )
        except ReplayLoadError as error:
            status = 400 if error.code == "invalid_bundle_id" else 404 if error.code == "bundle_not_found" else 422
            return _error(status, error.code, str(error))

    @app.post("/api/oracle/compare")
    def compare(request: CompareRequest):
        try:
            profile = ToleranceProfile.model_validate(request.profile)
            return compare_bundles(
                _bundle_path(config.bundle_root, request.baseline_bundle_id),
                _bundle_path(config.bundle_root, request.candidate_bundle_id),
                profile,
            ).model_dump(mode="json")
        except (ReplayLoadError, ValidationError):
            return _error(422, "oracle_request_invalid", "oracle comparison request is invalid")

    @app.post("/api/bundles/import")
    def reject_archive_import(_request: dict[str, Any]):
        return _error(
            415,
            "archive_import_disabled",
            "archive import is disabled; use an already sealed local bundle",
        )

    return app


app = create_app(ApiConfig.from_environment())
