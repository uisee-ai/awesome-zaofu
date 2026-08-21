from __future__ import annotations

import hashlib
import re
import secrets
import shutil
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol

from scenarioforge.authoring.actions import (
    AuthoringActionError,
    AuthoringActionService,
)
from scenarioforge.authoring.library import LocalScenarioLibrary
from scenarioforge.authoring.p1_preflight import (
    AuthoringPreflightReport,
    evaluate_preflight,
)
from scenarioforge.authoring.preflight import PreflightService
from scenarioforge.authoring.presets import PresetCatalog
from scenarioforge.authoring.providers import (
    OfflineReferenceProvider,
    ProviderRegistry,
    ScenarioDraftProvider,
)
from scenarioforge.authoring.save_and_run import Runner, SaveAndRunService
from scenarioforge.authoring.scenario_spec import (
    NormalizedScenarioSpec,
    normalize_scenario_spec,
)
from scenarioforge.authoring.serialization import export_authoring, import_authoring
from scenarioforge.authoring.validation import validate_authoring_spec
from scenarioforge.core.canonical import canonical_bytes, canonical_digest, thaw_json
from scenarioforge.core.strict_json import strict_loads
from scenarioforge.orchestration.contracts import ExperimentDefinition
from scenarioforge.runtime.confirmation import RunAuthorization
from scenarioforge.runtime.contracts import (
    RunResult,
    TraceabilityError,
    validate_run_traceability,
)

from .catalog import (
    p1_scenario_catalog,
    p1_scenario_metadata,
    scenario_catalog,
    scenario_metadata,
)
from .coordinator import (
    ExecutionState,
    P1RunCoordinator,
    RunCoordinator,
    RunReference,
    UnknownRunError,
)
from .evidence import (
    EvidenceValidationError,
    PublishedEvidenceReader,
    validate_artifact_key,
)

_SAFE_EVIDENCE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


class RevisionAwareEvidenceReader:
    """Validate v3 revision traceability, then reuse the strict v2 projection reader."""

    def __init__(self, delegate: PublishedEvidenceReader) -> None:
        self._delegate = delegate

    @staticmethod
    def _canonical_object(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
        if path.is_symlink() or not path.is_file():
            raise EvidenceValidationError(f"{label} is unavailable")
        payload = path.read_bytes()
        if len(payload) > 10_485_760:
            raise EvidenceValidationError(f"{label} exceeds the size limit")
        try:
            value = strict_loads(payload)
        except (TypeError, ValueError) as error:
            raise EvidenceValidationError(f"{label} is not valid strict JSON") from error
        if not isinstance(value, dict) or canonical_bytes(value) != payload:
            raise EvidenceValidationError(f"{label} is not canonical strict JSON")
        return value, payload

    def _root(self, run_id: str, attempt_id: str) -> Path:
        if (
            not isinstance(run_id, str)
            or _SAFE_EVIDENCE_ID.fullmatch(run_id) is None
            or not isinstance(attempt_id, str)
            or _SAFE_EVIDENCE_ID.fullmatch(attempt_id) is None
        ):
            raise EvidenceValidationError("published evidence identity is invalid")
        publish_root = self._delegate.publish_root
        if publish_root.is_symlink():
            raise EvidenceValidationError("publish-root containment validation failed")
        try:
            boundary = publish_root.resolve(strict=True)
            root = (publish_root / run_id / attempt_id).resolve(strict=True)
            root.relative_to(boundary)
        except (FileNotFoundError, ValueError) as error:
            raise EvidenceValidationError("published evidence is unavailable") from error
        if root.is_symlink() or not root.is_dir():
            raise EvidenceValidationError("published evidence is unavailable")
        return root

    @staticmethod
    def _digest(value: object, label: str) -> str:
        if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
            raise EvidenceValidationError(f"{label} is invalid")
        return value

    def _v3_contract(
        self,
        root: Path,
        run_id: str,
        attempt_id: str,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]] | None:
        result, result_payload = self._canonical_object(root / "run_result.json", "RunResult")
        if result.get("schema_version") != "scenarioforge.run-result/v3":
            return None
        index, index_payload = self._canonical_object(
            root / "artifact_index.json", "ArtifactIndex"
        )
        marker, _ = self._canonical_object(root / "SUCCESS", "completion marker")
        manifest, manifest_payload = self._canonical_object(
            root / "input" / "run_manifest.json", "RunManifest"
        )
        result_fields = {
            "schema_version",
            "run_id",
            "attempt_id",
            "worker_exit_code",
            "run_manifest_digest",
            "compile_report_digest",
            "execution_plan_digest",
            "artifact_index_digest",
            "execution_status",
            "scenario_outcome",
            "termination_reason",
            "traceability_digest",
            "scenario_revision_digest",
        }
        index_fields = {
            "schema_version",
            "run_id",
            "attempt_id",
            "artifacts",
            "run_manifest_digest",
            "execution_status",
            "scenario_outcome",
            "termination_reason",
            "traceability_digest",
            "scenario_revision_digest",
        }
        marker_fields = {
            "schema_version",
            "execution_status",
            "scenario_outcome",
            "termination_reason",
            "run_result_digest",
            "artifact_index_digest",
        }
        if (
            set(result) != result_fields
            or set(index) != index_fields
            or set(marker) != marker_fields
            or index.get("schema_version") != "scenarioforge.artifact-index/v3"
            or marker.get("schema_version") != "scenarioforge.completion-marker/v2"
        ):
            raise EvidenceValidationError("revision-aware publication fields are invalid")
        if (
            result.get("run_id") != run_id
            or result.get("attempt_id") != attempt_id
            or index.get("run_id") != run_id
            or index.get("attempt_id") != attempt_id
        ):
            raise EvidenceValidationError("revision-aware publication identity is invalid")
        axes = ("execution_status", "scenario_outcome", "termination_reason")
        if any(
            result.get(field) != index.get(field)
            or result.get(field) != marker.get(field)
            for field in axes
        ) or result.get("execution_status") != "completed":
            raise EvidenceValidationError("revision-aware terminal axes are invalid")
        if (
            hashlib.sha256(result_payload).hexdigest() != marker.get("run_result_digest")
            or hashlib.sha256(index_payload).hexdigest()
            != marker.get("artifact_index_digest")
            or canonical_digest(index) != result.get("artifact_index_digest")
            or hashlib.sha256(manifest_payload).hexdigest()
            != result.get("run_manifest_digest")
            or result.get("run_manifest_digest") != index.get("run_manifest_digest")
        ):
            raise EvidenceValidationError("revision-aware publication digest is invalid")
        trace = manifest.get("traceability")
        revision = manifest.get("scenario_revision")
        instance = manifest.get("scenario_instance")
        if not isinstance(trace, dict) or not isinstance(revision, dict) or not isinstance(instance, dict):
            raise EvidenceValidationError("revision-aware traceability is incomplete")
        trace_digest = canonical_digest(trace)
        revision_digest = revision.get("digest")
        if (
            result.get("traceability_digest") != trace_digest
            or index.get("traceability_digest") != trace_digest
            or result.get("scenario_revision_digest") != revision_digest
            or index.get("scenario_revision_digest") != revision_digest
            or manifest.get("scenario_instance_digest") != canonical_digest(instance)
            or instance.get("source_spec_digest") != revision_digest
        ):
            raise EvidenceValidationError("revision-aware traceability digest is invalid")
        report, _ = self._canonical_object(
            root / "input" / "compile_report.json", "CompileReport"
        )
        plan, _ = self._canonical_object(
            root / "input" / "execution_plan.json", "ExecutionPlan"
        )
        assets, _ = self._canonical_object(root / "input" / "assets.json", "assets")
        bundle: dict[str, object] = {
            "scenario_instance": instance,
            "report": report,
            "execution_plan": plan,
        }
        if "lossy_confirmation" in manifest:
            bundle["confirmation"] = manifest["lossy_confirmation"]
        if (
            manifest.get("compile_bundle_digest") != canonical_digest(bundle)
            or not isinstance(manifest.get("assets"), dict)
            or manifest["assets"].get("digest") != canonical_digest(assets)
        ):
            raise EvidenceValidationError("revision-aware frozen input digest is invalid")
        run_result = RunResult(
            schema_version="scenarioforge.run-result/v3",
            run_id=run_id,
            attempt_id=attempt_id,
            status="success",
            reason=str(result["termination_reason"]),
            worker_exit_code=int(result["worker_exit_code"]),
            run_manifest_digest=str(result["run_manifest_digest"]),
            compile_report_digest=str(result["compile_report_digest"]),
            execution_plan_digest=str(result["execution_plan_digest"]),
            artifact_index_digest=str(result["artifact_index_digest"]),
            execution_status=str(result["execution_status"]),
            scenario_outcome=str(result["scenario_outcome"]),
            termination_reason=str(result["termination_reason"]),
            traceability_digest=str(result["traceability_digest"]),
            scenario_revision_digest=str(result["scenario_revision_digest"]),
        )
        try:
            validate_run_traceability(manifest, run_result)
        except TraceabilityError as error:
            raise EvidenceValidationError("revision-aware traceability is invalid") from error
        return manifest, result, index

    @staticmethod
    def _write_canonical(path: Path, value: Mapping[str, Any]) -> None:
        path.chmod(0o600)
        path.write_bytes(canonical_bytes(value))
        path.chmod(0o444)

    def _project_v2(
        self,
        destination: Path,
        manifest: dict[str, Any],
        result: dict[str, Any],
        index: dict[str, Any],
    ) -> None:
        projected_manifest = dict(manifest)
        projected_manifest["schema_version"] = "scenarioforge.run-manifest/v2"
        projected_manifest.pop("compile_bundle_digest")
        projected_manifest.pop("scenario_revision")
        projected_manifest.pop("traceability")
        projected_instance = dict(projected_manifest["scenario_instance"])
        for field in ("revision_id", "revision_digest", "revision_schema_version"):
            projected_instance.pop(field)
        projected_instance["schema_version"] = "scenarioforge.scenario-instance/v2"
        projected_manifest["scenario_instance"] = projected_instance
        projected_manifest["scenario_instance_digest"] = canonical_digest(projected_instance)
        manifest_payload = canonical_bytes(projected_manifest)
        manifest_digest = hashlib.sha256(manifest_payload).hexdigest()

        projected_index = dict(index)
        projected_index["schema_version"] = "scenarioforge.artifact-index/v2"
        projected_index.pop("traceability_digest")
        projected_index.pop("scenario_revision_digest")
        projected_index["run_manifest_digest"] = manifest_digest
        entries = [dict(entry) for entry in projected_index["artifacts"]]
        manifest_entry = next(
            (entry for entry in entries if entry.get("path") == "input/run_manifest.json"),
            None,
        )
        if manifest_entry is None:
            raise EvidenceValidationError("revision-aware manifest is not indexed")
        manifest_entry["size_bytes"] = len(manifest_payload)
        manifest_entry["digest"] = manifest_digest
        projected_index["artifacts"] = entries

        projected_result = dict(result)
        projected_result["schema_version"] = "scenarioforge.run-result/v2"
        projected_result.pop("traceability_digest")
        projected_result.pop("scenario_revision_digest")
        projected_result["run_manifest_digest"] = manifest_digest
        projected_result["artifact_index_digest"] = canonical_digest(projected_index)

        marker, _ = self._canonical_object(destination / "SUCCESS", "completion marker")
        marker["run_result_digest"] = hashlib.sha256(
            canonical_bytes(projected_result)
        ).hexdigest()
        marker["artifact_index_digest"] = hashlib.sha256(
            canonical_bytes(projected_index)
        ).hexdigest()
        self._write_canonical(destination / "input" / "run_manifest.json", projected_manifest)
        self._write_canonical(destination / "artifact_index.json", projected_index)
        self._write_canonical(destination / "run_result.json", projected_result)
        self._write_canonical(destination / "SUCCESS", marker)

    def _read(self, method: str, run_id: str, attempt_id: str) -> dict[str, object]:
        root = self._root(run_id, attempt_id)
        contract = self._v3_contract(root, run_id, attempt_id)
        if contract is None:
            return getattr(self._delegate, method)(run_id, attempt_id)
        manifest, result, index = contract
        with tempfile.TemporaryDirectory(prefix="scenarioforge-v3-projection-") as temporary:
            shadow_root = Path(temporary) / "published" / run_id / attempt_id
            shutil.copytree(root, shadow_root, symlinks=True)
            self._project_v2(shadow_root, manifest, result, index)
            payload = getattr(
                PublishedEvidenceReader(publish_root=Path(temporary) / "published"),
                method,
            )(run_id, attempt_id)
        payload["scenario_revision"] = dict(manifest["scenario_revision"])
        payload["revision_traceability"] = dict(manifest["traceability"])
        payload["traceability_digest"] = result["traceability_digest"]
        return payload

    def terminal(self, run_id: str, attempt_id: str) -> dict[str, object]:
        return self._read("terminal", run_id, attempt_id)

    def playback(self, run_id: str, attempt_id: str) -> dict[str, object]:
        return self._read("playback", run_id, attempt_id)


class _Coordinator(Protocol):
    def start(self, scenario_id: str, *, idempotency_key: str) -> RunReference: ...

    def active_state(self, run_id: str) -> ExecutionState | None: ...

    def reference(self, run_id: str) -> RunReference: ...


class _EvidenceReader(Protocol):
    def terminal(self, run_id: str, attempt_id: str) -> dict[str, object]: ...

    def playback(self, run_id: str, attempt_id: str) -> dict[str, object]: ...


class _P1Coordinator(Protocol):
    def start(self, scenario_id: str, *, idempotency_key: str) -> RunReference: ...

    def active_state(self, run_id: str) -> ExecutionState | None: ...

    def terminal(self, run_id: str) -> dict[str, object]: ...

    def playback(self, run_id: str) -> dict[str, object]: ...


class _ExperimentService(Protocol):
    def submit(
        self,
        definition: ExperimentDefinition,
        *,
        idempotency_key: str,
    ) -> dict[str, object]: ...

    def list(self) -> dict[str, object]: ...

    def get(self, experiment_id: str) -> dict[str, object]: ...

    def control(
        self,
        experiment_id: str,
        operation: str,
        *,
        command_id: str,
    ) -> dict[str, object]: ...


class ScenarioForgeAPI:
    """Transport-neutral business API consumed by the loopback server adapter."""

    def __init__(
        self,
        *,
        coordinator: _Coordinator,
        evidence: _EvidenceReader,
        p1_coordinator: _P1Coordinator | None = None,
        catalog_profile: str = "p0b",
        library: LocalScenarioLibrary | None = None,
        authoring_runner: Runner | None = None,
        authoring_timeout_seconds: float = 120,
        experiment_service: _ExperimentService | None = None,
        registered_authoring_adapter_ids: tuple[str, ...] = (
            "scenarioforge.metadrive",
        ),
        authoring_providers: tuple[ScenarioDraftProvider, ...] | None = None,
    ) -> None:
        if catalog_profile not in {"p0b", "p0c"}:
            raise ValueError("unknown scenario catalog profile")
        self._coordinator = coordinator
        self._evidence = evidence
        self._p1_coordinator = p1_coordinator
        self._experiment_service = experiment_service
        self._catalog_profile = catalog_profile
        self._library = library
        self._presets = PresetCatalog()
        self._preflight = PreflightService()
        self._authoring = (
            SaveAndRunService(library=library, runner=authoring_runner)
            if library is not None and authoring_runner is not None
            else None
        )
        if authoring_timeout_seconds <= 0:
            raise ValueError("authoring_timeout_seconds must be positive")
        self._authoring_timeout_seconds = authoring_timeout_seconds
        self._authoring_runs: dict[str, RunReference] = {}
        self._authoring_idempotency: dict[str, dict[str, object]] = {}
        self._authoring_providers = ProviderRegistry(
            authoring_providers or (OfflineReferenceProvider(),)
        )
        self._authoring_actions = AuthoringActionService(
            registered_adapter_ids=registered_authoring_adapter_ids
        )
        self._registered_authoring_adapters = frozenset(
            registered_authoring_adapter_ids
        )
        self._p1_preflights: dict[
            str,
            tuple[str, NormalizedScenarioSpec, AuthoringPreflightReport],
        ] = {}

    def _authoring_library(self) -> LocalScenarioLibrary:
        if self._library is None:
            raise RuntimeError("authoring library is unavailable")
        return self._library

    @staticmethod
    def _normalized_authoring_content(
        content: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        if content.get("schema_version") not in {None, "scenarioforge.authoring/v1"}:
            return content
        return thaw_json(normalize_scenario_spec(content).content)

    @staticmethod
    def normalize_authoring_content(
        content: Mapping[str, Any],
    ) -> dict[str, object]:
        return normalize_scenario_spec(content).to_dict()

    def create_authoring_intent_draft(
        self,
        prompt: str,
        *,
        provider_id: str = "scenarioforge.offline-reference",
    ) -> dict[str, object]:
        return self._authoring_providers.create_draft(provider_id, prompt).to_dict()

    def create_authoring_draft(self, content: Mapping[str, Any]) -> dict[str, object]:
        normalized = self._normalized_authoring_content(content)
        return self._authoring_library().create_draft(normalized).to_dict()

    def get_authoring_draft(self, scenario_id: str) -> dict[str, object]:
        return self._authoring_library().get_draft(scenario_id).to_dict()

    def list_authoring_scenarios(
        self, *, include_archived: bool = False
    ) -> dict[str, object]:
        scenarios = self._authoring_library().list_scenarios(
            include_archived=include_archived
        )
        return {
            "schema_version": "scenarioforge.authoring-catalog/v1",
            "scenarios": [scenario.to_dict() for scenario in scenarios],
        }

    def clone_authoring_draft(self, scenario_id: str) -> dict[str, object]:
        source = self._authoring_library().get_draft(scenario_id)
        content = thaw_json(source.content)
        if not isinstance(content, dict):
            raise RuntimeError("stored draft is invalid")
        return self._authoring_library().create_draft(content).to_dict()

    def update_authoring_draft(
        self,
        scenario_id: str,
        content: Mapping[str, Any],
        *,
        expected_generation: int,
    ) -> dict[str, object]:
        return self._authoring_library().update_draft(
            scenario_id,
            self._normalized_authoring_content(content),
            expected_generation=expected_generation,
        ).to_dict()

    def validate_authoring_draft(self, scenario_id: str) -> dict[str, object]:
        draft = self._authoring_library().get_draft(scenario_id)
        return validate_authoring_spec(thaw_json(draft.content)).to_dict()

    def save_authoring_draft(
        self,
        scenario_id: str,
        *,
        expected_generation: int,
    ) -> dict[str, object]:
        return self._authoring_library().save_draft(
            scenario_id,
            expected_generation=expected_generation,
        ).to_dict()

    def get_authoring_revision(self, revision_id: str) -> dict[str, object]:
        return self._authoring_library().get_revision(revision_id).to_dict()

    def get_authoring_history(self, scenario_id: str) -> dict[str, object]:
        revisions = self._authoring_library().history(scenario_id)
        return {
            "schema_version": "scenarioforge.authoring-history/v1",
            "scenario_id": scenario_id,
            "revisions": [revision.to_dict() for revision in revisions],
        }

    def archive_authoring_scenario(self, scenario_id: str) -> dict[str, object]:
        return self._authoring_library().archive_scenario(scenario_id).to_dict()

    def get_authoring_presets(self) -> dict[str, object]:
        return {
            "schema_version": "scenarioforge.authoring-presets/v1",
            "templates": [
                self._presets.get(template_id).to_dict()
                for template_id in self._presets.template_ids
            ],
        }

    def fork_authoring_preset(
        self,
        template_id: str,
        content: Mapping[str, Any] | None = None,
    ) -> dict[str, object]:
        return self._authoring_library().fork_preset(
            template_id,
            content,
        ).to_dict()

    @staticmethod
    def export_authoring_content(
        content: Mapping[str, Any], *, format: str
    ) -> dict[str, object]:
        payload = export_authoring(content, format=format)
        return {
            "schema_version": "scenarioforge.authoring-export/v1",
            "format": format,
            "content": payload.decode("utf-8"),
            "digest": hashlib.sha256(payload).hexdigest(),
        }

    def import_authoring_draft(self, content: str, *, format: str) -> dict[str, object]:
        imported = import_authoring(content, format=format)
        value = thaw_json(imported.value)
        if not isinstance(value, dict):
            raise RuntimeError("imported authoring document is invalid")
        draft = self._authoring_library().create_draft(value)
        return {
            "schema_version": "scenarioforge.authoring-import/v1",
            "source_format": imported.source_format,
            "raw_digest": imported.raw_digest,
            "canonical_digest": imported.canonical_digest,
            "validation": imported.validation.to_dict(),
            "draft": draft.to_dict(),
        }

    def export_authoring_draft(
        self, scenario_id: str, *, format: str
    ) -> dict[str, object]:
        draft = self._authoring_library().get_draft(scenario_id)
        content = thaw_json(draft.content)
        if not isinstance(content, dict):
            raise RuntimeError("stored draft is invalid")
        return self.export_authoring_content(content, format=format)

    @staticmethod
    def _preflight_payload(result: object) -> dict[str, object]:
        revision = result.revision
        bundle = result.bundle
        execution_plan = bundle.execution_plan
        return {
            "schema_version": "scenarioforge.authoring-preflight/v1",
            "scenario_id": revision.scenario_id,
            "revision_id": revision.revision_id,
            "scenario_revision_digest": revision.canonical_digest,
            "status": result.status.value,
            "executable": result.executable,
            "requires_confirmation": result.requires_confirmation,
            "capabilities": result.capabilities.to_dict(),
            "report": result.report.to_dict(),
            "scenario_instance": result.scenario_instance.to_dict(),
            "compile_bundle_digest": bundle.digest,
            "execution_plan_digest": (
                None if execution_plan is None else execution_plan.digest
            ),
        }

    def preflight_authoring_revision(self, revision_id: str) -> dict[str, object]:
        revision = self._authoring_library().get_revision(revision_id)
        return self._preflight_payload(self._preflight.evaluate(revision))

    def preflight_p1_authoring_revision(
        self,
        revision_id: str,
        *,
        backend_id: str,
    ) -> dict[str, object]:
        if backend_id not in self._registered_authoring_adapters:
            raise AuthoringActionError(f"adapter is not registered: {backend_id}")
        revision = self._authoring_library().get_revision(revision_id)
        content = thaw_json(revision.content)
        if (
            not isinstance(content, dict)
            or content.get("schema_version") != "scenarioforge.authoring/v1"
        ):
            raise AuthoringActionError(
                "P1 preflight requires a normalized authoring ScenarioSpec"
            )
        normalized = normalize_scenario_spec(content)
        validation = validate_authoring_spec(thaw_json(normalized.content))
        if normalized.missing_fields or not validation.valid:
            capability_report = {
                "schema_version": "scenarioforge.capability-report/v1",
                "backend_id": backend_id,
                "status": "exact",
                "diagnostics": [],
            }
        else:
            compiled = self._preflight.evaluate(revision)
            if compiled.report.adapter_id != backend_id:
                raise AuthoringActionError(
                    f"adapter is not registered for this compiler: {backend_id}"
                )
            capability_diagnostics = [
                {
                    "path": item.path,
                    "source_semantics": item.capability,
                    "degraded_semantics": item.alternative or "no supported mapping",
                    "impact": item.reason,
                }
                for item in compiled.report.diagnostics
            ]
            capability_report = {
                "schema_version": "scenarioforge.capability-report/v1",
                "backend_id": backend_id,
                "adapter_version": compiled.report.adapter_version,
                "status": compiled.status.value,
                "diagnostics": capability_diagnostics,
            }
        report = evaluate_preflight(
            normalized,
            backend_id=backend_id,
            capability_report=capability_report,
        )
        preflight_id = f"preflight-{secrets.token_hex(16)}"
        self._p1_preflights[preflight_id] = (revision_id, normalized, report)
        return {
            "preflight_id": preflight_id,
            "revision_id": revision_id,
            "normalized_spec": normalized.to_dict(),
            **report.to_dict(),
        }

    def _p1_preflight(
        self, preflight_id: str
    ) -> tuple[str, NormalizedScenarioSpec, AuthoringPreflightReport]:
        try:
            return self._p1_preflights[preflight_id]
        except KeyError as error:
            raise AuthoringActionError("unknown or consumed P1 preflight") from error

    def confirm_p1_authoring(self, preflight_id: str) -> dict[str, object]:
        _revision_id, normalized, report = self._p1_preflight(preflight_id)
        return self._authoring_actions.confirm(normalized, report).to_dict()

    def authorize_p1_authoring_run(
        self,
        preflight_id: str,
        authorization: Mapping[str, Any],
    ) -> dict[str, object]:
        revision_id, normalized, report = self._p1_preflight(preflight_id)
        try:
            grant = RunAuthorization(**dict(authorization))
        except (TypeError, ValueError) as error:
            raise AuthoringActionError("run authorization payload is invalid") from error
        consumed = self._authoring_actions.authorize_run(grant, normalized, report)
        del self._p1_preflights[preflight_id]
        return {
            "schema_version": "scenarioforge.authoring-action-receipt/v1",
            "action": "run",
            "authorized": True,
            "authorization_id": consumed.authorization_id,
            "revision_id": revision_id,
            "backend_id": report.backend_id,
        }

    def run_authoring_revision(
        self,
        revision_id: str,
        *,
        idempotency_key: str,
    ) -> dict[str, object]:
        prior = self._authoring_idempotency.get(idempotency_key)
        if prior is not None:
            return dict(prior)
        if self._authoring is None:
            raise RuntimeError("authoring runner is unavailable")
        run_id = f"run-{secrets.token_hex(12)}"
        attempt_id = f"attempt-{secrets.token_hex(12)}"
        result = self._authoring.run_revision(
            revision_id,
            run_id=run_id,
            attempt_id=attempt_id,
            timeout_seconds=self._authoring_timeout_seconds,
        )
        revision = result.revision
        reference = RunReference(
            schema_version="scenarioforge.run-reference/v1",
            scenario_id=revision.scenario_id,
            run_id=run_id,
            attempt_id=attempt_id,
            published_ref=f"published/{run_id}/{attempt_id}",
        )
        self._authoring_runs[run_id] = reference
        payload = {
            **reference.to_dict(),
            "schema_version": "scenarioforge.authoring-run-reference/v1",
            "revision_id": revision.revision_id,
            "scenario_revision_digest": revision.canonical_digest,
        }
        self._authoring_idempotency[idempotency_key] = payload
        return dict(payload)

    def list_scenarios(self) -> dict[str, object]:
        return scenario_catalog(profile=self._catalog_profile)

    def _experiments(self) -> _ExperimentService:
        if self._experiment_service is None:
            raise RuntimeError("Experiment service is unavailable")
        return self._experiment_service

    def submit_experiment(
        self,
        definition: Mapping[str, object],
        *,
        idempotency_key: str,
    ) -> dict[str, object]:
        return self._experiments().submit(
            ExperimentDefinition.from_mapping(definition),
            idempotency_key=idempotency_key,
        )

    def list_experiments(self) -> dict[str, object]:
        return self._experiments().list()

    def get_experiment(self, experiment_id: str) -> dict[str, object]:
        return self._experiments().get(experiment_id)

    def control_experiment(
        self,
        experiment_id: str,
        operation: str,
        *,
        command_id: str,
    ) -> dict[str, object]:
        return self._experiments().control(
            experiment_id,
            operation,
            command_id=command_id,
        )

    def start_run(self, scenario_id: str, *, idempotency_key: str) -> dict[str, object]:
        scenario_metadata(scenario_id, profile=self._catalog_profile)
        return self._coordinator.start(
            scenario_id,
            idempotency_key=idempotency_key,
        ).to_dict()

    def _p1_runs(self) -> _P1Coordinator:
        if self._p1_coordinator is None:
            raise RuntimeError("P1 SMARTS Web runner is unavailable")
        return self._p1_coordinator

    def get_p1_catalog(self) -> dict[str, object]:
        return p1_scenario_catalog()

    def start_p1_run(
        self, scenario_id: str, *, idempotency_key: str
    ) -> dict[str, object]:
        p1_scenario_metadata(scenario_id)
        reference = self._p1_runs().start(
            scenario_id,
            idempotency_key=idempotency_key,
        )
        return {
            **reference.to_dict(),
            "backend": {"id": "scenarioforge.smarts", "version": "2.0.1"},
        }

    def get_p1_run_status(self, run_id: str) -> dict[str, object]:
        active = self._p1_runs().active_state(run_id)
        if active is not None:
            return active.to_dict()
        return self._p1_runs().terminal(run_id)

    def get_p1_run_artifact(
        self, run_id: str, artifact_key: str
    ) -> dict[str, object]:
        validate_artifact_key(artifact_key)
        return self._p1_runs().playback(run_id)

    def run_status(self, run_id: str) -> dict[str, object]:
        try:
            active = self._coordinator.active_state(run_id)
            if active is not None:
                return active.to_dict()
            reference = self._coordinator.reference(run_id)
        except UnknownRunError:
            try:
                reference = self._authoring_runs[run_id]
            except KeyError as error:
                raise UnknownRunError("unknown run_id") from error
        return self._evidence.terminal(reference.run_id, reference.attempt_id)

    def run_artifact(self, run_id: str, artifact_key: str) -> dict[str, object]:
        validate_artifact_key(artifact_key)
        try:
            reference = self._coordinator.reference(run_id)
        except UnknownRunError:
            try:
                reference = self._authoring_runs[run_id]
            except KeyError as error:
                raise UnknownRunError("unknown run_id") from error
        return self._evidence.playback(reference.run_id, reference.attempt_id)

    # Readable aliases for server adapters that use HTTP-oriented naming.
    get_catalog = list_scenarios
    get_run_status = run_status
    get_run_artifact = run_artifact


BusinessAPI = ScenarioForgeAPI

__all__ = [
    "BusinessAPI",
    "P1RunCoordinator",
    "PublishedEvidenceReader",
    "RunCoordinator",
    "ScenarioForgeAPI",
]
