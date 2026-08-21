from __future__ import annotations

from enum import Enum

from scenarioforge.runtime.contracts import RunResult


class TerminalStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"


class FailureKind(str, Enum):
    WORKER_CRASHED = "worker_crashed"
    TIMEOUT = "timeout"
    RESOURCE_LIMIT = "resource_limit_exceeded"
    ARTIFACT_VALIDATION = "artifact_validation_failed"
    OPERATOR_INTERRUPTED = "operator_interrupted"

    @property
    def terminal_status(self) -> TerminalStatus:
        if self is FailureKind.TIMEOUT:
            return TerminalStatus.TIMEOUT
        return TerminalStatus.FAILED


def create_run_result(
    *,
    schema_version: str,
    run_id: str,
    attempt_id: str,
    status: str,
    reason: str,
    worker_exit_code: int,
    run_manifest_digest: str,
    compile_report_digest: str,
    execution_plan_digest: str,
    artifact_index_digest: str,
) -> RunResult:
    """Build a public terminal result without accepting transient/cancel states."""
    try:
        terminal = TerminalStatus(status)
    except ValueError as error:
        allowed = ", ".join(item.value for item in TerminalStatus)
        raise ValueError(f"invalid public terminal status; expected one of: {allowed}") from error
    if not run_id or not attempt_id or run_id == attempt_id:
        raise ValueError("run_id and attempt_id must be distinct non-empty identities")
    return RunResult(
        schema_version=schema_version,
        run_id=run_id,
        attempt_id=attempt_id,
        status=terminal.value,
        reason=reason,
        worker_exit_code=worker_exit_code,
        run_manifest_digest=run_manifest_digest,
        compile_report_digest=compile_report_digest,
        execution_plan_digest=execution_plan_digest,
        artifact_index_digest=artifact_index_digest,
    )
