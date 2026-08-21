from __future__ import annotations

import os
import hashlib
import subprocess
import sys
import signal
import tempfile
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from scenarioforge.core.models import CompileBundle
from scenarioforge.security import (
    ResourcePolicy,
    SecurityViolation,
    enforce_resource_policy,
    observe_process_group,
)
from scenarioforge.security.resources import (
    RELEASE_RESOURCE_LIMITS,
    DelegatedCgroupV2,
)

from .artifact_publish import publish_success
from .contracts import RunOutcome
from .snapshot import SnapshotError, prepare_run

if TYPE_CHECKING:
    from scenarioforge.failsafe import FailureController, FailureOutcome


_INTERACTIVE_CONTROL_READY_WINDOW_SECONDS = 3.0


class RunSupervisor:
    """Trusted coordinator for exactly one synchronous Worker process."""

    def __init__(
        self,
        *,
        workspace: Path,
        project_root: Path,
        failure_controller: FailureController | None = None,
        require_delegated_cgroup: bool = False,
        cgroup_root: Path | None = None,
    ) -> None:
        self.workspace = Path(workspace)
        self.project_root = Path(project_root)
        if failure_controller is None:
            from scenarioforge.failsafe import FailureController

            failure_controller = FailureController(
                redacted_paths=(self.workspace, self.project_root),
            )
        self.failure_controller = failure_controller
        self.require_delegated_cgroup = require_delegated_cgroup
        self.cgroup_root = None if cgroup_root is None else Path(cgroup_root)
        if require_delegated_cgroup and self.cgroup_root is None:
            raise ValueError("formal Release Workers require a delegated cgroup root")
        self._slot = threading.Lock()
        self._state_lock = threading.Lock()
        self._running = False
        self._shutdown_requested = threading.Event()
        self._active_process: subprocess.Popen[str] | None = None
        self._paused = False
        self._cancel_requested: tuple[str, str, str] | None = None

    def run(
        self,
        bundle: CompileBundle,
        *,
        run_id: str,
        attempt_id: str,
        timeout_seconds: float,
        process_started: Callable[[int], None] | None = None,
    ) -> RunOutcome | FailureOutcome:
        from scenarioforge.failsafe import FailureKind

        if timeout_seconds <= 0:
            raise SnapshotError("timeout_seconds must be positive")
        if not self._slot.acquire(blocking=False):
            raise SnapshotError("single-run supervisor slot is occupied")
        with self._state_lock:
            self._running = True
            self._shutdown_requested.clear()
        try:
            prepared = prepare_run(
                bundle,
                workspace=self.workspace,
                project_root=self.project_root,
                run_id=run_id,
                attempt_id=attempt_id,
            )
            command = [
                sys.executable,
                "-I",
                "-c",
                (
                    "import runpy,sys;"
                    "sys.path.insert(0,sys.argv.pop(1));"
                    "runpy.run_module('scenarioforge.runtime.worker_entry',run_name='__main__')"
                ),
                str(self.project_root / "src"),
                "--input-snapshot",
                str(prepared.input_snapshot_path),
                "--output-staging",
                str(prepared.output_staging_path),
            ]
            environment = {
                "PATH": os.defpath,
                "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8",
            }
            cgroup = None
            if self.require_delegated_cgroup:
                assert self.cgroup_root is not None
                identity = "sf-" + hashlib.sha256(
                    f"{run_id}\0{attempt_id}".encode("utf-8")
                ).hexdigest()[:32]
                cgroup = DelegatedCgroupV2(self.cgroup_root).create(
                    identity,
                    RELEASE_RESOURCE_LIMITS,
                )
            plan = prepared.bundle.execution_plan
            if plan is None:
                raise SnapshotError("Worker requires a frozen ExecutionPlan")
            resource_policy = ResourcePolicy.from_mapping(
                {
                    field: plan.resource_config[field]
                    for field in (
                        "wall_clock_timeout_s",
                        "memory_limit_mb",
                        "pid_limit",
                        "log_limit_bytes",
                        "artifact_limit_bytes",
                    )
                }
            )
            with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as stdout_file:
                with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as stderr_file:
                    process = subprocess.Popen(
                        command,
                        cwd=self.project_root,
                        env=environment,
                        stdin=subprocess.DEVNULL,
                        stdout=stdout_file,
                        stderr=stderr_file,
                        text=True,
                        start_new_session=True,
                    )
                    started_at = time.monotonic()
                    deadline = started_at + min(
                        timeout_seconds,
                        resource_policy.wall_clock_timeout_s,
                    )
                    if cgroup is not None:
                        try:
                            cgroup.attach(process.pid)
                        except SecurityViolation:
                            return self.failure_controller.close(
                                prepared,
                                process=process,
                                kind=FailureKind.RESOURCE_LIMIT,
                                stage="cgroup_v2_attachment",
                                stdout=self._captured(stdout_file),
                                stderr=self._captured(stderr_file),
                            )
                    startup_held = False
                    if process_started is not None:
                        try:
                            os.killpg(process.pid, signal.SIGSTOP)
                            startup_held = True
                        except ProcessLookupError:
                            startup_held = False
                    with self._state_lock:
                        self._active_process = process
                    if process_started is not None:
                        process_started(process.pid)
                    if startup_held:
                        # A persistent Experiment exposes the process-group identity
                        # before releasing a short Worker.  Keep it controllable long
                        # enough for the actual browser/API client to observe that
                        # identity and issue Pause or Stop.
                        handshake_deadline = min(
                            deadline,
                            time.monotonic()
                            + _INTERACTIVE_CONTROL_READY_WINDOW_SECONDS,
                        )
                        while time.monotonic() < handshake_deadline:
                            with self._state_lock:
                                if self._paused or self._cancel_requested is not None:
                                    break
                            time.sleep(0.01)
                        with self._state_lock:
                            preserve_pause = self._paused
                        if not preserve_pause:
                            try:
                                os.killpg(process.pid, signal.SIGCONT)
                            except ProcessLookupError:
                                pass
                    while True:
                        with self._state_lock:
                            cancellation = self._cancel_requested
                            paused = self._paused
                        if cancellation is not None:
                            if paused:
                                try:
                                    os.killpg(process.pid, signal.SIGCONT)
                                except ProcessLookupError:
                                    pass
                            from scenarioforge.failsafe import terminate_process_tree
                            from scenarioforge.orchestration.publication import (
                                publish_cancellation,
                            )

                            termination = terminate_process_tree(
                                process,
                                trigger="user_cancelled",
                            )
                            return publish_cancellation(
                                prepared,
                                command_id=cancellation[0],
                                operation=cancellation[1],
                                reason=cancellation[2],
                                worker_exit_code=(
                                    process.returncode
                                    if process.returncode is not None
                                    else -signal.SIGKILL
                                ),
                                termination=termination,
                            )
                        if self._shutdown_requested.is_set():
                            return self.failure_controller.close(
                                prepared,
                                process=process,
                                kind=FailureKind.OPERATOR_INTERRUPTED,
                                stage="operator_interruption",
                                stdout=self._captured(stdout_file),
                                stderr=self._captured(stderr_file),
                            )
                        if process.poll() is not None:
                            break
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            return self.failure_controller.close(
                                prepared,
                                process=process,
                                kind=FailureKind.TIMEOUT,
                                stage="worker_execution",
                                stdout=self._captured(stdout_file),
                                stderr=self._captured(stderr_file),
                            )
                        log_bytes = os.fstat(stdout_file.fileno()).st_size + os.fstat(
                            stderr_file.fileno()
                        ).st_size
                        try:
                            observation = observe_process_group(
                                process.pid,
                                started_at=started_at,
                                log_bytes=log_bytes,
                                artifact_root=prepared.output_staging_path,
                            )
                            enforce_resource_policy(resource_policy, observation)
                        except SecurityViolation:
                            return self.failure_controller.close(
                                prepared,
                                process=process,
                                kind=FailureKind.RESOURCE_LIMIT,
                                stage="resource_enforcement",
                                stdout=self._captured(stdout_file),
                                stderr=self._captured(stderr_file),
                            )
                        time.sleep(min(0.02, remaining))

                    stdout = self._captured(stdout_file)
                    stderr = self._captured(stderr_file)
                    if process.returncode != 0:
                        return self.failure_controller.close(
                            prepared,
                            process=process,
                            kind=FailureKind.WORKER_CRASHED,
                            stage="worker_execution",
                            worker_exit_code=process.returncode,
                            stdout=stdout,
                            stderr=stderr,
                        )

                    result, index = publish_success(
                        prepared, worker_exit_code=process.returncode
                    )
                    return RunOutcome(
                        bundle=bundle,
                        input_snapshot_path=prepared.input_snapshot_path,
                        output_staging_path=prepared.output_staging_path,
                        published_path=prepared.published_path,
                        run_request=prepared.run_request,
                        run_result=result,
                        artifact_index=index,
                        worker_pid=process.pid,
                        worker_exit_code=process.returncode,
                        worker_exited=process.poll() is not None,
                    )
        finally:
            with self._state_lock:
                self._running = False
                self._shutdown_requested.clear()
                self._active_process = None
                self._paused = False
                self._cancel_requested = None
            self._slot.release()

    @staticmethod
    def _captured(stream: object) -> str:
        stream.flush()
        stream.seek(0)
        return str(stream.read())

    @property
    def active_process_group_id(self) -> int | None:
        with self._state_lock:
            if self._active_process is None or self._active_process.poll() is not None:
                return None
            return self._active_process.pid

    def pause_active(self) -> bool:
        with self._state_lock:
            process = self._active_process
            if process is None or process.poll() is not None:
                return False
            if self._paused:
                return True
            try:
                os.killpg(process.pid, signal.SIGSTOP)
            except ProcessLookupError:
                return False
            self._paused = True
            return True

    def resume_active(self) -> bool:
        with self._state_lock:
            process = self._active_process
            if process is None or process.poll() is not None:
                return False
            if not self._paused:
                return True
            try:
                os.killpg(process.pid, signal.SIGCONT)
            except ProcessLookupError:
                return False
            self._paused = False
            return True

    def step_active(self, *, quantum_seconds: float = 0.05) -> bool:
        if quantum_seconds <= 0 or quantum_seconds > 1:
            raise ValueError("step quantum must be in (0, 1] seconds")
        with self._state_lock:
            process = self._active_process
            if process is None or process.poll() is not None or not self._paused:
                return False
            try:
                os.killpg(process.pid, signal.SIGCONT)
            except ProcessLookupError:
                return False
        time.sleep(quantum_seconds)
        with self._state_lock:
            if process.poll() is not None or self._cancel_requested is not None:
                self._paused = False
                return False
            try:
                os.killpg(process.pid, signal.SIGSTOP)
            except ProcessLookupError:
                self._paused = False
                return False
            self._paused = True
            return True

    def cancel_active(
        self,
        *,
        command_id: str,
        reason: str,
        operation: str = "stop",
    ) -> bool:
        with self._state_lock:
            process = self._active_process
            if process is None or process.poll() is not None:
                return False
            request = (command_id, operation, reason)
            if self._cancel_requested is not None:
                return self._cancel_requested == request
            self._cancel_requested = request
            return True

    def interrupt_active_for_shutdown(self) -> bool:
        """Signal the run-owning thread; Web clients never receive this capability."""
        with self._state_lock:
            if not self._running:
                return False
            self._shutdown_requested.set()
            return True
