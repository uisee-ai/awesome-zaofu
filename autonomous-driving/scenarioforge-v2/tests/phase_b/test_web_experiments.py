from __future__ import annotations

import time
from pathlib import Path

from starlette.testclient import TestClient

from scenarioforge.orchestration.service import ExperimentService
from scenarioforge.orchestration.store import ExperimentStore
from scenarioforge.web.api import ScenarioForgeAPI
from scenarioforge.web.server import create_app


PORT = 7421
ORIGIN = f"http://127.0.0.1:{PORT}"
TOKEN = "phase-b-test-token-abcdefghijklmnopqrstuvwxyz-012345"


class ImmediateRunner:
    def run(self, *, attempt_id: str, timeout_seconds: int) -> str:
        return "completed"

    def pause(self) -> bool:
        return True

    def resume(self) -> bool:
        return True

    def step(self) -> bool:
        return True

    def cancel(self, *, command_id: str, reason: str) -> bool:
        return True


class NoopCoordinator:
    def interrupt_active_for_shutdown(self) -> bool:
        return False

    def wait_for_terminal(self, run_id: str, *, timeout: float | None = None) -> object:
        return object()

    def active_state(self, run_id: str):
        raise AssertionError("legacy run API was not expected")

    def reference(self, run_id: str):
        raise AssertionError("legacy run API was not expected")


class NoopEvidence:
    pass


def _definition() -> dict[str, object]:
    return {
        "schema_version": "scenarioforge.experiment-definition/v1",
        "matrix": {"scenario_id": ["brake_lead"], "seed": [7]},
        "inputs": {"scenario_revision_digest": "a" * 64},
        "limits": {
            "active_experiments": 1,
            "artifact_bytes": 10_485_760,
            "concurrency": 2,
            "cpu_max_period": 100_000,
            "cpu_max_quota": 100_000,
            "log_bytes": 1_048_576,
            "max_jobs": 64,
            "memory_mib": 4_096,
            "pids": 32,
            "timeout_seconds": 120,
        },
    }


def _client(tmp_path: Path) -> TestClient:
    coordinator = NoopCoordinator()
    service = ExperimentService(
        store=ExperimentStore(tmp_path),
        runner_factory=lambda _job, _manifest: ImmediateRunner(),
        recover=False,
    )
    api = ScenarioForgeAPI(
        coordinator=coordinator,
        evidence=NoopEvidence(),
        experiment_service=service,
    )
    return TestClient(
        create_app(api=api, coordinator=coordinator, port=PORT, csrf_token=TOKEN),
        base_url=ORIGIN,
    )


def _headers() -> dict[str, str]:
    return {
        "Origin": ORIGIN,
        "X-CSRF-Token": TOKEN,
        "Idempotency-Key": "submit-0001",
    }


def test_actual_api_submits_queries_and_controls_persistent_experiment(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)

    submitted = client.post("/api/experiments", headers=_headers(), json=_definition())
    experiment_id = submitted.json()["experiment_id"]
    listed = client.get("/api/experiments")
    refreshed = client.get(f"/api/experiments/{experiment_id}")
    started = client.post(
        f"/api/experiments/{experiment_id}/commands",
        headers={"Origin": ORIGIN, "X-CSRF-Token": TOKEN},
        json={"operation": "start", "command_id": "command-start-0001"},
    )
    deadline = time.monotonic() + 3
    while client.get(f"/api/experiments/{experiment_id}").json()["state"] != "completed":
        if time.monotonic() >= deadline:
            raise AssertionError("Experiment did not complete")
        time.sleep(0.01)

    assert submitted.status_code == 201
    assert submitted.json()["state"] == "queued"
    assert listed.json()["experiments"][0]["experiment_id"] == experiment_id
    assert refreshed.json()["manifest_digest"] == submitted.json()["manifest_digest"]
    assert started.status_code == 200
    assert client.get(f"/api/experiments/{experiment_id}").json()["jobs"][0][
        "state"
    ] == "completed"


def test_experiment_routes_reject_extra_fields_and_missing_browser_boundary(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    invalid = {**_definition(), "unexpected": True}

    extra = client.post("/api/experiments", headers=_headers(), json=invalid)
    no_origin = client.post(
        "/api/experiments",
        headers={"X-CSRF-Token": TOKEN, "Idempotency-Key": "submit-0001"},
        json=_definition(),
    )

    assert extra.status_code == 400
    assert extra.json() == {"detail": "Experiment definition fields are invalid"}
    assert no_origin.status_code == 403
