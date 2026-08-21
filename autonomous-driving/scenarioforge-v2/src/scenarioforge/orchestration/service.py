from __future__ import annotations

import os
import re
import secrets
import signal
import threading
import time
from dataclasses import replace
from types import MappingProxyType
from typing import Callable, Mapping, Protocol

from scenarioforge.core.canonical import JSONValue, freeze_json, thaw_json
from scenarioforge.failsafe import live_process_group_members

from .contracts import (
    JOB_STATES,
    ExperimentDefinition,
    ExperimentJob,
    ExperimentManifest,
    ExperimentState,
    JobState,
)
from .store import ExperimentStore


_SAFE_COMMAND_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_OPERATIONS = frozenset({"start", "pause", "step", "resume", "stop", "reset"})
_TERMINAL_JOBS = frozenset({"completed", "failed", "timeout", "cancelled"})


class ExperimentServiceError(RuntimeError):
    pass


class InvalidControlTransition(ExperimentServiceError):
    pass


class CommandConflictError(ExperimentServiceError):
    pass


class JobRunner(Protocol):
    def run(self, *, attempt_id: str, timeout_seconds: int) -> object: ...

    def pause(self) -> bool: ...

    def resume(self) -> bool: ...

    def step(self) -> bool: ...

    def cancel(self, *, command_id: str, reason: str) -> bool: ...


RunnerFactory = Callable[[ExperimentJob, ExperimentManifest], JobRunner]
OrphanCleanup = Callable[[int], Mapping[str, object]]


def _default_orphan_cleanup(process_group_id: int) -> Mapping[str, object]:
    observed = live_process_group_members(process_group_id)
    signals_sent: list[str] = []
    if observed:
        try:
            os.killpg(process_group_id, signal.SIGTERM)
            signals_sent.append("SIGTERM")
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + 0.5
    remaining = live_process_group_members(process_group_id)
    while remaining and time.monotonic() < deadline:
        time.sleep(0.01)
        remaining = live_process_group_members(process_group_id)
    if remaining:
        try:
            os.killpg(process_group_id, signal.SIGKILL)
            signals_sent.append("SIGKILL")
        except ProcessLookupError:
            pass
        deadline = time.monotonic() + 1.0
        while remaining and time.monotonic() < deadline:
            time.sleep(0.01)
            remaining = live_process_group_members(process_group_id)
    return {
        "schema_version": "scenarioforge.process-tree-termination/v1",
        "process_group_id": process_group_id,
        "observed_pids": list(observed),
        "signals_sent": signals_sent,
        "remaining_pids": list(remaining),
        "complete": not remaining,
    }


def _attempts_with_terminal(
    job: JobState,
    *,
    attempt_id: str,
    terminal: str,
    extra: Mapping[str, object] | None = None,
) -> tuple[Mapping[str, JSONValue], ...]:
    attempts = [dict(thaw_json(item)) for item in job.attempts]
    replacement: dict[str, object] = {"attempt_id": attempt_id, "state": terminal}
    if extra:
        replacement.update(extra)
    if attempts and attempts[-1].get("attempt_id") == attempt_id:
        attempts[-1] = {**attempts[-1], **replacement}
    else:
        attempts.append(replacement)
    return tuple(freeze_json(item) for item in attempts)


class ExperimentService:
    """Persistent two-slot scheduler with idempotent interactive controls."""

    def __init__(
        self,
        *,
        store: ExperimentStore,
        runner_factory: RunnerFactory,
        orphan_cleanup: OrphanCleanup | None = None,
        recover: bool = True,
    ) -> None:
        self.store = store
        self.runner_factory = runner_factory
        self.orphan_cleanup = orphan_cleanup or _default_orphan_cleanup
        self._lock = threading.RLock()
        self._active_runners: dict[tuple[str, str], JobRunner] = {}
        self._threads: dict[tuple[str, str], threading.Thread] = {}
        if recover:
            self.recover()

    def submit(
        self,
        definition: ExperimentDefinition,
        *,
        idempotency_key: str,
    ) -> dict[str, object]:
        manifest = self.store.submit(definition, idempotency_key=idempotency_key)
        return self.get(manifest.experiment_id)

    def get(self, experiment_id: str) -> dict[str, object]:
        with self._lock:
            manifest = self.store.load_manifest(experiment_id)
            state = self.store.load_state(experiment_id)
            states = {job.job_id: job for job in state.jobs}
            jobs: list[dict[str, object]] = []
            for job in manifest.jobs:
                scheduler = states[job.job_id]
                jobs.append(
                    {
                        **job.to_dict(),
                        "state": scheduler.state,
                        "attempt_id": scheduler.attempt_id,
                        "attempts": thaw_json(scheduler.attempts),
                    }
                )
            return {
                "schema_version": "scenarioforge.experiment/v1",
                "experiment_id": manifest.experiment_id,
                "manifest_digest": manifest.digest,
                "definition_digest": manifest.definition_digest,
                "matrix": thaw_json(manifest.matrix),
                "cardinality": manifest.cardinality,
                "inputs": thaw_json(manifest.inputs),
                "limits": manifest.limits.to_dict(),
                "state": state.state,
                "sequence": state.sequence,
                "jobs": jobs,
            }

    def list(self) -> dict[str, object]:
        return {
            "schema_version": "scenarioforge.experiment-list/v1",
            "experiments": [self.get(item) for item in self.store.list_experiment_ids()],
        }

    def control(
        self,
        experiment_id: str,
        operation: str,
        *,
        command_id: str,
    ) -> dict[str, object]:
        if operation not in _OPERATIONS:
            raise InvalidControlTransition("unknown Experiment control operation")
        if not isinstance(command_id, str) or _SAFE_COMMAND_ID.fullmatch(command_id) is None:
            raise ExperimentServiceError("command_id is invalid")
        if operation == "reset":
            return self._reset(experiment_id, command_id)

        schedule = False
        with self._lock:
            manifest = self.store.load_manifest(experiment_id)
            state = self.store.load_state(experiment_id)
            prior = thaw_json(state.commands).get(command_id)
            if prior is not None:
                if prior.get("operation") != operation:
                    raise CommandConflictError("command_id is bound to another operation")
                return self.get(experiment_id)

            if operation == "start":
                if state.state == "queued":
                    state = state.with_update(state="running", sequence=state.sequence + 1)
                    schedule = True
                elif state.state != "running":
                    raise InvalidControlTransition("start requires a queued Experiment")
            elif operation == "pause":
                if state.state == "running":
                    state = self._pause_running(state)
                elif state.state != "paused":
                    raise InvalidControlTransition("pause requires a running Experiment")
            elif operation == "step":
                if manifest.cardinality != 1:
                    raise InvalidControlTransition("step is limited to a single-job Experiment")
                if state.state != "paused":
                    raise InvalidControlTransition("step requires a paused Experiment")
                runner = self._active_runners.get((experiment_id, state.jobs[0].job_id))
                if runner is None or not runner.step():
                    raise InvalidControlTransition("paused Worker cannot step")
                state = state.with_update(sequence=state.sequence + 1)
            elif operation == "resume":
                if state.state == "paused":
                    state = self._resume_paused(state)
                    schedule = True
                elif state.state != "running":
                    raise InvalidControlTransition("resume requires a paused Experiment")
            elif operation == "stop":
                if state.state in {"queued", "running", "paused"}:
                    state = self._stop(state, command_id=command_id)
                elif state.state != "cancelled":
                    raise InvalidControlTransition("stop requires a non-terminal Experiment")

            state = self._record_command(state, command_id, operation)
            self.store.save_state(state)

        if schedule:
            self._schedule(experiment_id)
        return self.get(experiment_id)

    def _record_command(
        self,
        state: ExperimentState,
        command_id: str,
        operation: str,
    ) -> ExperimentState:
        commands = dict(thaw_json(state.commands))
        commands[command_id] = {
            "operation": operation,
            "sequence": state.sequence,
        }
        return state.with_update(commands=freeze_json(commands))

    def _pause_running(self, state: ExperimentState) -> ExperimentState:
        jobs: list[JobState] = []
        for job in state.jobs:
            if job.state == "running":
                runner = self._active_runners.get((state.experiment_id, job.job_id))
                if runner is None or not runner.pause():
                    raise InvalidControlTransition("running Worker cannot pause")
                jobs.append(replace(job, state="paused"))
            else:
                jobs.append(job)
        return state.with_update(
            state="paused",
            sequence=state.sequence + 1,
            jobs=tuple(jobs),
        )

    def _resume_paused(self, state: ExperimentState) -> ExperimentState:
        jobs: list[JobState] = []
        for job in state.jobs:
            if job.state == "paused":
                runner = self._active_runners.get((state.experiment_id, job.job_id))
                if runner is None or not runner.resume():
                    raise InvalidControlTransition("paused Worker cannot resume")
                jobs.append(replace(job, state="running"))
            else:
                jobs.append(job)
        return state.with_update(
            state="running",
            sequence=state.sequence + 1,
            jobs=tuple(jobs),
        )

    def _stop(self, state: ExperimentState, *, command_id: str) -> ExperimentState:
        active_runners = {
            job.job_id: self._active_runners.get(
                (state.experiment_id, job.job_id)
            )
            for job in state.jobs
            if job.state in {"running", "paused"}
        }
        if any(runner is None for runner in active_runners.values()):
            raise InvalidControlTransition("running Worker cannot stop")
        jobs: list[JobState] = []
        for job in state.jobs:
            if job.state in {"running", "paused"}:
                runner = active_runners[job.job_id]
                assert runner is not None
                if not runner.cancel(
                    command_id=command_id,
                    reason="user_cancelled",
                ):
                    raise InvalidControlTransition("running Worker cannot stop")
                if job.attempt_id is None:
                    raise ExperimentServiceError("active job has no attempt identity")
                jobs.append(
                    replace(
                        job,
                        state="cancelled",
                        attempts=_attempts_with_terminal(
                            job,
                            attempt_id=job.attempt_id,
                            terminal="cancelled",
                            extra={
                                "command_id": command_id,
                                "reason": "user_cancelled",
                            },
                        ),
                    )
                )
            elif job.state == "queued":
                jobs.append(replace(job, state="cancelled"))
            else:
                jobs.append(job)
        return state.with_update(
            state="cancelled",
            sequence=state.sequence + 1,
            jobs=tuple(jobs),
        )

    def _reset(self, experiment_id: str, command_id: str) -> dict[str, object]:
        threads: list[threading.Thread] = []
        with self._lock:
            state = self.store.load_state(experiment_id)
            prior = thaw_json(state.commands).get(command_id)
            if prior is not None:
                if prior.get("operation") != "reset":
                    raise CommandConflictError("command_id is bound to another operation")
                return self.get(experiment_id)
            jobs: list[JobState] = []
            for job in state.jobs:
                if job.state in {"running", "paused"} and job.attempt_id is not None:
                    runner = self._active_runners.get((experiment_id, job.job_id))
                    if runner is not None:
                        runner.cancel(command_id=command_id, reason="reset")
                    thread = self._threads.get((experiment_id, job.job_id))
                    if thread is not None:
                        threads.append(thread)
                    attempts = _attempts_with_terminal(
                        job,
                        attempt_id=job.attempt_id,
                        terminal="cancelled",
                        extra={"command_id": command_id, "reason": "reset"},
                    )
                else:
                    attempts = job.attempts
                jobs.append(
                    replace(
                        job,
                        state="queued",
                        attempt_id=None,
                        attempts=attempts,
                    )
                )
            state = state.with_update(
                state="running",
                sequence=state.sequence + 1,
                jobs=tuple(jobs),
            )
            state = self._record_command(state, command_id, "reset")
            self.store.save_state(state)

        for thread in threads:
            thread.join(timeout=5)
            if thread.is_alive():
                raise ExperimentServiceError("reset could not close the prior attempt")
        self._schedule(experiment_id)
        return self.get(experiment_id)

    def _schedule(self, experiment_id: str) -> None:
        to_start: list[threading.Thread] = []
        with self._lock:
            manifest = self.store.load_manifest(experiment_id)
            state = self.store.load_state(experiment_id)
            if state.state != "running":
                return
            jobs = list(state.jobs)
            active = sum(job.state in {"running", "paused"} for job in jobs)
            available = max(0, manifest.limits.concurrency - active)
            manifest_jobs = {job.job_id: job for job in manifest.jobs}
            for index, job in enumerate(jobs):
                if available <= 0:
                    break
                if job.state != "queued":
                    continue
                attempt_id = f"attempt-{secrets.token_hex(12)}"
                attempts = tuple(job.attempts) + (
                    freeze_json({"attempt_id": attempt_id, "state": "running"}),
                )
                jobs[index] = replace(
                    job,
                    state="running",
                    attempt_id=attempt_id,
                    attempts=attempts,
                )
                runner = self.runner_factory(manifest_jobs[job.job_id], manifest)
                bind_process_group = getattr(runner, "bind_process_group", None)
                if bind_process_group is not None:
                    bind_process_group(
                        lambda process_group_id, selected_job_id=job.job_id, selected_attempt_id=attempt_id: self._record_process_group(
                            experiment_id,
                            selected_job_id,
                            selected_attempt_id,
                            process_group_id,
                        )
                    )
                key = (experiment_id, job.job_id)
                self._active_runners[key] = runner
                thread = threading.Thread(
                    target=self._execute,
                    args=(experiment_id, job.job_id, attempt_id, runner),
                    name=f"scenarioforge-{experiment_id}-{job.job_id}",
                    daemon=True,
                )
                self._threads[key] = thread
                to_start.append(thread)
                available -= 1
            if to_start:
                state = state.with_update(
                    sequence=state.sequence + 1,
                    jobs=tuple(jobs),
                )
                self.store.save_state(state)
        for thread in to_start:
            thread.start()

    def _execute(
        self,
        experiment_id: str,
        job_id: str,
        attempt_id: str,
        runner: JobRunner,
    ) -> None:
        terminal = "completed"
        detail: dict[str, object] = {}
        try:
            manifest = self.store.load_manifest(experiment_id)
            outcome = runner.run(
                attempt_id=attempt_id,
                timeout_seconds=manifest.limits.timeout_seconds,
            )
            if isinstance(outcome, str):
                terminal = outcome
            else:
                run_result = getattr(outcome, "run_result", None)
                terminal = str(getattr(run_result, "status", "completed"))
                cleanup = getattr(run_result, "process_tree_cleanup", None)
                if cleanup is not None:
                    detail["process_tree_cleanup"] = thaw_json(cleanup)
                published_path = getattr(outcome, "published_path", None)
                if published_path is not None:
                    detail["published_ref"] = (
                        f"published/{getattr(run_result, 'run_id', '')}/"
                        f"{getattr(run_result, 'attempt_id', '')}"
                    )
            if terminal == "success":
                terminal = "completed"
            if terminal not in _TERMINAL_JOBS:
                raise ExperimentServiceError("Worker returned an invalid terminal state")
        except TimeoutError as error:
            terminal = "timeout"
            detail = {"reason": type(error).__name__}
        except BaseException as error:
            terminal = "failed"
            detail = {"reason": type(error).__name__}

        schedule = False
        with self._lock:
            key = (experiment_id, job_id)
            self._active_runners.pop(key, None)
            self._threads.pop(key, None)
            state = self.store.load_state(experiment_id)
            jobs = list(state.jobs)
            index = next(i for i, item in enumerate(jobs) if item.job_id == job_id)
            job = jobs[index]
            if job.attempt_id != attempt_id:
                return
            if job.state == "cancelled":
                if detail:
                    jobs[index] = replace(
                        job,
                        attempts=_attempts_with_terminal(
                            job,
                            attempt_id=attempt_id,
                            terminal="cancelled",
                            extra=detail,
                        ),
                    )
                    self.store.save_state(
                        state.with_update(
                            sequence=state.sequence + 1,
                            jobs=tuple(jobs),
                        )
                    )
                return
            jobs[index] = replace(
                job,
                state=terminal,
                attempts=_attempts_with_terminal(
                    job,
                    attempt_id=attempt_id,
                    terminal=terminal,
                    extra=detail,
                ),
            )
            nonterminal = [item for item in jobs if item.state not in _TERMINAL_JOBS]
            if nonterminal:
                experiment_state = state.state
                schedule = state.state == "running"
            elif any(item.state in {"failed", "timeout"} for item in jobs):
                experiment_state = "failed"
            elif all(item.state == "cancelled" for item in jobs):
                experiment_state = "cancelled"
            else:
                experiment_state = "completed"
            updated = state.with_update(
                state=experiment_state,
                sequence=state.sequence + 1,
                jobs=tuple(jobs),
            )
            self.store.save_state(updated)
        if schedule:
            self._schedule(experiment_id)

    def _record_process_group(
        self,
        experiment_id: str,
        job_id: str,
        attempt_id: str,
        process_group_id: int,
    ) -> None:
        with self._lock:
            state = self.store.load_state(experiment_id)
            jobs = list(state.jobs)
            index = next(i for i, item in enumerate(jobs) if item.job_id == job_id)
            job = jobs[index]
            if job.attempt_id != attempt_id or job.state not in {"running", "paused"}:
                return
            attempts = [dict(thaw_json(item)) for item in job.attempts]
            if not attempts or attempts[-1].get("attempt_id") != attempt_id:
                raise ExperimentServiceError("active attempt history is inconsistent")
            attempts[-1]["process_group_id"] = process_group_id
            jobs[index] = replace(
                job,
                attempts=tuple(freeze_json(item) for item in attempts),
            )
            self.store.save_state(
                state.with_update(
                    sequence=state.sequence + 1,
                    jobs=tuple(jobs),
                )
            )

    def recover(self) -> None:
        restart: list[str] = []
        with self._lock:
            for experiment_id in self.store.list_experiment_ids():
                state = self.store.load_state(experiment_id)
                if state.state not in {"running", "paused"}:
                    continue
                jobs: list[JobState] = []
                for job in state.jobs:
                    if job.state not in {"running", "paused"} or job.attempt_id is None:
                        jobs.append(job)
                        continue
                    attempts = [dict(thaw_json(item)) for item in job.attempts]
                    current = attempts[-1] if attempts else {"attempt_id": job.attempt_id}
                    process_group_id = current.get("process_group_id")
                    cleanup: Mapping[str, object] = {
                        "schema_version": "scenarioforge.process-tree-termination/v1",
                        "remaining_pids": [],
                        "complete": True,
                    }
                    if isinstance(process_group_id, int) and process_group_id > 0:
                        cleanup = self.orphan_cleanup(process_group_id)
                    if not cleanup.get("complete") or cleanup.get("remaining_pids"):
                        raise ExperimentServiceError("orphan process tree cleanup failed")
                    terminal = {
                        **current,
                        "attempt_id": job.attempt_id,
                        "state": "failed",
                        "reason": "infrastructure_interrupted",
                        "cleanup": dict(cleanup),
                    }
                    if attempts:
                        attempts[-1] = terminal
                    else:
                        attempts.append(terminal)
                    jobs.append(
                        replace(
                            job,
                            state="queued",
                            attempt_id=None,
                            attempts=tuple(freeze_json(item) for item in attempts),
                        )
                    )
                recovered = state.with_update(
                    state="running",
                    sequence=state.sequence + 1,
                    jobs=tuple(jobs),
                )
                self.store.save_state(recovered)
                restart.append(experiment_id)
        for experiment_id in restart:
            self._schedule(experiment_id)
