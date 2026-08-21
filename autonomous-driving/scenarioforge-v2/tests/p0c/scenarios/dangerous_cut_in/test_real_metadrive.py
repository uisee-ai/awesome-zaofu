from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest

from scenarioforge.core import ScenarioCompiler, instantiate_scenario, load_scenario
from scenarioforge.runtime import RunSupervisor


ROOT = Path(__file__).resolve().parents[4]
SCENARIO = ROOT / "examples" / "p0c" / "dangerous_cut_in.json"


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def published_collision_run(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[dict[str, Any], Any]:
    scenario = instantiate_scenario(load_scenario(SCENARIO))
    bundle = ScenarioCompiler().compile(scenario)
    assert bundle.report.executable is True, bundle.report.to_dict()
    assert bundle.execution_plan is not None
    plan = bundle.execution_plan.to_dict()
    supervisor = RunSupervisor(
        workspace=tmp_path_factory.mktemp("dangerous-cut-in-run"),
        project_root=ROOT,
    )
    outcome = supervisor.run(
        bundle,
        run_id="run-dangerous-cut-in",
        attempt_id="attempt-0001",
        timeout_seconds=120,
    )
    return plan, outcome


def test_real_worker_completes_normally_with_collision_failure_result(
    published_collision_run: tuple[dict[str, Any], Any],
) -> None:
    _, outcome = published_collision_run
    published = outcome.published_path
    result = _read(published / "run_result.json")
    index = _read(published / "artifact_index.json")
    marker = _read(published / "SUCCESS")
    terminal = {
        "execution_status": "completed",
        "scenario_outcome": "collision_failure",
        "termination_reason": "collision",
    }

    assert outcome.worker_exit_code == 0
    assert outcome.worker_pid != os.getpid()
    assert outcome.worker_exited is True
    assert {key: result[key] for key in terminal} == terminal
    assert {key: index[key] for key in terminal} == terminal
    assert result["schema_version"] == "scenarioforge.run-result/v2"
    assert result["worker_exit_code"] == 0
    assert marker == {
        "schema_version": "scenarioforge.completion-marker/v2",
        **terminal,
        "run_result_digest": _digest(published / "run_result.json"),
        "artifact_index_digest": _digest(published / "artifact_index.json"),
    }
    assert not (published / "FAILED").exists()
    assert not (published / "TIMEOUT").exists()
    assert not (published / "PARTIAL").exists()


def test_real_cut_in_event_collision_trajectory_and_metrics_match_freeze(
    published_collision_run: tuple[dict[str, Any], Any],
) -> None:
    _, outcome = published_collision_run
    output = outcome.published_path / "output"
    events = _read(output / "events.json")
    metrics = _read(output / "metrics.json")
    trajectory = _read(output / "trajectory.json")
    initial = {
        point["participant_id"]: point
        for point in trajectory
        if point["tick"] == 0
    }

    assert [event["event_id"] for event in events] == [
        "dangerous-cut-in-started",
        "dangerous-cut-in-control-2",
        "dangerous-cut-in-control-3",
        "dangerous-cut-in-control-4",
        "dangerous-cut-in-control-5",
        "dangerous-cut-in-control-6",
        "dangerous-cut-in-control-7",
    ]
    assert [event["sequence"] for event in events] == list(range(7))
    assert [event["trigger_tick"] for event in events] == list(range(5, 12))
    assert [event["effect_state_tick"] for event in events] == list(range(6, 13))
    assert all(
        event["schema_version"] == "scenarioforge.event/v2"
        and event["type"] == "trigger_fired"
        and event["participant_id"] == "cutter"
        and event["priority_contract"] == "scenarioforge.trigger-priority/v2"
        and event["action"] == {"steering": -1.0, "throttle_brake": 0.0}
        for event in events
    )
    assert initial["ego"]["lane_id"] == "ego-lane"
    assert initial["cutter"]["lane_id"] == "adjacent-lane"
    assert initial["cutter"]["position_m"][0] > initial["ego"]["position_m"][0]
    assert any(point["collision"] for point in trajectory)
    assert metrics["collision_participants"] == ["cutter", "ego"]
    assert metrics["execution_status"] == "completed"
    assert metrics["scenario_outcome"] == "collision_failure"
    assert metrics["target_outcome_match"] is True
    assert metrics["termination_reason"] == "collision"
    assert metrics["predicate_results"] == {
        "success": [
            {
                "predicate_id": "routes-completed",
                "kind": "route_completed",
                "satisfied": False,
            }
        ],
        "failure": [
            {
                "predicate_id": "collision-observed",
                "kind": "collision",
                "satisfied": True,
            },
            {
                "predicate_id": "cutter-boundary-violation",
                "kind": "boundary_violation",
                "satisfied": False,
            },
            {
                "predicate_id": "route-timeout",
                "kind": "timeout",
                "satisfied": False,
            },
        ],
    }
    values = {item["metric"]: item["value"] for item in metrics["metric_values"]}
    assert values["collision"] is True
    assert -11.871 <= values["hard_braking"] <= -11.869
    assert 0.497 <= values["minimum_ttc"] <= 0.5
    assert values["completion_time"] is None
    assert values["termination_reason"] == "collision"


def test_published_collision_run_contains_only_fully_verified_evidence(
    published_collision_run: tuple[dict[str, Any], Any],
) -> None:
    plan, outcome = published_collision_run
    published = outcome.published_path
    index = _read(published / "artifact_index.json")
    expected_paths = [
        "input/assets.json",
        "input/compile_report.json",
        "input/execution_plan.json",
        "input/policy.json",
        "input/run_manifest.json",
        "input/run_request.json",
        "output/actions.json",
        "output/events.json",
        "output/metrics.json",
        "output/trajectory.json",
        "output/worker_result.json",
    ]

    assert plan["artifact_contract"] == {
        "schema_version": "scenarioforge.artifact-contract/v2",
        "required": [
            "actions.json",
            "events.json",
            "metrics.json",
            "trajectory.json",
            "worker_result.json",
        ],
        "fully_verified_required": True,
        "max_file_bytes": 10_485_760,
    }
    assert [entry["path"] for entry in index["artifacts"]] == expected_paths
    for entry in index["artifacts"]:
        artifact = published.joinpath(*entry["path"].split("/"))
        assert entry == {
            "path": entry["path"],
            "status": "present",
            "size_bytes": artifact.stat().st_size,
            "digest": _digest(artifact),
            "validation": "verified",
        }
    worker_result = _read(published / "output" / "worker_result.json")
    assert worker_result["execution_status"] == "completed"
    assert worker_result["scenario_outcome"] == "collision_failure"
    assert worker_result["termination_reason"] == "collision"
