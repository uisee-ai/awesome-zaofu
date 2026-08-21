from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from scenarioforge.core import (
    ScenarioCompiler,
    canonical_bytes,
    instantiate_scenario,
    load_scenario,
)


ROOT = Path(__file__).resolve().parents[4]
SCENARIO = ROOT / "examples" / "p0c" / "highway_merge.json"


def _execute_real_metadrive(runtime_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    scenario = instantiate_scenario(load_scenario(SCENARIO))
    bundle = ScenarioCompiler().compile(scenario)
    assert bundle.report.executable is True, bundle.report.to_dict()
    assert bundle.execution_plan is not None

    plan = bundle.execution_plan.to_dict()
    plan_path = runtime_path / "execution-plan.json"
    artifacts_path = runtime_path / "artifacts.json"
    plan_path.write_bytes(canonical_bytes(plan))
    environment = dict(os.environ)
    inherited_python_path = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = str(ROOT / "src") + (
        os.pathsep + inherited_python_path if inherited_python_path else ""
    )
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json,sys; from pathlib import Path; "
                "from scenarioforge.core import canonical_bytes; "
                "from scenarioforge.runtime.adapter import MetaDriveAdapter; "
                "plan=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8')); "
                "Path(sys.argv[2]).write_bytes(canonical_bytes(MetaDriveAdapter(plan).run()))"
            ),
            str(plan_path),
            str(artifacts_path),
        ],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr
    return plan, json.loads(artifacts_path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def real_highway_merge(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[dict[str, Any], dict[str, Any]]:
    return _execute_real_metadrive(tmp_path_factory.mktemp("highway-merge-runtime"))


def test_real_metadrive_starts_on_ramp_between_mainline_front_and_rear(
    real_highway_merge: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    plan, artifacts = real_highway_merge
    trajectory = artifacts["trajectory.json"]
    initial = {
        point["participant_id"]: point
        for point in trajectory
        if point["tick"] == 0
    }

    assert plan["simulation"]["topology"]["topology_kind"] == "ramp_merge"
    assert initial["ego"]["lane_id"] == "ramp-merge"
    assert initial["ego"]["engine_lane_index"] == [">>", ">>>", 0]
    assert initial["front"]["lane_id"] == "merged-lane"
    assert initial["front"]["engine_lane_index"] == [">>", ">>>", 1]
    assert initial["rear"]["lane_id"] == "merged-lane"
    assert initial["rear"]["engine_lane_index"] == [">>", ">>>", 1]
    assert initial["front"]["position_m"][0] > initial["ego"]["position_m"][0]
    assert initial["rear"]["position_m"][0] < initial["ego"]["position_m"][0]


def test_real_metadrive_selects_gap_adjusts_speed_and_reaches_right_mainline_goal(
    real_highway_merge: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    _, artifacts = real_highway_merge
    actions = artifacts["actions.json"]
    events = artifacts["events.json"]
    trajectory = artifacts["trajectory.json"]
    metrics = artifacts["metrics.json"]
    ego_points = [
        point for point in trajectory if point["participant_id"] == "ego"
    ]

    assert [item["event_id"] for item in events] == [
        "gap-selected",
        "gap-merge-control-2",
        "gap-merge-control-3",
        "gap-merge-control-4",
        "gap-merge-control-5",
        "gap-merge-control-6",
        "gap-merge-control-7",
    ]
    ego_merge_actions = [
        item
        for item in actions
        if item["participant_id"] == "ego" and 5 <= item["tick"] <= 11
    ]
    assert [item["tick"] for item in ego_merge_actions] == list(range(5, 12))
    assert [item["final_action"] for item in ego_merge_actions] == [
        {"steering": -1.0, "throttle_brake": 0.1}
    ] * 7
    assert [item["source"] for item in ego_merge_actions] == [
        "scenario_override"
    ] * 7
    assert ego_points[0]["speed_mps"] == pytest.approx(20.0, abs=0.1)
    assert ego_points[-1]["route_completed"] is True
    assert ego_points[-1]["lane_id"] == "merged-lane"
    assert ego_points[-1]["route_destination_matches"] is True
    assert all(point["lane_id"] != "mainline-wrong-lane" for point in ego_points)
    assert metrics["completed_steps"] == ego_points[-1]["tick"]


def test_real_metadrive_reports_safe_pass_and_all_failure_modes_false(
    real_highway_merge: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    _, artifacts = real_highway_merge
    metrics = artifacts["metrics.json"]

    assert metrics["execution_status"] == "completed"
    assert metrics["scenario_outcome"] == "safe_pass"
    assert metrics["target_outcome_match"] is True
    assert metrics["termination_reason"] == "success_predicates_satisfied"
    assert metrics["collision"] is False
    assert metrics["predicate_results"] == {
        "success": [
            {
                "predicate_id": "merge-completed",
                "kind": "merge_completed",
                "satisfied": True,
            }
        ],
        "failure": [
            {
                "predicate_id": "collision-observed",
                "kind": "collision",
                "satisfied": False,
            },
            {
                "predicate_id": "ego-route-departure",
                "kind": "boundary_violation",
                "satisfied": False,
            },
            {
                "predicate_id": "wrong-mainline-lane-entered",
                "kind": "wrong_lane",
                "satisfied": False,
            },
            {
                "predicate_id": "merge-timeout",
                "kind": "timeout",
                "satisfied": False,
            },
        ],
    }
    values = {item["metric"]: item["value"] for item in metrics["metric_values"]}
    assert values["collision"] is False
    assert -3.374 < values["hard_braking"] < -3.372
    assert 11.522 < values["minimum_ttc"] < 11.524
    assert 2.499 < values["completion_time"] < 2.501
    assert values["termination_reason"] == "success_predicates_satisfied"
