from __future__ import annotations

import hashlib
import os
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scenarioforge.core import canonical_bytes, canonical_digest, strict_loads

from .contracts import ArtifactEntry, ArtifactIndex, PreparedRun, RunResult
from .snapshot import INPUT_FILES, SnapshotError


@dataclass(frozen=True)
class _RevisionAwareArtifactIndex(ArtifactIndex):
    traceability_digest: str | None = None
    scenario_revision_digest: str | None = None

    def to_dict(self) -> dict[str, object]:
        value = super().to_dict()
        if None in {self.traceability_digest, self.scenario_revision_digest}:
            raise ValueError("v3 ArtifactIndex requires complete revision traceability")
        return {
            **value,
            "traceability_digest": self.traceability_digest,
            "scenario_revision_digest": self.scenario_revision_digest,
        }


def _write_json(path: Path, value: Any) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0), 0o600)
    try:
        payload = canonical_bytes(value)
        if os.write(descriptor, payload) != len(payload):
            raise SnapshotError(f"short write for {path.name}")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_staging(prepared: PreparedRun) -> tuple[str, ...]:
    plan = prepared.bundle.execution_plan
    assert plan is not None
    root = prepared.output_staging_path
    required = tuple(str(name) for name in plan.artifact_contract["required"])
    actual = tuple(sorted(path.name for path in root.iterdir()))
    if actual != tuple(sorted(required)):
        raise SnapshotError("OutputStaging required artifact set is incomplete or unexpected")
    total = 0
    maximum = int(plan.artifact_contract["max_file_bytes"])
    for path in root.iterdir():
        mode = path.lstat().st_mode
        if path.is_symlink() or not stat.S_ISREG(mode):
            raise SnapshotError(f"OutputStaging contains a link or special file: {path.name}")
        size = path.stat().st_size
        if size > maximum:
            raise SnapshotError(f"OutputStaging artifact exceeds size limit: {path.name}")
        total += size
        strict_loads(path.read_bytes())
    if total > int(plan.resource_config["artifact_limit_bytes"]):
        raise SnapshotError("OutputStaging exceeds the aggregate artifact limit")

    worker_result = strict_loads((root / "worker_result.json").read_bytes())
    metrics = strict_loads((root / "metrics.json").read_bytes())
    if not isinstance(worker_result, dict) or not isinstance(metrics, dict):
        raise SnapshotError("Worker result or metrics is not a JSON object")
    if worker_result["run_id"] != prepared.run_request.run_id:
        raise SnapshotError("Worker result run_id does not match RunRequest")
    if worker_result["attempt_id"] != prepared.run_request.attempt_id:
        raise SnapshotError("Worker result attempt_id does not match RunRequest")
    if worker_result["execution_plan_digest"] != prepared.run_request.execution_plan_digest:
        raise SnapshotError("Worker result plan digest does not match RunRequest")
    is_v2 = plan.schema_version == "scenarioforge.execution-plan/v2"
    if is_v2:
        terminal_fields = (
            "execution_status",
            "scenario_outcome",
            "termination_reason",
        )
        if any(worker_result.get(field) != metrics.get(field) for field in terminal_fields):
            raise SnapshotError("Worker result and metrics terminal axes do not match")
        if metrics.get("execution_status") != "completed":
            raise SnapshotError("success publisher requires completed v2 execution")
        if metrics.get("scenario_outcome") not in {
            "safe_pass",
            "near_miss",
            "collision_failure",
        }:
            raise SnapshotError("success publisher received an invalid v2 scenario outcome")
        if bool(metrics.get("collision")) != (
            metrics.get("scenario_outcome") == "collision_failure"
        ):
            raise SnapshotError("collision evidence and v2 scenario outcome do not match")
    elif worker_result["status"] != "completed" or metrics["terminal_status"] != "success":
        raise SnapshotError("success publisher received a non-success Worker result")
    return required


def _freeze(root: Path) -> None:
    for path in root.rglob("*"):
        if path.is_file():
            path.chmod(0o444)
    for path in sorted((candidate for candidate in root.rglob("*") if candidate.is_dir()), reverse=True):
        path.chmod(0o555)
    root.chmod(0o555)


def publish_success(
    prepared: PreparedRun,
    *,
    worker_exit_code: int,
) -> tuple[RunResult, ArtifactIndex]:
    required_outputs = _validate_staging(prepared)
    is_v2 = (
        prepared.bundle.execution_plan.schema_version
        == "scenarioforge.execution-plan/v2"
    )
    is_revision = (
        prepared.run_request.schema_version == "scenarioforge.run-request/v3"
    )
    traceability_digest: str | None = None
    scenario_revision_digest: str | None = None
    if is_revision:
        manifest = strict_loads(
            (prepared.input_snapshot_path / "run_manifest.json").read_bytes()
        )
        if not isinstance(manifest, dict):
            raise SnapshotError("revision-aware RunManifest is not a JSON object")
        traceability = manifest.get("traceability")
        revision = manifest.get("scenario_revision")
        if not isinstance(traceability, dict) or not isinstance(revision, dict):
            raise SnapshotError("revision-aware RunManifest lacks traceability")
        revision_digest = revision.get("digest")
        if not isinstance(revision_digest, str):
            raise SnapshotError("revision-aware RunManifest lacks revision digest")
        traceability_digest = canonical_digest(traceability)
        scenario_revision_digest = revision_digest
    destination = prepared.published_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / f".{destination.name}.publishing"
    if temporary.exists() or destination.exists():
        raise SnapshotError("immutable publish destination already exists")
    temporary.mkdir(mode=0o700)
    try:
        shutil.copytree(prepared.input_snapshot_path, temporary / "input", copy_function=shutil.copy2)
        os.replace(prepared.output_staging_path, temporary / "output")

        relative_paths = [f"input/{name}" for name in INPUT_FILES]
        relative_paths.extend(f"output/{name}" for name in required_outputs)
        entries: list[ArtifactEntry] = []
        for relative in sorted(relative_paths):
            path = temporary / relative
            mode = path.lstat().st_mode
            if path.is_symlink() or not stat.S_ISREG(mode):
                raise SnapshotError(f"publish tree contains a link or special file: {relative}")
            entries.append(
                ArtifactEntry(
                    path=relative,
                    status="present",
                    size_bytes=path.stat().st_size,
                    digest=_file_digest(path),
                    validation="verified",
                )
            )
        metrics = strict_loads((temporary / "output" / "metrics.json").read_bytes())
        assert isinstance(metrics, dict)
        index_type = _RevisionAwareArtifactIndex if is_revision else ArtifactIndex
        index = index_type(
            schema_version=(
                "scenarioforge.artifact-index/v3"
                if is_revision
                else (
                    "scenarioforge.artifact-index/v2"
                    if is_v2
                    else "scenarioforge.artifact-index/v1"
                )
            ),
            run_id=prepared.run_request.run_id,
            attempt_id=prepared.run_request.attempt_id,
            artifacts=tuple(entries),
            run_manifest_digest=(
                prepared.run_request.run_manifest_digest
                if is_v2
                else None
            ),
            execution_status=(
                str(metrics["execution_status"])
                if is_v2
                else None
            ),
            scenario_outcome=(
                str(metrics["scenario_outcome"])
                if is_v2
                else None
            ),
            termination_reason=(
                str(metrics["termination_reason"])
                if is_v2
                else None
            ),
            **(
                {
                    "traceability_digest": traceability_digest,
                    "scenario_revision_digest": scenario_revision_digest,
                }
                if is_revision
                else {}
            ),
        )
        result = RunResult(
            schema_version=(
                "scenarioforge.run-result/v3"
                if is_revision
                else (
                    "scenarioforge.run-result/v2"
                    if is_v2
                    else "scenarioforge.run-result/v1"
                )
            ),
            run_id=prepared.run_request.run_id,
            attempt_id=prepared.run_request.attempt_id,
            status="success",
            reason=str(metrics["termination_reason"]),
            worker_exit_code=worker_exit_code,
            run_manifest_digest=prepared.run_request.run_manifest_digest,
            compile_report_digest=prepared.bundle.report.digest,
            execution_plan_digest=prepared.run_request.execution_plan_digest,
            artifact_index_digest=index.digest,
            execution_status=(str(metrics["execution_status"]) if is_v2 else None),
            scenario_outcome=(str(metrics["scenario_outcome"]) if is_v2 else None),
            termination_reason=(str(metrics["termination_reason"]) if is_v2 else None),
            traceability_digest=traceability_digest,
            scenario_revision_digest=scenario_revision_digest,
        )
        _write_json(temporary / "artifact_index.json", index.to_dict())
        _write_json(temporary / "run_result.json", result.to_dict())
        marker = (
            {
                "schema_version": "scenarioforge.completion-marker/v2",
                "execution_status": str(metrics["execution_status"]),
                "scenario_outcome": str(metrics["scenario_outcome"]),
                "termination_reason": str(metrics["termination_reason"]),
                "run_result_digest": _file_digest(temporary / "run_result.json"),
                "artifact_index_digest": _file_digest(temporary / "artifact_index.json"),
            }
            if is_v2
            else {
                "schema_version": "scenarioforge.completion-marker/v1",
                "status": "success",
                "run_result_digest": _file_digest(temporary / "run_result.json"),
                "artifact_index_digest": _file_digest(temporary / "artifact_index.json"),
            }
        )
        _write_json(temporary / "SUCCESS", marker)
        _freeze(temporary)
        os.replace(temporary, destination)
        return result, index
    except BaseException:
        if temporary.exists():
            for path in temporary.rglob("*"):
                try:
                    path.chmod(0o700 if path.is_dir() else 0o600)
                except OSError:
                    pass
            temporary.chmod(0o700)
            shutil.rmtree(temporary, ignore_errors=True)
        raise
