from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from scenarioforge.orchestration.contracts import ExperimentDefinition, ExperimentLimits
from scenarioforge.orchestration.service import (
    ExperimentService,
    InvalidControlTransition,
)
from scenarioforge.orchestration.store import ExperimentStore


def _definition(*, jobs: int = 1) -> ExperimentDefinition:
    return ExperimentDefinition.from_mapping(
        {
            "schema_version": "scenarioforge.experiment-definition/v1",
            "matrix": {
                "scenario_id": ["brake_lead"],
                "seed": list(range(7, 7 + jobs)),
            },
            "inputs": {"scenario_revision_digest": "a" * 64},
            "limits": ExperimentLimits.release_default().to_dict(),
        }
    )


def _wait_for(predicate, *, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError("condition did not become true")
        time.sleep(0.01)


@dataclass
class BlockingRunner:
    job_id: str
    outcome: str = "completed"
    started: threading.Event = field(default_factory=threading.Event)
    released: threading.Event = field(default_factory=threading.Event)
    cancelled: threading.Event = field(default_factory=threading.Event)
    pause_calls: int = 0
    resume_calls: int = 0
    step_calls: int = 0
    cancel_calls: list[dict[str, str]] = field(default_factory=list)

    def run(self, *, attempt_id: str, timeout_seconds: int) -> str:
        assert attempt_id.startswith("attempt-")
        assert timeout_seconds == 120
        self.started.set()
        if not self.released.wait(timeout=3):
            raise TimeoutError("test runner was not released")
        if self.cancelled.is_set():
            return "cancelled"
        if self.outcome == "raise":
            raise RuntimeError("controlled worker crash")
        return self.outcome

    def pause(self) -> bool:
        self.pause_calls += 1
        return True

    def resume(self) -> bool:
        self.resume_calls += 1
        return True

    def step(self) -> bool:
        self.step_calls += 1
        return True

    def cancel(self, *, command_id: str, reason: str) -> bool:
        self.cancel_calls.append({"command_id": command_id, "reason": reason})
        self.cancelled.set()
        self.released.set()
        return True


class RunnerFactory:
    def __init__(self, outcomes: dict[str, str] | None = None) -> None:
        self.outcomes = outcomes or {}
        self.runners: list[BlockingRunner] = []
        self.lock = threading.Lock()

    def __call__(self, job, _manifest) -> BlockingRunner:
        runner = BlockingRunner(job.job_id, outcome=self.outcomes.get(job.job_id, "completed"))
        with self.lock:
            self.runners.append(runner)
        return runner


def _service(tmp_path: Path, factory: RunnerFactory) -> ExperimentService:
    return ExperimentService(
        store=ExperimentStore(tmp_path),
        runner_factory=factory,
        recover=False,
    )


def test_scheduler_enforces_concurrency_two_and_preserves_queued_job(tmp_path: Path) -> None:
    factory = RunnerFactory()
    service = _service(tmp_path, factory)
    submitted = service.submit(_definition(jobs=3), idempotency_key="submit-0001")

    running = service.control(
        submitted["experiment_id"], "start", command_id="command-start-0001"
    )
    _wait_for(lambda: len(factory.runners) == 2 and all(item.started.is_set() for item in factory.runners))

    observed = service.get(submitted["experiment_id"])
    assert running["experiment_id"] == submitted["experiment_id"]
    assert [job["state"] for job in observed["jobs"]] == [
        "running",
        "running",
        "queued",
    ]
    assert len({job["attempt_id"] for job in observed["jobs"][:2]}) == 2

    factory.runners[0].released.set()
    _wait_for(lambda: len(factory.runners) == 3 and factory.runners[2].started.is_set())
    assert [job["state"] for job in service.get(submitted["experiment_id"])["jobs"]].count(
        "running"
    ) == 2

    for runner in factory.runners:
        runner.released.set()
    _wait_for(lambda: service.get(submitted["experiment_id"])["state"] == "completed")


def test_pause_step_resume_and_command_idempotency_are_persistent(tmp_path: Path) -> None:
    factory = RunnerFactory()
    service = _service(tmp_path, factory)
    experiment_id = service.submit(
        _definition(), idempotency_key="submit-0001"
    )["experiment_id"]
    service.control(experiment_id, "start", command_id="command-start-0001")
    _wait_for(lambda: len(factory.runners) == 1 and factory.runners[0].started.is_set())

    paused = service.control(experiment_id, "pause", command_id="command-pause-0001")
    replay = service.control(experiment_id, "pause", command_id="command-pause-0001")
    stepped = service.control(experiment_id, "step", command_id="command-step-0001")
    resumed = service.control(experiment_id, "resume", command_id="command-resume-0001")

    assert replay == paused
    assert paused["state"] == "paused"
    assert stepped["state"] == "paused"
    assert resumed["state"] == "running"
    assert factory.runners[0].pause_calls == 1
    assert factory.runners[0].step_calls == 1
    assert factory.runners[0].resume_calls == 1
    reloaded = ExperimentStore(tmp_path).load_state(experiment_id)
    assert set(reloaded.commands) == {
        "command-start-0001",
        "command-pause-0001",
        "command-step-0001",
        "command-resume-0001",
    }

    factory.runners[0].released.set()
    _wait_for(lambda: service.get(experiment_id)["state"] == "completed")


def test_batch_step_is_rejected_without_mutating_state(tmp_path: Path) -> None:
    factory = RunnerFactory()
    service = _service(tmp_path, factory)
    experiment_id = service.submit(
        _definition(jobs=2), idempotency_key="submit-0001"
    )["experiment_id"]
    service.control(experiment_id, "start", command_id="command-start-0001")
    _wait_for(lambda: len(factory.runners) == 2)
    service.control(experiment_id, "pause", command_id="command-pause-0001")

    with pytest.raises(InvalidControlTransition, match="single-job"):
        service.control(experiment_id, "step", command_id="command-step-0001")

    assert service.get(experiment_id)["state"] == "paused"
    assert all(runner.step_calls == 0 for runner in factory.runners)
    for runner in factory.runners:
        runner.cancel(command_id="cleanup", reason="test_cleanup")


def test_stop_cancels_started_and_queued_jobs_without_starting_new_attempts(
    tmp_path: Path,
) -> None:
    factory = RunnerFactory()
    service = _service(tmp_path, factory)
    experiment_id = service.submit(
        _definition(jobs=3), idempotency_key="submit-0001"
    )["experiment_id"]
    service.control(experiment_id, "start", command_id="command-start-0001")
    _wait_for(lambda: len(factory.runners) == 2 and all(item.started.is_set() for item in factory.runners))

    stopped = service.control(experiment_id, "stop", command_id="command-stop-0001")
    replay = service.control(experiment_id, "stop", command_id="command-stop-0001")

    assert replay == stopped
    assert stopped["state"] == "cancelled"
    assert [job["state"] for job in stopped["jobs"]] == [
        "cancelled",
        "cancelled",
        "cancelled",
    ]
    assert stopped["jobs"][2]["attempt_id"] is None
    assert len(factory.runners) == 2
    assert [runner.cancel_calls for runner in factory.runners] == [
        [{"command_id": "command-stop-0001", "reason": "user_cancelled"}],
        [{"command_id": "command-stop-0001", "reason": "user_cancelled"}],
    ]


def test_stop_does_not_claim_cancellation_when_worker_rejects_command(
    tmp_path: Path,
) -> None:
    factory = RunnerFactory()
    service = _service(tmp_path, factory)
    experiment_id = service.submit(
        _definition(), idempotency_key="submit-0001"
    )["experiment_id"]
    service.control(experiment_id, "start", command_id="command-start-0001")
    _wait_for(lambda: len(factory.runners) == 1 and factory.runners[0].started.is_set())
    factory.runners[0].cancel = lambda **_kwargs: False  # type: ignore[method-assign]

    with pytest.raises(InvalidControlTransition, match="cannot stop"):
        service.control(experiment_id, "stop", command_id="command-stop-0001")

    observed = service.get(experiment_id)
    assert observed["state"] == "running"
    assert observed["jobs"][0]["state"] == "running"
    factory.runners[0].released.set()
    _wait_for(lambda: service.get(experiment_id)["state"] == "completed")


def test_reset_preserves_old_attempt_and_starts_a_new_attempt_for_same_job(
    tmp_path: Path,
) -> None:
    factory = RunnerFactory()
    service = _service(tmp_path, factory)
    experiment_id = service.submit(
        _definition(), idempotency_key="submit-0001"
    )["experiment_id"]
    service.control(experiment_id, "start", command_id="command-start-0001")
    _wait_for(lambda: len(factory.runners) == 1 and factory.runners[0].started.is_set())
    old_attempt = service.get(experiment_id)["jobs"][0]["attempt_id"]

    reset = service.control(experiment_id, "reset", command_id="command-reset-0001")
    _wait_for(lambda: len(factory.runners) == 2 and factory.runners[1].started.is_set())
    current = service.get(experiment_id)["jobs"][0]

    assert reset["state"] in {"queued", "running"}
    assert current["logical_run_id"].endswith("-0001")
    assert current["attempt_id"] != old_attempt
    assert current["attempts"][0]["attempt_id"] == old_attempt
    assert current["attempts"][0]["state"] == "cancelled"
    assert current["attempts"][0]["command_id"] == "command-reset-0001"

    factory.runners[1].released.set()
    _wait_for(lambda: service.get(experiment_id)["state"] == "completed")


def test_worker_crash_isolated_from_sibling_and_next_queued_job(tmp_path: Path) -> None:
    factory = RunnerFactory({"job-0001": "raise"})
    service = _service(tmp_path, factory)
    experiment_id = service.submit(
        _definition(jobs=3), idempotency_key="submit-0001"
    )["experiment_id"]
    service.control(experiment_id, "start", command_id="command-start-0001")
    _wait_for(lambda: len(factory.runners) == 2)

    factory.runners[0].released.set()
    _wait_for(lambda: len(factory.runners) == 3)
    factory.runners[1].released.set()
    factory.runners[2].released.set()
    _wait_for(lambda: service.get(experiment_id)["state"] == "failed")

    observed = service.get(experiment_id)
    assert [job["state"] for job in observed["jobs"]] == [
        "failed",
        "completed",
        "completed",
    ]
