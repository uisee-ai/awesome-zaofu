from __future__ import annotations

import hashlib
import os
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scenarioforge.core import canonical_bytes, canonical_digest, strict_loads
from scenarioforge.failsafe import TerminationEvidence
from scenarioforge.runtime.contracts import (
    ArtifactEntry,
    ArtifactIndex,
    PreparedRun,
    RunResult,
)
from scenarioforge.runtime.snapshot import INPUT_FILES, validate_input_snapshot


ZERO_DIGEST = "0" * 64


class CancellationPublicationError(RuntimeError):
    pass


@dataclass(frozen=True)
class CancellationOutcome:
    published_path: Path
    run_result: RunResult
    artifact_index: ArtifactIndex
    cancellation_evidence: dict[str, Any]
    termination: TerminationEvidence


def _write_json(path: Path, value: Any) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
        0o600,
    )
    try:
        payload = canonical_bytes(value)
        if os.write(descriptor, payload) != len(payload):
            raise CancellationPublicationError(f"short write for {path.name}")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _entry(
    path: str,
    status: str,
    size_bytes: int,
    digest: str,
    validation: str,
) -> ArtifactEntry:
    return ArtifactEntry(
        path=path,
        status=status,
        size_bytes=size_bytes,
        digest=digest,
        validation=validation,
    )


def _partial_outputs(prepared: PreparedRun, destination: Path) -> list[ArtifactEntry]:
    plan = prepared.bundle.execution_plan
    if plan is None:
        raise CancellationPublicationError("cancellation requires a frozen ExecutionPlan")
    destination.mkdir(mode=0o700)
    required = tuple(str(name) for name in plan.artifact_contract["required"])
    file_limit = int(plan.artifact_contract["max_file_bytes"])
    aggregate_limit = int(plan.resource_config["artifact_limit_bytes"])
    aggregate = 0
    entries: list[ArtifactEntry] = []
    for name in sorted(required):
        source = prepared.output_staging_path / name
        relative = f"output/{name}"
        if not source.exists() and not source.is_symlink():
            entries.append(_entry(relative, "missing", 0, ZERO_DIGEST, "declared_missing"))
            continue
        mode = source.lstat().st_mode
        if source.is_symlink() or not stat.S_ISREG(mode):
            entries.append(_entry(relative, "invalid", 0, ZERO_DIGEST, "link_or_special_file"))
            continue
        payload = source.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        if len(payload) > file_limit or aggregate + len(payload) > aggregate_limit:
            entries.append(
                _entry(relative, "invalid", len(payload), digest, "size_limit_exceeded")
            )
            continue
        try:
            strict_loads(payload)
        except (TypeError, ValueError):
            entries.append(_entry(relative, "invalid", len(payload), digest, "invalid_json"))
            continue
        shutil.copy2(source, destination / name)
        aggregate += len(payload)
        entries.append(_entry(relative, "present", len(payload), digest, "verified_partial"))
    return entries


def _freeze(root: Path) -> None:
    for path in root.rglob("*"):
        path.chmod(0o555 if path.is_dir() else 0o444)
    root.chmod(0o555)


def _remove_tree(root: Path) -> None:
    if not root.exists():
        return
    for path in root.rglob("*"):
        if path.is_symlink():
            continue
        try:
            path.chmod(0o700 if path.is_dir() else 0o600)
        except OSError:
            pass
    try:
        root.chmod(0o700)
    except OSError:
        pass
    shutil.rmtree(root, ignore_errors=True)


def publish_cancellation(
    prepared: PreparedRun,
    *,
    command_id: str,
    operation: str,
    reason: str,
    worker_exit_code: int,
    termination: TerminationEvidence,
) -> CancellationOutcome:
    """Atomically publish a started user cancellation as RunResult v4."""
    if not termination.complete or termination.remaining_pids:
        raise CancellationPublicationError(
            "cannot publish cancellation while the Worker tree is live"
        )
    snapshot_digest = validate_input_snapshot(prepared.input_snapshot_path)
    if snapshot_digest != prepared.run_request.input_snapshot_digest:
        raise CancellationPublicationError("frozen InputSnapshot changed before cancellation")
    destination = prepared.published_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / f".{destination.name}.publishing"
    if temporary.exists() or destination.exists():
        raise CancellationPublicationError("immutable publish destination already exists")
    temporary.mkdir(mode=0o700)
    try:
        shutil.copytree(
            prepared.input_snapshot_path,
            temporary / "input",
            copy_function=shutil.copy2,
        )
        output_entries = _partial_outputs(prepared, temporary / "output")
        command = {
            "schema_version": "scenarioforge.control-command/v1",
            "command_id": command_id,
            "operation": operation,
            "reason": reason,
        }
        evidence = {
            "schema_version": "scenarioforge.cancellation-evidence/v1",
            "run_id": prepared.run_request.run_id,
            "attempt_id": prepared.run_request.attempt_id,
            "command": command,
            "termination": termination.to_dict(),
            "statistics_eligible": False,
            "frozen_evidence": {
                "run_manifest": {
                    "ref": "input/run_manifest.json",
                    "digest": prepared.run_request.run_manifest_digest,
                },
                "compile_report": {
                    "ref": "input/compile_report.json",
                    "digest": prepared.bundle.report.digest,
                },
                "execution_plan": {
                    "ref": "input/execution_plan.json",
                    "digest": prepared.run_request.execution_plan_digest,
                },
            },
            "partial_artifacts": [entry.to_dict() for entry in output_entries],
        }
        _write_json(temporary / "cancellation_evidence.json", evidence)
        entries = [
            _entry(
                f"input/{name}",
                "present",
                (temporary / "input" / name).stat().st_size,
                _digest(temporary / "input" / name),
                "verified",
            )
            for name in INPUT_FILES
        ]
        entries.extend(output_entries)
        entries.append(
            _entry(
                "cancellation_evidence.json",
                "present",
                (temporary / "cancellation_evidence.json").stat().st_size,
                _digest(temporary / "cancellation_evidence.json"),
                "verified",
            )
        )
        index = ArtifactIndex(
            schema_version="scenarioforge.artifact-index/v1",
            run_id=prepared.run_request.run_id,
            attempt_id=prepared.run_request.attempt_id,
            artifacts=tuple(sorted(entries, key=lambda item: item.path)),
        )
        manifest = strict_loads((temporary / "input" / "run_manifest.json").read_bytes())
        if not isinstance(manifest, dict):
            raise CancellationPublicationError("RunManifest is invalid")
        trace = manifest.get("traceability")
        traceability_digest = canonical_digest(
            trace
            if isinstance(trace, dict)
            else {"run_manifest_digest": prepared.run_request.run_manifest_digest}
        )
        revision = manifest.get("scenario_revision")
        scenario_revision_digest = (
            revision.get("digest")
            if isinstance(revision, dict) and isinstance(revision.get("digest"), str)
            else manifest.get("scenario_instance_digest")
        )
        if not isinstance(scenario_revision_digest, str):
            scenario_revision_digest = prepared.run_request.run_manifest_digest
        result = RunResult(
            schema_version="scenarioforge.run-result/v4",
            run_id=prepared.run_request.run_id,
            attempt_id=prepared.run_request.attempt_id,
            status="cancelled",
            reason=reason,
            worker_exit_code=worker_exit_code,
            run_manifest_digest=prepared.run_request.run_manifest_digest,
            compile_report_digest=prepared.bundle.report.digest,
            execution_plan_digest=prepared.run_request.execution_plan_digest,
            artifact_index_digest=index.digest,
            execution_status="cancelled",
            scenario_outcome="not_applicable",
            termination_reason=reason,
            traceability_digest=traceability_digest,
            scenario_revision_digest=scenario_revision_digest,
            control_command=command,
            process_tree_cleanup=termination.to_dict(),
            statistics_eligible=False,
        )
        _write_json(temporary / "artifact_index.json", index.to_dict())
        _write_json(temporary / "run_result.json", result.to_dict())
        marker = {
            "schema_version": "scenarioforge.completion-marker/v3",
            "status": "cancelled",
            "execution_status": "cancelled",
            "scenario_outcome": "not_applicable",
            "termination_reason": reason,
            "run_result_digest": _digest(temporary / "run_result.json"),
            "artifact_index_digest": _digest(temporary / "artifact_index.json"),
            "cancellation_evidence_digest": _digest(
                temporary / "cancellation_evidence.json"
            ),
        }
        _write_json(temporary / "CANCELLED", marker)
        _freeze(temporary)
        os.replace(temporary, destination)
        _remove_tree(prepared.output_staging_path)
        return CancellationOutcome(
            published_path=destination,
            run_result=result,
            artifact_index=index,
            cancellation_evidence=evidence,
            termination=termination,
        )
    except BaseException:
        _remove_tree(temporary)
        raise
