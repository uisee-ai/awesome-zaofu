from __future__ import annotations

import threading
import time
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

from scenarioforge.core.canonical import freeze_json
from scenarioforge.orchestration.contracts import ExperimentDefinition, ExperimentLimits
from scenarioforge.orchestration.service import ExperimentService
from scenarioforge.orchestration.store import ExperimentStore


def _definition() -> ExperimentDefinition:
    return ExperimentDefinition.from_mapping(
        {
            "schema_version": "scenarioforge.experiment-definition/v1",
            "matrix": {"scenario_id": ["brake_lead"], "seed": [7]},
            "inputs": {"scenario_revision_digest": "a" * 64},
            "limits": ExperimentLimits.release_default().to_dict(),
        }
    )


class CompletingRunner:
    def __init__(self) -> None:
        self.started = threading.Event()

    def run(self, *, attempt_id: str, timeout_seconds: int) -> str:
        self.started.set()
        return "completed"

    def pause(self) -> bool:
        return True

    def resume(self) -> bool:
        return True

    def step(self) -> bool:
        return True

    def cancel(self, *, command_id: str, reason: str) -> bool:
        return True


def test_restart_reconciles_orphan_and_retries_with_new_attempt_without_overwrite(
    tmp_path: Path,
) -> None:
    store = ExperimentStore(tmp_path)
    manifest = store.submit(_definition(), idempotency_key="submit-0001")
    state = store.load_state(manifest.experiment_id)
    stale_attempt = "attempt-before-restart"
    running_job = replace(
        state.jobs[0],
        state="running",
        attempt_id=stale_attempt,
        attempts=(
            freeze_json(
                {
                    "attempt_id": stale_attempt,
                    "state": "running",
                    "process_group_id": 4321,
                }
            ),
        ),
    )
    store.save_state(
        state.with_update(
            state="running",
            sequence=4,
            jobs=(running_job,),
            commands=MappingProxyType({"command-start": {"operation": "start"}}),
        )
    )
    cleanup_calls: list[int] = []
    runners: list[CompletingRunner] = []

    def factory(_job, _manifest):
        runner = CompletingRunner()
        runners.append(runner)
        return runner

    service = ExperimentService(
        store=ExperimentStore(tmp_path),
        runner_factory=factory,
        orphan_cleanup=lambda process_group_id: cleanup_calls.append(process_group_id)
        or {
            "schema_version": "scenarioforge.process-tree-termination/v1",
            "process_group_id": process_group_id,
            "remaining_pids": [],
            "complete": True,
        },
    )
    deadline = time.monotonic() + 3
    while service.get(manifest.experiment_id)["state"] != "completed":
        if time.monotonic() >= deadline:
            raise AssertionError("recovered job did not complete")
        time.sleep(0.01)

    job = service.get(manifest.experiment_id)["jobs"][0]
    assert cleanup_calls == [4321]
    assert job["attempt_id"] != stale_attempt
    assert job["attempts"][0] == {
        "attempt_id": stale_attempt,
        "cleanup": {
            "complete": True,
            "process_group_id": 4321,
            "remaining_pids": [],
            "schema_version": "scenarioforge.process-tree-termination/v1",
        },
        "process_group_id": 4321,
        "reason": "infrastructure_interrupted",
        "state": "failed",
    }
    assert job["attempts"][1]["attempt_id"] == job["attempt_id"]
    assert job["attempts"][1]["state"] == "completed"
