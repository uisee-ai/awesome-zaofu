from __future__ import annotations

import signal
import subprocess
from pathlib import Path

from scenarioforge.runtime.contracts import PreparedRun

from .contracts import FailureKind
from .process_tree import terminate_process_tree
from .publisher import FailureOutcome, publish_failure


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


class FailureController:
    """Close a failed single-run Worker tree before publishing its terminal evidence."""

    def __init__(
        self,
        *,
        sensitive_values: tuple[str, ...] = (),
        redacted_paths: tuple[Path, ...] = (),
    ) -> None:
        self.sensitive_values = sensitive_values
        self.redacted_paths = redacted_paths

    def close(
        self,
        prepared: PreparedRun,
        *,
        process: subprocess.Popen[object],
        kind: FailureKind,
        stage: str,
        worker_exit_code: int | None = None,
        stdout: str | None = None,
        stderr: str | None = None,
    ) -> FailureOutcome:
        termination = terminate_process_tree(process, trigger=kind.value)
        if stdout is None or stderr is None:
            captured_stdout, captured_stderr = process.communicate()
            if stdout is None:
                stdout = _text(captured_stdout)
            if stderr is None:
                stderr = _text(captured_stderr)
        exit_code = worker_exit_code
        if exit_code is None:
            exit_code = process.returncode if process.returncode is not None else -signal.SIGKILL
        return publish_failure(
            prepared,
            kind=kind,
            stage=stage,
            worker_exit_code=exit_code,
            termination=termination,
            stdout=stdout,
            stderr=stderr,
            sensitive_values=self.sensitive_values,
            redacted_paths=self.redacted_paths,
        )
