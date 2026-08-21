from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from scenarioforge.core import (
    ScenarioCompiler,
    canonical_bytes,
    instantiate_scenario,
    load_scenario,
)


ROOT = Path(__file__).resolve().parents[4]
SCENARIO = ROOT / "examples" / "p0c" / "unprotected_left_turn.json"
FROZEN = (
    ROOT
    / "tests"
    / "fixtures"
    / "p0c"
    / "calibration"
    / "frozen-contracts.json"
)


def _run_real_metadrive(runtime_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    scenario = instantiate_scenario(load_scenario(SCENARIO))
    bundle = ScenarioCompiler().compile(scenario)
    assert bundle.report.executable is True, bundle.report.to_dict()
    assert bundle.execution_plan is not None

    plan = bundle.execution_plan.to_dict()
    plan_path = runtime_path / "execution-plan.json"
    artifacts_path = runtime_path / "artifacts.json"
    plan_path.write_bytes(canonical_bytes(plan))
    child_environment = dict(os.environ)
    inherited_python_path = child_environment.get("PYTHONPATH", "")
    child_environment["PYTHONPATH"] = str(ROOT / "src") + (
        os.pathsep + inherited_python_path if inherited_python_path else ""
    )
    child_environment["PYTHONDONTWRITEBYTECODE"] = "1"
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
        env=child_environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr
    return plan, json.loads(artifacts_path.read_text(encoding="utf-8"))


def test_real_metadrive_yields_then_completes_the_left_turn(
    tmp_path: Path,
) -> None:
    frozen = json.loads(FROZEN.read_text(encoding="utf-8"))
    preset = next(
        item
        for item in frozen["presets"]
        if item["preset_id"] == "unprotected_left_turn"
    )
    plan, artifacts = _run_real_metadrive(tmp_path)
    metrics = artifacts["metrics.json"]
    trajectory = artifacts["trajectory.json"]
    actions = artifacts["actions.json"]

    assert plan["backend"]["version"] == "0.4.3"
    assert plan["simulation"]["headless"] is True
    assert [event["event_id"] for event in artifacts["events.json"]] == [
        "yield-started",
        "left-turn-committed",
    ]

    yield_action = next(
        action
        for action in actions
        if action["participant_id"] == "ego" and action["tick"] == 20
    )
    commit_action = next(
        action
        for action in actions
        if action["participant_id"] == "ego" and action["tick"] == 39
    )
    assert yield_action["source"] == "scenario_override"
    assert yield_action["final_action"]["throttle_brake"] == -1.0
    assert commit_action["source"] == "scenario_override"
    assert commit_action["final_action"]["throttle_brake"] == 0.5
    yield_actions = [
        action
        for action in actions
        if action["participant_id"] == "ego"
        and action["source"] == "scenario_override"
        and action["final_action"]["throttle_brake"] == -1.0
    ]
    assert [action["tick"] for action in yield_actions] == list(range(20, 39))

    ego_points = [
        point for point in trajectory if point["participant_id"] == "ego"
    ]
    oncoming_points = [
        point for point in trajectory if point["participant_id"] == "oncoming"
    ]
    ego_lane_ids = list(dict.fromkeys(point["lane_id"] for point in ego_points))
    oncoming_conflict_ticks = [
        point["tick"]
        for point in oncoming_points
        if point["lane_id"] == "oncoming-through"
    ]
    ego_conflict_ticks = [
        point["tick"]
        for point in ego_points
        if point["lane_id"] == "ego-left-turn"
    ]

    assert oncoming_conflict_ticks
    assert ego_conflict_ticks
    assert max(oncoming_conflict_ticks) < min(ego_conflict_ticks)
    assert max(
        point["speed_mps"]
        for point in ego_points
        if 28 <= point["tick"] <= 39
    ) < 0.5
    assert ego_lane_ids == ["ego-inbound", "ego-left-turn", "ego-exit"]
    assert all(point["wrong_route"] is False for point in ego_points)
    assert ego_points[-1]["lane_id"] == "ego-exit"
    assert ego_points[-1]["route_completed"] is True

    assert metrics["execution_status"] == "completed"
    assert metrics["scenario_outcome"] == "near_miss"
    assert metrics["target_outcome_match"] is True
    assert metrics["termination_reason"] == "success_predicates_satisfied"
    assert metrics["predicate_results"] == preset["expected"]["predicate_results"]
    assert metrics["predicate_results"]["success"] == [
        {
            "predicate_id": "yield-completed",
            "kind": "yield_completed",
            "satisfied": True,
        }
    ]
    assert all(
        predicate["satisfied"] is False
        for predicate in metrics["predicate_results"]["failure"]
    )

    values = {item["metric"]: item["value"] for item in metrics["metric_values"]}
    assert values["collision"] is False
    for metric, bounds in preset["expected"]["metric_ranges"].items():
        assert bounds is not None
        assert bounds["minimum"] <= values[metric] <= bounds["maximum"]
