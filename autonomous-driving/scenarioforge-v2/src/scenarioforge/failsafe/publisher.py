from __future__ import annotations

import hashlib
import os
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scenarioforge.core import canonical_bytes, strict_loads
from scenarioforge.runtime.contracts import ArtifactEntry, ArtifactIndex, PreparedRun, RunResult
from scenarioforge.runtime.snapshot import INPUT_FILES, validate_input_snapshot
from scenarioforge.security import redact_log

from .contracts import FailureKind, create_run_result
from .process_tree import TerminationEvidence


ZERO_DIGEST = "0" * 64


class FailurePublicationError(RuntimeError):
    pass


@dataclass(frozen=True)
class FailureOutcome:
    published_path: Path
    run_result: RunResult
    artifact_index: ArtifactIndex
    failure_evidence: dict[str, Any]
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
            raise FailurePublicationError(f"short write for {path.name}")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _digest_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _file_digest(path: Path) -> str:
    return _digest_bytes(path.read_bytes())


def _entry(path: str, status: str, size: int, digest: str, validation: str) -> ArtifactEntry:
    return ArtifactEntry(
        path=path,
        status=status,
        size_bytes=size,
        digest=digest,
        validation=validation,
    )


def _inspect_partial_outputs(prepared: PreparedRun, destination: Path) -> list[ArtifactEntry]:
    plan = prepared.bundle.execution_plan
    if plan is None:
        raise FailurePublicationError("failure publication requires a frozen ExecutionPlan")
    required = tuple(str(name) for name in plan.artifact_contract["required"])
    if any(Path(name).name != name or name in {"", ".", ".."} for name in required):
        raise FailurePublicationError("artifact contract contains an unsafe path")
    maximum = int(plan.artifact_contract["max_file_bytes"])
    aggregate_limit = int(plan.resource_config["artifact_limit_bytes"])
    aggregate_size = 0
    destination.mkdir(mode=0o700)
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
        size = source.stat().st_size
        if size > maximum or aggregate_size + size > aggregate_limit:
            entries.append(_entry(relative, "invalid", size, ZERO_DIGEST, "size_limit_exceeded"))
            continue
        payload = source.read_bytes()
        digest = _digest_bytes(payload)
        try:
            strict_loads(payload)
        except (TypeError, ValueError):
            entries.append(_entry(relative, "invalid", size, digest, "invalid_json"))
            continue
        shutil.copy2(source, destination / name)
        aggregate_size += size
        entries.append(_entry(relative, "present", size, digest, "verified_partial"))
    return entries


def _freeze(root: Path) -> None:
    for path in root.rglob("*"):
        if path.is_file():
            path.chmod(0o444)
    for path in sorted((item for item in root.rglob("*") if item.is_dir()), reverse=True):
        path.chmod(0o555)
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


def publish_failure(
    prepared: PreparedRun,
    *,
    kind: FailureKind,
    stage: str,
    worker_exit_code: int,
    termination: TerminationEvidence,
    stdout: str = "",
    stderr: str = "",
    sensitive_values: tuple[str, ...] = (),
    redacted_paths: tuple[Path, ...] = (),
) -> FailureOutcome:
    """Atomically publish one immutable failed/timeout terminal and its evidence."""
    if not termination.complete or termination.remaining_pids:
        raise FailurePublicationError("cannot publish while the Worker process tree is still live")
    if termination.trigger != kind.value:
        raise FailurePublicationError("termination trigger does not match the failure kind")
    snapshot_digest = validate_input_snapshot(prepared.input_snapshot_path)
    if snapshot_digest != prepared.run_request.input_snapshot_digest:
        raise FailurePublicationError("frozen InputSnapshot digest changed before publication")
    plan = prepared.bundle.execution_plan
    if plan is None:
        raise FailurePublicationError("failure publication requires an ExecutionPlan")

    destination = prepared.published_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / f".{destination.name}.publishing"
    if temporary.exists() or destination.exists():
        raise FailurePublicationError("immutable publish destination already exists")
    temporary.mkdir(mode=0o700)
    try:
        shutil.copytree(prepared.input_snapshot_path, temporary / "input", copy_function=shutil.copy2)
        output_entries = _inspect_partial_outputs(prepared, temporary / "output")
        log_limit = int(plan.resource_config["log_limit_bytes"])
        safe_stdout = redact_log(
            stdout,
            sensitive_values=tuple(sensitive_values),
            redacted_paths=tuple(redacted_paths),
            limit_bytes=log_limit,
        )
        safe_stderr = redact_log(
            stderr,
            sensitive_values=tuple(sensitive_values),
            redacted_paths=tuple(redacted_paths),
            limit_bytes=log_limit,
        )
        evidence: dict[str, Any] = {
            "schema_version": "scenarioforge.failure-evidence/v1",
            "run_id": prepared.run_request.run_id,
            "attempt_id": prepared.run_request.attempt_id,
            "failure_kind": kind.value,
            "failure_stage": stage,
            "reason": kind.value,
            "worker_exit_code": worker_exit_code,
            "termination": termination.to_dict(),
            "logs": {
                "stdout": safe_stdout.text,
                "stderr": safe_stderr.text,
                "truncated": safe_stdout.truncated or safe_stderr.truncated,
            },
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
            "missing_artifacts": [
                entry.path for entry in output_entries if entry.status == "missing"
            ],
        }
        _write_json(temporary / "failure_evidence.json", evidence)

        entries = [
            _entry(
                f"input/{name}",
                "present",
                (temporary / "input" / name).stat().st_size,
                _file_digest(temporary / "input" / name),
                "verified",
            )
            for name in INPUT_FILES
        ]
        entries.extend(output_entries)
        entries.append(
            _entry(
                "failure_evidence.json",
                "present",
                (temporary / "failure_evidence.json").stat().st_size,
                _file_digest(temporary / "failure_evidence.json"),
                "verified",
            )
        )
        index = ArtifactIndex(
            schema_version="scenarioforge.artifact-index/v1",
            run_id=prepared.run_request.run_id,
            attempt_id=prepared.run_request.attempt_id,
            artifacts=tuple(sorted(entries, key=lambda item: item.path)),
        )
        result = create_run_result(
            schema_version="scenarioforge.run-result/v1",
            run_id=prepared.run_request.run_id,
            attempt_id=prepared.run_request.attempt_id,
            status=kind.terminal_status.value,
            reason=kind.value,
            worker_exit_code=worker_exit_code,
            run_manifest_digest=prepared.run_request.run_manifest_digest,
            compile_report_digest=prepared.bundle.report.digest,
            execution_plan_digest=prepared.run_request.execution_plan_digest,
            artifact_index_digest=index.digest,
        )
        _write_json(temporary / "artifact_index.json", index.to_dict())
        _write_json(temporary / "run_result.json", result.to_dict())
        marker = {
            "schema_version": "scenarioforge.completion-marker/v1",
            "status": result.status,
            "run_result_digest": _file_digest(temporary / "run_result.json"),
            "artifact_index_digest": _file_digest(temporary / "artifact_index.json"),
            "failure_evidence_digest": _file_digest(temporary / "failure_evidence.json"),
        }
        _write_json(temporary / result.status.upper(), marker)
        _freeze(temporary)
        os.replace(temporary, destination)
        _remove_tree(prepared.output_staging_path)
        return FailureOutcome(
            published_path=destination,
            run_result=result,
            artifact_index=index,
            failure_evidence=evidence,
            termination=termination,
        )
    except BaseException:
        _remove_tree(temporary)
        raise
