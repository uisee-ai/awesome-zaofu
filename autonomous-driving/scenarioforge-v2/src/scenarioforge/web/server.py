from __future__ import annotations

import asyncio
import json
import secrets
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from types import FrameType
from typing import Protocol
from urllib.parse import urlsplit

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from scenarioforge.authoring.actions import AuthoringActionError
from scenarioforge.authoring.library import (
    ArchivedScenarioError,
    DraftConflictError,
    InvalidDraftError,
    LocalScenarioLibrary,
    UnknownRevisionError,
)
from scenarioforge.authoring.library import (
    UnknownScenarioError as UnknownAuthoringScenarioError,
)
from scenarioforge.authoring.p1_preflight import PreflightContractError
from scenarioforge.authoring.presets import UnknownPresetError
from scenarioforge.authoring.providers import ProviderError
from scenarioforge.authoring.save_and_run import SaveAndRunBlocked
from scenarioforge.authoring.scenario_spec import ScenarioSpecError
from scenarioforge.authoring.serialization import SerializationError
from scenarioforge.orchestration.contracts import ExperimentContractError
from scenarioforge.orchestration.runner import ScenarioForgeRunnerFactory
from scenarioforge.orchestration.service import (
    CommandConflictError,
    ExperimentService,
    InvalidControlTransition,
)
from scenarioforge.orchestration.store import (
    ActiveExperimentError,
    ExperimentStore,
    UnknownExperimentError,
)
from scenarioforge.runtime.confirmation import ConfirmationError
from scenarioforge.runtime.supervisor import RunSupervisor

from .api import RevisionAwareEvidenceReader, ScenarioForgeAPI
from .coordinator import (
    InvalidIdentifierError,
    P1RunCoordinator,
    RunCoordinator,
    RunExecutionError,
    SlotOccupiedError,
    UnknownRunError,
    UnknownScenarioError,
)
from .evidence import (
    EvidenceValidationError,
    InvalidEvidenceIdentifierError,
    NonPlayableRunError,
    PublishedEvidenceReader,
    UnknownArtifactError,
    UnknownPublishedRunError,
)

LOOPBACK_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
_LOOPBACK_NAMES = frozenset({"127.0.0.1", "localhost", "::1"})
_STATE_CHANGING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_MAX_REQUEST_BYTES = 4096
_MAX_AUTHORING_REQUEST_BYTES = 66_560
_SHUTDOWN_WAIT_SECONDS = 10.0
CONTENT_SECURITY_POLICY = (
    "default-src 'none'; "
    "base-uri 'none'; "
    "object-src 'none'; "
    "frame-ancestors 'none'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "connect-src 'self'; "
    "img-src 'self' data:; "
    "font-src 'none'; "
    "form-action 'none'"
)
_SECURITY_HEADERS = {
    "cache-control": "no-store",
    "content-security-policy": CONTENT_SECURITY_POLICY,
    "cross-origin-resource-policy": "same-origin",
    "permissions-policy": "camera=(), geolocation=(), microphone=()",
    "referrer-policy": "no-referrer",
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
}


class _BusinessAPI(Protocol):
    def get_catalog(self) -> dict[str, object]: ...

    def start_run(self, scenario_id: str, *, idempotency_key: str) -> dict[str, object]: ...

    def get_run_status(self, run_id: str) -> dict[str, object]: ...

    def get_run_artifact(self, run_id: str, artifact_key: str) -> dict[str, object]: ...

    def get_p1_catalog(self) -> dict[str, object]: ...

    def start_p1_run(
        self, scenario_id: str, *, idempotency_key: str
    ) -> dict[str, object]: ...

    def get_p1_run_status(self, run_id: str) -> dict[str, object]: ...

    def get_p1_run_artifact(
        self, run_id: str, artifact_key: str
    ) -> dict[str, object]: ...

    def submit_experiment(
        self,
        definition: dict[str, object],
        *,
        idempotency_key: str,
    ) -> dict[str, object]: ...

    def list_experiments(self) -> dict[str, object]: ...

    def get_experiment(self, experiment_id: str) -> dict[str, object]: ...

    def control_experiment(
        self,
        experiment_id: str,
        operation: str,
        *,
        command_id: str,
    ) -> dict[str, object]: ...

    def normalize_authoring_content(
        self, content: dict[str, object]
    ) -> dict[str, object]: ...

    def create_authoring_intent_draft(
        self,
        prompt: str,
        *,
        provider_id: str,
    ) -> dict[str, object]: ...

    def preflight_p1_authoring_revision(
        self,
        revision_id: str,
        *,
        backend_id: str,
    ) -> dict[str, object]: ...

    def confirm_p1_authoring(self, preflight_id: str) -> dict[str, object]: ...

    def authorize_p1_authoring_run(
        self,
        preflight_id: str,
        authorization: dict[str, object],
    ) -> dict[str, object]: ...


class _Coordinator(Protocol):
    def interrupt_active_for_shutdown(self) -> bool: ...

    def wait_for_terminal(self, run_id: str, *, timeout: float | None = None) -> object: ...


class _RequestProblem(ValueError):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class _ShutdownController:
    """Bridge Uvicorn signals to one tracked immutable run publication."""

    def __init__(self, coordinator: _Coordinator) -> None:
        self._coordinator = coordinator
        self._lock = threading.Lock()
        self._run_id: str | None = None
        self._requested = False
        self._interrupted = False

    def track(self, run_id: str) -> None:
        with self._lock:
            self._run_id = run_id

    def request_interruption(self) -> bool:
        with self._lock:
            if not self._requested:
                self._requested = True
                self._interrupted = bool(
                    self._coordinator.interrupt_active_for_shutdown()
                )
            return self._interrupted

    def finish(self) -> None:
        interrupted = self.request_interruption()
        with self._lock:
            run_id = self._run_id
        if interrupted and run_id is not None:
            self._coordinator.wait_for_terminal(
                run_id,
                timeout=_SHUTDOWN_WAIT_SECONDS,
            )


class LoopbackServer(uvicorn.Server):
    """Uvicorn server whose OS signal path first interrupts the active Worker."""

    def __init__(
        self,
        config: uvicorn.Config,
        *,
        shutdown: _ShutdownController,
    ) -> None:
        super().__init__(config)
        self._scenarioforge_shutdown = shutdown

    def handle_exit(self, sig: int, frame: FrameType | None) -> None:
        self._scenarioforge_shutdown.request_interruption()
        super().handle_exit(sig, frame)


def _json_problem(status_code: int, detail: str) -> JSONResponse:
    return JSONResponse({"detail": detail}, status_code=status_code)


def _header_values(scope: Scope, name: str) -> tuple[str, ...]:
    encoded = name.lower().encode("ascii")
    return tuple(
        value.decode("latin-1")
        for key, value in scope.get("headers", ())
        if key.lower() == encoded
    )


def _authority(value: str, configured_port: int) -> tuple[str, int] | None:
    try:
        parsed = urlsplit(f"//{value}")
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.hostname is None
    ):
        return None
    hostname = parsed.hostname.lower()
    effective_port = 80 if port is None else port
    if hostname not in _LOOPBACK_NAMES or effective_port != configured_port:
        return None
    return hostname, effective_port


def _origin(value: str) -> tuple[str, int] | None:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme.lower() != "http"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.hostname is None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        return None
    return parsed.hostname.lower(), 80 if port is None else port


class ScenarioForgeWebApplication:
    """ASGI wrapper enforcing the service's loopback browser boundary."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        shutdown: _ShutdownController,
        port: int,
        csrf_token: str,
    ) -> None:
        self.app = app
        self.shutdown = shutdown
        self.port = port
        self.csrf_token = csrf_token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        hosts = _header_values(scope, "host")
        host = _authority(hosts[0], self.port) if len(hosts) == 1 else None
        if host is None:
            await self._send_response(
                _json_problem(400, "invalid Host authority"), scope, receive, send
            )
            return

        origins = _header_values(scope, "origin")
        if len(origins) > 1 or (origins and _origin(origins[0]) != host):
            await self._send_response(
                _json_problem(403, "cross-origin request rejected"),
                scope,
                receive,
                send,
            )
            return

        if scope["method"].upper() in _STATE_CHANGING_METHODS:
            if len(origins) != 1:
                await self._send_response(
                    _json_problem(403, "same-origin request required"),
                    scope,
                    receive,
                    send,
                )
                return
            tokens = _header_values(scope, "x-csrf-token")
            if len(tokens) != 1 or not secrets.compare_digest(
                tokens[0], self.csrf_token
            ):
                await self._send_response(
                    _json_problem(403, "invalid anti-CSRF token"),
                    scope,
                    receive,
                    send,
                )
                return

        await self.app(scope, receive, self._secure_send(send))

    async def _send_response(
        self,
        response: Response,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        await response(scope, receive, self._secure_send(send))

    @staticmethod
    def _secure_send(send: Send) -> Send:
        async def secured(message: Message) -> None:
            if message["type"] == "http.response.start":
                protected = {name.encode("ascii") for name in _SECURITY_HEADERS}
                headers = [
                    (key, value)
                    for key, value in message.get("headers", ())
                    if key.lower() not in protected
                ]
                headers.extend(
                    (name.encode("ascii"), value.encode("latin-1"))
                    for name, value in _SECURITY_HEADERS.items()
                )
                message["headers"] = headers
            await send(message)

        return secured


def _single_header(request: Request, name: str) -> str:
    values = _header_values(request.scope, name)
    if len(values) != 1:
        raise _RequestProblem(400, f"exactly one {name} header is required")
    return values[0]


def _object_without_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _RequestProblem(400, "request JSON contains duplicate fields")
        result[key] = value
    return result


def _reject_nonfinite_constant(_value: str) -> object:
    raise ValueError("non-finite JSON number")


async def _start_payload(request: Request) -> tuple[str, str]:
    payload = await _request_payload(request, max_bytes=_MAX_REQUEST_BYTES)
    if set(payload) != {"scenario_id"}:
        raise _RequestProblem(400, "request JSON fields are invalid")
    scenario_id = payload["scenario_id"]
    if not isinstance(scenario_id, str):
        raise _RequestProblem(400, "scenario_id must be a string")
    return scenario_id, _single_header(request, "idempotency-key")


async def _request_payload(
    request: Request,
    *,
    max_bytes: int = _MAX_AUTHORING_REQUEST_BYTES,
) -> dict[str, object]:
    content_type = _single_header(request, "content-type")
    if content_type.split(";", 1)[0].strip().lower() != "application/json":
        raise _RequestProblem(415, "Content-Type must be application/json")
    body = await request.body()
    if not body or len(body) > max_bytes:
        raise _RequestProblem(400, "request JSON body is invalid")
    try:
        payload = json.loads(
            body.decode("utf-8"),
            object_pairs_hook=_object_without_duplicates,
            parse_constant=_reject_nonfinite_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        if isinstance(error, _RequestProblem):
            raise
        raise _RequestProblem(400, "request JSON body is invalid") from error
    if not isinstance(payload, dict):
        raise _RequestProblem(400, "request JSON body must be an object")
    return payload


def _exact_fields(
    payload: dict[str, object],
    fields: set[str],
) -> dict[str, object]:
    if set(payload) != fields:
        raise _RequestProblem(400, "request JSON fields are invalid")
    return payload


def _content(payload: dict[str, object]) -> dict[str, object]:
    content = payload.get("content")
    if not isinstance(content, dict):
        raise _RequestProblem(400, "content must be a JSON object")
    return content


def _generation(payload: dict[str, object]) -> int:
    generation = payload.get("expected_generation")
    if isinstance(generation, bool) or not isinstance(generation, int) or generation < 0:
        raise _RequestProblem(400, "expected_generation must be a non-negative integer")
    return generation


def _api_problem(error: Exception) -> JSONResponse:
    if isinstance(error, SlotOccupiedError):
        return _json_problem(409, "single-run execution slot is occupied")
    if isinstance(
        error,
        (
            UnknownRunError,
            UnknownScenarioError,
            UnknownArtifactError,
            UnknownPublishedRunError,
        ),
    ):
        return _json_problem(404, str(error))
    if isinstance(error, (InvalidIdentifierError, InvalidEvidenceIdentifierError)):
        return _json_problem(400, str(error))
    if isinstance(error, NonPlayableRunError):
        return _json_problem(409, str(error))
    if isinstance(error, EvidenceValidationError):
        return _json_problem(422, str(error))
    if isinstance(error, RunExecutionError):
        return _json_problem(500, "run execution failed")
    if isinstance(error, UnknownExperimentError):
        return _json_problem(404, str(error))
    if isinstance(error, ActiveExperimentError):
        return _json_problem(409, str(error))
    if isinstance(error, (InvalidControlTransition, CommandConflictError)):
        return _json_problem(409, str(error))
    if isinstance(error, ExperimentContractError):
        return _json_problem(400, str(error))
    if isinstance(error, (UnknownAuthoringScenarioError, UnknownRevisionError)):
        return _json_problem(404, str(error))
    if isinstance(error, UnknownPresetError):
        return _json_problem(404, "unknown preset")
    if isinstance(error, (DraftConflictError, ArchivedScenarioError)):
        return _json_problem(409, str(error))
    if isinstance(error, SaveAndRunBlocked):
        return _json_problem(409, str(error))
    if isinstance(error, SerializationError):
        return JSONResponse(
            {
                "detail": str(error),
                "stage": error.stage,
                "code": error.code,
                "path": error.path,
            },
            status_code=422,
        )
    if isinstance(error, InvalidDraftError):
        return _json_problem(422, str(error))
    if isinstance(
        error,
        (AuthoringActionError, PreflightContractError, ProviderError, ScenarioSpecError),
    ):
        return _json_problem(400, str(error))
    if isinstance(error, ConfirmationError):
        return _json_problem(409, str(error))
    raise error


def create_app(
    *,
    api: _BusinessAPI,
    coordinator: _Coordinator,
    port: int = DEFAULT_PORT,
    csrf_token: str | None = None,
    static_root: Path | None = None,
) -> ScenarioForgeWebApplication:
    """Assemble the fixed local API and immutable static replay surface."""
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("port must be between 1 and 65535")
    token = secrets.token_urlsafe(32) if csrf_token is None else csrf_token
    if not isinstance(token, str) or len(token) < 32:
        raise ValueError("csrf_token must contain at least 32 characters")
    assets = (
        Path(static_root)
        if static_root is not None
        else Path(__file__).with_name("static")
    )
    if not assets.is_dir():
        raise ValueError("static asset directory is unavailable")
    shutdown = _ShutdownController(coordinator)

    @asynccontextmanager
    async def lifespan(_app: Starlette):
        yield
        await asyncio.to_thread(shutdown.finish)

    async def index(_request: Request) -> Response:
        return FileResponse(assets / "index.html", media_type="text/html")

    async def experiment_controls(_request: Request) -> Response:
        module = Path(__file__).parents[1] / "orchestration" / "experiment_controls.js"
        return FileResponse(module, media_type="text/javascript")

    async def replay_scene(_request: Request) -> Response:
        module = Path(__file__).parents[1] / "replay" / "replay_scene.js"
        return FileResponse(module, media_type="text/javascript")

    async def session(_request: Request) -> Response:
        return JSONResponse(
            {
                "schema_version": "scenarioforge.web-session/v1",
                "csrf_token": token,
            }
        )

    async def catalog(_request: Request) -> Response:
        return JSONResponse(api.get_catalog())

    async def start(request: Request) -> Response:
        try:
            scenario_id, idempotency_key = await _start_payload(request)
            payload = api.start_run(
                scenario_id,
                idempotency_key=idempotency_key,
            )
        except Exception as error:
            if isinstance(error, _RequestProblem):
                return _json_problem(error.status_code, error.detail)
            return _api_problem(error)
        run_id = payload.get("run_id")
        if not isinstance(run_id, str):
            return _json_problem(500, "run reference is invalid")
        shutdown.track(run_id)
        return JSONResponse(payload, status_code=201)

    async def status(request: Request) -> Response:
        try:
            payload = api.get_run_status(request.path_params["run_id"])
        except Exception as error:
            return _api_problem(error)
        return JSONResponse(payload)

    async def artifact(request: Request) -> Response:
        try:
            payload = api.get_run_artifact(
                request.path_params["run_id"],
                request.path_params["artifact_key"],
            )
        except Exception as error:
            return _api_problem(error)
        return JSONResponse(payload)

    async def p1_catalog(_request: Request) -> Response:
        try:
            payload = api.get_p1_catalog()
        except Exception as error:
            return _api_problem(error)
        return JSONResponse(payload)

    async def start_p1(request: Request) -> Response:
        try:
            scenario_id, idempotency_key = await _start_payload(request)
            payload = api.start_p1_run(
                scenario_id,
                idempotency_key=idempotency_key,
            )
        except Exception as error:
            if isinstance(error, _RequestProblem):
                return _json_problem(error.status_code, error.detail)
            return _api_problem(error)
        return JSONResponse(payload, status_code=201)

    async def p1_status(request: Request) -> Response:
        try:
            payload = api.get_p1_run_status(request.path_params["run_id"])
        except Exception as error:
            return _api_problem(error)
        return JSONResponse(payload)

    async def p1_artifact(request: Request) -> Response:
        try:
            payload = api.get_p1_run_artifact(
                request.path_params["run_id"],
                request.path_params["artifact_key"],
            )
        except Exception as error:
            return _api_problem(error)
        return JSONResponse(payload)

    async def experiments(_request: Request) -> Response:
        try:
            payload = api.list_experiments()
        except Exception as error:
            return _api_problem(error)
        return JSONResponse(payload)

    async def submit_experiment(request: Request) -> Response:
        try:
            body = await _request_payload(request)
            payload = api.submit_experiment(
                body,
                idempotency_key=_single_header(request, "idempotency-key"),
            )
        except Exception as error:
            if isinstance(error, _RequestProblem):
                return _json_problem(error.status_code, error.detail)
            return _api_problem(error)
        return JSONResponse(payload, status_code=201)

    async def experiment(request: Request) -> Response:
        try:
            payload = api.get_experiment(request.path_params["experiment_id"])
        except Exception as error:
            return _api_problem(error)
        return JSONResponse(payload)

    async def control_experiment(request: Request) -> Response:
        try:
            body = _exact_fields(
                await _request_payload(request),
                {"operation", "command_id"},
            )
            operation = body["operation"]
            command_id = body["command_id"]
            if not isinstance(operation, str) or not isinstance(command_id, str):
                raise _RequestProblem(400, "operation and command_id must be strings")
            payload = api.control_experiment(
                request.path_params["experiment_id"],
                operation,
                command_id=command_id,
            )
        except Exception as error:
            if isinstance(error, _RequestProblem):
                return _json_problem(error.status_code, error.detail)
            return _api_problem(error)
        return JSONResponse(payload)

    async def authoring_scenarios(request: Request) -> Response:
        include_archived = request.query_params.get("include_archived", "false")
        if include_archived not in {"true", "false"}:
            return _json_problem(400, "include_archived must be true or false")
        try:
            payload = api.list_authoring_scenarios(
                include_archived=include_archived == "true"
            )
        except Exception as error:
            return _api_problem(error)
        return JSONResponse(payload)

    async def create_authoring_draft(request: Request) -> Response:
        try:
            body = _exact_fields(await _request_payload(request), {"content"})
            payload = api.create_authoring_draft(_content(body))
        except Exception as error:
            if isinstance(error, _RequestProblem):
                return _json_problem(error.status_code, error.detail)
            return _api_problem(error)
        return JSONResponse(payload, status_code=201)

    async def normalize_authoring_content(request: Request) -> Response:
        try:
            body = _exact_fields(await _request_payload(request), {"content"})
            payload = api.normalize_authoring_content(_content(body))
        except Exception as error:
            if isinstance(error, _RequestProblem):
                return _json_problem(error.status_code, error.detail)
            return _api_problem(error)
        return JSONResponse(payload)

    async def create_authoring_intent_draft(request: Request) -> Response:
        try:
            body = _exact_fields(
                await _request_payload(request), {"prompt", "provider_id"}
            )
            prompt = body["prompt"]
            provider_id = body["provider_id"]
            if not isinstance(prompt, str) or not isinstance(provider_id, str):
                raise _RequestProblem(400, "prompt and provider_id must be strings")
            payload = api.create_authoring_intent_draft(
                prompt,
                provider_id=provider_id,
            )
        except Exception as error:
            if isinstance(error, _RequestProblem):
                return _json_problem(error.status_code, error.detail)
            return _api_problem(error)
        return JSONResponse(payload, status_code=201)

    async def authoring_draft(request: Request) -> Response:
        scenario_id = request.path_params["scenario_id"]
        try:
            if request.method == "GET":
                payload = api.get_authoring_draft(scenario_id)
            else:
                body = _exact_fields(
                    await _request_payload(request),
                    {"content", "expected_generation"},
                )
                payload = api.update_authoring_draft(
                    scenario_id,
                    _content(body),
                    expected_generation=_generation(body),
                )
        except Exception as error:
            if isinstance(error, _RequestProblem):
                return _json_problem(error.status_code, error.detail)
            return _api_problem(error)
        return JSONResponse(payload)

    async def validate_authoring_draft(request: Request) -> Response:
        try:
            payload = api.validate_authoring_draft(request.path_params["scenario_id"])
        except Exception as error:
            return _api_problem(error)
        return JSONResponse(payload)

    async def save_authoring_draft(request: Request) -> Response:
        try:
            body = _exact_fields(
                await _request_payload(request), {"expected_generation"}
            )
            payload = api.save_authoring_draft(
                request.path_params["scenario_id"],
                expected_generation=_generation(body),
            )
        except Exception as error:
            if isinstance(error, _RequestProblem):
                return _json_problem(error.status_code, error.detail)
            return _api_problem(error)
        return JSONResponse(payload, status_code=201)

    async def authoring_history(request: Request) -> Response:
        try:
            payload = api.get_authoring_history(request.path_params["scenario_id"])
        except Exception as error:
            return _api_problem(error)
        return JSONResponse(payload)

    async def authoring_revision(request: Request) -> Response:
        try:
            payload = api.get_authoring_revision(request.path_params["revision_id"])
        except Exception as error:
            return _api_problem(error)
        return JSONResponse(payload)

    async def clone_authoring_scenario(request: Request) -> Response:
        try:
            _exact_fields(await _request_payload(request), set())
            payload = api.clone_authoring_draft(request.path_params["scenario_id"])
        except Exception as error:
            if isinstance(error, _RequestProblem):
                return _json_problem(error.status_code, error.detail)
            return _api_problem(error)
        return JSONResponse(payload, status_code=201)

    async def archive_authoring_scenario(request: Request) -> Response:
        try:
            _exact_fields(await _request_payload(request), set())
            payload = api.archive_authoring_scenario(
                request.path_params["scenario_id"]
            )
        except Exception as error:
            if isinstance(error, _RequestProblem):
                return _json_problem(error.status_code, error.detail)
            return _api_problem(error)
        return JSONResponse(payload)

    async def authoring_presets(_request: Request) -> Response:
        try:
            payload = api.get_authoring_presets()
        except Exception as error:
            return _api_problem(error)
        return JSONResponse(payload)

    async def fork_authoring_preset(request: Request) -> Response:
        try:
            body = _exact_fields(await _request_payload(request), {"content"})
            payload = api.fork_authoring_preset(
                request.path_params["template_id"], _content(body)
            )
        except Exception as error:
            if isinstance(error, _RequestProblem):
                return _json_problem(error.status_code, error.detail)
            return _api_problem(error)
        return JSONResponse(payload, status_code=201)

    async def import_authoring_draft(request: Request) -> Response:
        try:
            body = _exact_fields(
                await _request_payload(request), {"content", "format"}
            )
            content = body["content"]
            format = body["format"]
            if not isinstance(content, str) or not isinstance(format, str):
                raise _RequestProblem(400, "import content and format must be strings")
            payload = api.import_authoring_draft(content, format=format)
        except Exception as error:
            if isinstance(error, _RequestProblem):
                return _json_problem(error.status_code, error.detail)
            return _api_problem(error)
        return JSONResponse(payload, status_code=201)

    async def export_authoring_draft(request: Request) -> Response:
        format = request.query_params.get("format")
        if format not in {"json", "yaml"}:
            return _json_problem(400, "format must be json or yaml")
        try:
            payload = api.export_authoring_draft(
                request.path_params["scenario_id"], format=format
            )
        except Exception as error:
            return _api_problem(error)
        return JSONResponse(payload)

    async def preflight_authoring_revision(request: Request) -> Response:
        try:
            _exact_fields(await _request_payload(request), set())
            payload = api.preflight_authoring_revision(
                request.path_params["revision_id"]
            )
        except Exception as error:
            if isinstance(error, _RequestProblem):
                return _json_problem(error.status_code, error.detail)
            return _api_problem(error)
        return JSONResponse(payload)

    async def preflight_p1_authoring_revision(request: Request) -> Response:
        try:
            body = _exact_fields(await _request_payload(request), {"backend_id"})
            backend_id = body["backend_id"]
            if not isinstance(backend_id, str):
                raise _RequestProblem(400, "backend_id must be a string")
            payload = api.preflight_p1_authoring_revision(
                request.path_params["revision_id"],
                backend_id=backend_id,
            )
        except Exception as error:
            if isinstance(error, _RequestProblem):
                return _json_problem(error.status_code, error.detail)
            return _api_problem(error)
        return JSONResponse(payload)

    async def confirm_p1_authoring(request: Request) -> Response:
        try:
            _exact_fields(await _request_payload(request), set())
            payload = api.confirm_p1_authoring(request.path_params["preflight_id"])
        except Exception as error:
            if isinstance(error, _RequestProblem):
                return _json_problem(error.status_code, error.detail)
            return _api_problem(error)
        return JSONResponse(payload, status_code=201)

    async def authorize_p1_authoring_run(request: Request) -> Response:
        try:
            body = _exact_fields(await _request_payload(request), {"authorization"})
            authorization = body["authorization"]
            if not isinstance(authorization, dict):
                raise _RequestProblem(400, "authorization must be a JSON object")
            payload = api.authorize_p1_authoring_run(
                request.path_params["preflight_id"], authorization
            )
        except Exception as error:
            if isinstance(error, _RequestProblem):
                return _json_problem(error.status_code, error.detail)
            return _api_problem(error)
        return JSONResponse(payload, status_code=201)

    async def run_authoring_revision(request: Request) -> Response:
        try:
            _exact_fields(await _request_payload(request), set())
            payload = await asyncio.to_thread(
                api.run_authoring_revision,
                request.path_params["revision_id"],
                idempotency_key=_single_header(request, "idempotency-key"),
            )
        except Exception as error:
            if isinstance(error, _RequestProblem):
                return _json_problem(error.status_code, error.detail)
            return _api_problem(error)
        run_id = payload.get("run_id")
        if not isinstance(run_id, str):
            return _json_problem(500, "run reference is invalid")
        shutdown.track(run_id)
        return JSONResponse(payload, status_code=201)

    routes = [
        Route("/", index, methods=["GET"]),
        Route("/api/session", session, methods=["GET"]),
        Route("/api/scenarios", catalog, methods=["GET"]),
        Route("/api/runs", start, methods=["POST"]),
        Route("/api/runs/{run_id}", status, methods=["GET"]),
        Route(
            "/api/runs/{run_id}/artifacts/{artifact_key}",
            artifact,
            methods=["GET"],
        ),
        Route("/api/p1/scenarios", p1_catalog, methods=["GET"]),
        Route("/api/p1/runs", start_p1, methods=["POST"]),
        Route("/api/p1/runs/{run_id}", p1_status, methods=["GET"]),
        Route(
            "/api/p1/runs/{run_id}/artifacts/{artifact_key}",
            p1_artifact,
            methods=["GET"],
        ),
        Route("/api/experiments", experiments, methods=["GET"]),
        Route("/api/experiments", submit_experiment, methods=["POST"]),
        Route(
            "/api/experiments/{experiment_id}",
            experiment,
            methods=["GET"],
        ),
        Route(
            "/api/experiments/{experiment_id}/commands",
            control_experiment,
            methods=["POST"],
        ),
        Route("/api/authoring/scenarios", authoring_scenarios, methods=["GET"]),
        Route("/api/authoring/drafts", create_authoring_draft, methods=["POST"]),
        Route("/api/authoring/normalize", normalize_authoring_content, methods=["POST"]),
        Route(
            "/api/authoring/provider-drafts",
            create_authoring_intent_draft,
            methods=["POST"],
        ),
        Route(
            "/api/authoring/drafts/{scenario_id}",
            authoring_draft,
            methods=["GET", "PUT"],
        ),
        Route(
            "/api/authoring/drafts/{scenario_id}/validation",
            validate_authoring_draft,
            methods=["GET"],
        ),
        Route(
            "/api/authoring/drafts/{scenario_id}/revisions",
            save_authoring_draft,
            methods=["POST"],
        ),
        Route(
            "/api/authoring/drafts/{scenario_id}/export",
            export_authoring_draft,
            methods=["GET"],
        ),
        Route(
            "/api/authoring/scenarios/{scenario_id}/history",
            authoring_history,
            methods=["GET"],
        ),
        Route(
            "/api/authoring/scenarios/{scenario_id}/clone",
            clone_authoring_scenario,
            methods=["POST"],
        ),
        Route(
            "/api/authoring/scenarios/{scenario_id}/archive",
            archive_authoring_scenario,
            methods=["POST"],
        ),
        Route("/api/authoring/revisions/{revision_id}", authoring_revision, methods=["GET"]),
        Route(
            "/api/authoring/revisions/{revision_id}/preflight",
            preflight_authoring_revision,
            methods=["POST"],
        ),
        Route(
            "/api/authoring/revisions/{revision_id}/p1-preflight",
            preflight_p1_authoring_revision,
            methods=["POST"],
        ),
        Route(
            "/api/authoring/p1-preflights/{preflight_id}/confirm",
            confirm_p1_authoring,
            methods=["POST"],
        ),
        Route(
            "/api/authoring/p1-preflights/{preflight_id}/authorize-run",
            authorize_p1_authoring_run,
            methods=["POST"],
        ),
        Route(
            "/api/authoring/revisions/{revision_id}/runs",
            run_authoring_revision,
            methods=["POST"],
        ),
        Route("/api/authoring/presets", authoring_presets, methods=["GET"]),
        Route(
            "/api/authoring/presets/{template_id}/fork",
            fork_authoring_preset,
            methods=["POST"],
        ),
        Route("/api/authoring/import", import_authoring_draft, methods=["POST"]),
        Route(
            "/static/experiment_controls.js",
            experiment_controls,
            methods=["GET"],
        ),
        Route("/static/replay_scene.js", replay_scene, methods=["GET"]),
        Mount("/static", app=StaticFiles(directory=assets), name="static"),
    ]
    return ScenarioForgeWebApplication(
        Starlette(routes=routes, lifespan=lifespan),
        shutdown=shutdown,
        port=port,
        csrf_token=token,
    )


def serve(
    *,
    workspace: Path,
    project_root: Path,
    port: int = DEFAULT_PORT,
    timeout_seconds: int = 120,
) -> None:
    """Launch one non-proxied service bound exclusively to IPv4 loopback."""
    coordinator = RunCoordinator(
        workspace=workspace,
        project_root=project_root,
        timeout_seconds=timeout_seconds,
        catalog_profile="p0c",
    )
    p1_coordinator = P1RunCoordinator(workspace=workspace)
    evidence = RevisionAwareEvidenceReader(
        PublishedEvidenceReader(publish_root=Path(workspace) / "published")
    )
    library = LocalScenarioLibrary(Path(workspace) / "authoring-library")
    authoring_runner = RunSupervisor(
        workspace=workspace,
        project_root=project_root,
    )
    experiment_service = ExperimentService(
        store=ExperimentStore(Path(workspace)),
        runner_factory=ScenarioForgeRunnerFactory(
            workspace=Path(workspace),
            project_root=Path(project_root),
        ),
    )
    api = ScenarioForgeAPI(
        coordinator=coordinator,
        evidence=evidence,
        p1_coordinator=p1_coordinator,
        catalog_profile="p0c",
        library=library,
        authoring_runner=authoring_runner,
        authoring_timeout_seconds=timeout_seconds,
        experiment_service=experiment_service,
    )
    app = create_app(api=api, coordinator=coordinator, port=port)
    config = uvicorn.Config(
        app,
        host=LOOPBACK_HOST,
        port=port,
        proxy_headers=False,
        server_header=False,
        timeout_graceful_shutdown=15,
    )
    LoopbackServer(config, shutdown=app.shutdown).run()


__all__ = [
    "CONTENT_SECURITY_POLICY",
    "DEFAULT_PORT",
    "LOOPBACK_HOST",
    "LoopbackServer",
    "ScenarioForgeWebApplication",
    "create_app",
    "serve",
]
