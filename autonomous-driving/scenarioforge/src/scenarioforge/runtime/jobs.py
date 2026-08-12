from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from threading import Event, RLock, Thread
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from scenarioforge.compiler import CompiledBundle

from .models import RunOutcome
from .runner import FaultMode, run_bundle

JobState = Literal["queued", "running", "completed", "partial", "cancelled", "aborted", "failed"]


class JobSnapshot(BaseModel):
    """Queryable state for a single accepted, isolated run."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    job_id: str = Field(min_length=1)
    scenario_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: JobState
    bundle_path: str | None
    cancel_requested: bool
    retry_count: Literal[0]
    error: str | None


@dataclass
class _Job:
    compiled: CompiledBundle
    output_root: Path
    fault_plan: dict[int, FaultMode] | None
    cancel_event: Event = field(default_factory=Event)
    done_event: Event = field(default_factory=Event)
    status: JobState = "queued"
    bundle_path: Path | None = None
    outcome: RunOutcome | None = None
    error: str | None = None


class JobManager:
    """Thread-safe asynchronous facade over the process-isolated bundle runner."""

    def __init__(self) -> None:
        self._jobs: dict[str, _Job] = {}
        self._lock = RLock()

    def submit(
        self,
        compiled: CompiledBundle,
        output_root: Path,
        *,
        job_id: str,
        fault_plan: dict[int, FaultMode] | None = None,
    ) -> JobSnapshot:
        with self._lock:
            if job_id in self._jobs:
                raise ValueError(f"job already exists: {job_id}")
            job = _Job(compiled=compiled, output_root=output_root, fault_plan=fault_plan)
            self._jobs[job_id] = job
            thread = Thread(target=self._run, args=(job_id,), daemon=True, name=f"scenarioforge-{job_id}")
            thread.start()
            return self._snapshot(job_id, job)

    def get(self, job_id: str) -> JobSnapshot:
        with self._lock:
            return self._snapshot(job_id, self._require(job_id))

    def cancel(self, job_id: str) -> JobSnapshot:
        with self._lock:
            job = self._require(job_id)
            if job.status in {"completed", "partial", "cancelled", "aborted", "failed"}:
                return self._snapshot(job_id, job)
            job.cancel_event.set()
            return self._snapshot(job_id, job)

    def wait(self, job_id: str, *, timeout_seconds: float | None = None) -> JobSnapshot:
        job = self._require(job_id)
        if not job.done_event.wait(timeout_seconds):
            raise TimeoutError(f"job did not reach a terminal state: {job_id}")
        return self.get(job_id)

    def outcome(self, job_id: str) -> RunOutcome | None:
        with self._lock:
            return self._require(job_id).outcome

    def _run(self, job_id: str) -> None:
        with self._lock:
            job = self._require(job_id)
            job.status = "running"
        try:
            outcome = run_bundle(
                job.compiled,
                job.output_root,
                run_id=job_id,
                fault_plan=job.fault_plan,
                cancel_event=job.cancel_event,
            )
            with self._lock:
                job.outcome = outcome
                job.bundle_path = outcome.bundle_path
                job.status = outcome.status
        except Exception as error:  # noqa: BLE001 - job boundary exposes a terminal failure state
            with self._lock:
                job.status = "failed"
                job.error = f"{type(error).__name__}: {error}"
        finally:
            job.done_event.set()

    def _require(self, job_id: str) -> _Job:
        try:
            return self._jobs[job_id]
        except KeyError as error:
            raise KeyError(f"unknown job: {job_id}") from error

    @staticmethod
    def _snapshot(job_id: str, job: _Job) -> JobSnapshot:
        return JobSnapshot(
            job_id=job_id,
            scenario_digest=job.compiled.scenario_digest,
            status=job.status,
            bundle_path=None if job.bundle_path is None else str(job.bundle_path),
            cancel_requested=job.cancel_event.is_set(),
            retry_count=0,
            error=job.error,
        )
