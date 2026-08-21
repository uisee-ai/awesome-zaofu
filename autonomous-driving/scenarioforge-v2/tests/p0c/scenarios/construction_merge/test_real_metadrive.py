from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from scenarioforge.core import (
    CompilationStatus,
    ScenarioCompiler,
    canonical_bytes,
    instantiate_scenario,
    load_scenario,
)


ROOT = Path(__file__).resolve().parents[4]
SCENARIO = ROOT / "examples" / "p0c" / "construction_merge.json"


@pytest.fixture(scope="module")
def real_run(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[dict[str, Any], dict[str, Any]]:
    bundle = ScenarioCompiler().compile(instantiate_scenario(load_scenario(SCENARIO)))
    assert bundle.report.overall_status is CompilationStatus.EXACT
    assert bundle.execution_plan is not None
    plan = bundle.execution_plan.to_dict()
    runtime_path = tmp_path_factory.mktemp("construction-merge-real")
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


def test_real_metadrive_merges_before_closure_and_passes_the_work_zone(
    real_run: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    plan, artifacts = real_run
    metrics = artifacts["metrics.json"]
    trajectory = artifacts["trajectory.json"]
    ego_points = [item for item in trajectory if item["participant_id"] == "ego"]
    initial = ego_points[0]
    first_open_lane = next(item for item in ego_points if item["lane_id"] == "open-lane")
    closure_point_m = next(
        item["length_m"]
        for item in plan["simulation"]["topology"]["lanes"]
        if item["id"] == "closing-lane"
    )
    taper = plan["simulation"]["topology"]["conflict_zones"][0]

    assert plan["backend"] == {
        "id": "metadrive",
        "version": "0.4.3",
        "adapter": {"id": "scenarioforge.metadrive", "version": "2.0.0"},
    }
    assert plan["simulation"]["headless"] is True
    assert initial["lane_id"] == "closing-lane"
    assert initial["engine_lane_index"] == [">>", ">>>", 0]
    assert first_open_lane["lane_longitudinal_m"] < closure_point_m
    assert first_open_lane["lane_longitudinal_m"] < taper["start_m"]
    assert ego_points[-1]["lane_id"] == "open-lane"
    assert ego_points[-1]["lane_longitudinal_m"] > taper["end_m"]
    assert ego_points[-1]["route_completed"] is True
    assert all(item["lane_id"] != "closed-region" for item in ego_points)
    assert all(item["collision"] is False for item in ego_points)
    assert all(item["boundary_violation"] is False for item in ego_points)
    assert artifacts["events.json"] == [
        {
            "schema_version": "scenarioforge.event/v2",
            "event_id": "closure-merge-started",
            "sequence": 0,
            "type": "trigger_fired",
            "participant_id": "ego",
            "trigger_tick": 20,
            "effect_state_tick": 21,
            "priority_contract": "scenarioforge.trigger-priority/v2",
            "action": {"steering": -1.0, "throttle_brake": 0.1},
        },
        {
            "schema_version": "scenarioforge.event/v2",
            "event_id": "closure-merge-control-2",
            "sequence": 1,
            "type": "trigger_fired",
            "participant_id": "ego",
            "trigger_tick": 21,
            "effect_state_tick": 22,
            "priority_contract": "scenarioforge.trigger-priority/v2",
            "action": {"steering": -1.0, "throttle_brake": 0.1},
        },
        {
            "schema_version": "scenarioforge.event/v2",
            "event_id": "closure-merge-control-3",
            "sequence": 2,
            "type": "trigger_fired",
            "participant_id": "ego",
            "trigger_tick": 22,
            "effect_state_tick": 23,
            "priority_contract": "scenarioforge.trigger-priority/v2",
            "action": {"steering": -1.0, "throttle_brake": 0.1},
        },
        {
            "schema_version": "scenarioforge.event/v2",
            "event_id": "closure-merge-control-4",
            "sequence": 3,
            "type": "trigger_fired",
            "participant_id": "ego",
            "trigger_tick": 23,
            "effect_state_tick": 24,
            "priority_contract": "scenarioforge.trigger-priority/v2",
            "action": {"steering": -1.0, "throttle_brake": 0.1},
        },
        {
            "schema_version": "scenarioforge.event/v2",
            "event_id": "closure-merge-control-5",
            "sequence": 4,
            "type": "trigger_fired",
            "participant_id": "ego",
            "trigger_tick": 24,
            "effect_state_tick": 25,
            "priority_contract": "scenarioforge.trigger-priority/v2",
            "action": {"steering": -1.0, "throttle_brake": 0.1},
        },
        {
            "schema_version": "scenarioforge.event/v2",
            "event_id": "closure-merge-control-6",
            "sequence": 5,
            "type": "trigger_fired",
            "participant_id": "ego",
            "trigger_tick": 25,
            "effect_state_tick": 26,
            "priority_contract": "scenarioforge.trigger-priority/v2",
            "action": {"steering": -1.0, "throttle_brake": 0.1},
        },
    ]
    assert metrics["execution_status"] == "completed"
    assert metrics["scenario_outcome"] == "safe_pass"
    assert metrics["target_scenario_outcome"] == "safe_pass"
    assert metrics["target_outcome_match"] is True
    assert metrics["termination_reason"] == "success_predicates_satisfied"
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
                "predicate_id": "ego-boundary-violation",
                "kind": "boundary_violation",
                "satisfied": False,
            },
            {
                "predicate_id": "closed-region-entered",
                "kind": "closed_region_entry",
                "satisfied": False,
            },
            {
                "predicate_id": "merge-timeout",
                "kind": "timeout",
                "satisfied": False,
            },
        ],
    }
    metric_values = {item["metric"]: item["value"] for item in metrics["metric_values"]}
    assert metric_values["collision"] is False
    assert -3.287 <= metric_values["hard_braking"] <= -3.286
    assert metric_values["minimum_ttc"] is None
    assert 7.499 <= metric_values["completion_time"] <= 7.501
    assert metric_values["termination_reason"] == "success_predicates_satisfied"
