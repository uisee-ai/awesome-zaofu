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
SCENARIO = ROOT / "examples" / "p0c" / "brake_lead.json"


@pytest.fixture(scope="module")
def real_run(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[dict[str, Any], dict[str, Any]]:
    bundle = ScenarioCompiler().compile(instantiate_scenario(load_scenario(SCENARIO)))
    assert bundle.report.overall_status is CompilationStatus.EXACT
    assert bundle.execution_plan is not None
    plan = bundle.execution_plan.to_dict()
    runtime_path = tmp_path_factory.mktemp("brake-lead-real")
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


def test_real_metadrive_applies_frozen_braking_then_ego_avoidance(
    real_run: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    plan, artifacts = real_run
    trajectory = artifacts["trajectory.json"]
    by_actor_tick = {
        (item["participant_id"], item["tick"]): item for item in trajectory
    }

    assert plan["backend"] == {
        "id": "metadrive",
        "version": "0.4.3",
        "adapter": {"id": "scenarioforge.metadrive", "version": "2.0.0"},
    }
    assert plan["simulation"]["headless"] is True
    assert by_actor_tick[("lead", 0)]["lane_longitudinal_m"] - by_actor_tick[
        ("ego", 0)
    ]["lane_longitudinal_m"] == pytest.approx(28.0, abs=0.01)
    assert artifacts["events.json"] == [
        {
            "schema_version": "scenarioforge.event/v2",
            "event_id": "lead-hard-brake",
            "sequence": 0,
            "type": "trigger_fired",
            "participant_id": "lead",
            "trigger_tick": 35,
            "effect_state_tick": 36,
            "priority_contract": "scenarioforge.trigger-priority/v2",
            "action": {"steering": 0.0, "throttle_brake": -1.0},
        },
        {
            "schema_version": "scenarioforge.event/v2",
            "event_id": "ego-avoidance-brake",
            "sequence": 1,
            "type": "trigger_fired",
            "participant_id": "ego",
            "trigger_tick": 40,
            "effect_state_tick": 41,
            "priority_contract": "scenarioforge.trigger-priority/v2",
            "action": {"steering": 0.0, "throttle_brake": -0.7},
        },
    ]
    override_actions = [
        item for item in artifacts["actions.json"] if item["source"] == "scenario_override"
    ]
    assert [
        item["tick"] for item in override_actions if item["participant_id"] == "lead"
    ] == list(range(35, 41))
    assert [
        item["tick"] for item in override_actions if item["participant_id"] == "ego"
    ] == list(range(40, 46))
    assert all(
        item["final_action"] == {"steering": 0.0, "throttle_brake": -1.0}
        for item in override_actions
        if item["participant_id"] == "lead"
    )
    assert all(
        item["final_action"] == {"steering": 0.0, "throttle_brake": -0.7}
        for item in override_actions
        if item["participant_id"] == "ego"
    )
    lead_speeds = [by_actor_tick[("lead", tick)]["speed_mps"] for tick in range(35, 42)]
    ego_speeds = [by_actor_tick[("ego", tick)]["speed_mps"] for tick in range(40, 47)]
    assert sum(right < left - 0.5 for left, right in zip(lead_speeds, lead_speeds[1:])) >= 3
    assert sum(right < left - 0.5 for left, right in zip(ego_speeds, ego_speeds[1:])) >= 3


def test_real_metadrive_finishes_as_verified_near_miss_without_contact(
    real_run: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    _, artifacts = real_run
    metrics = artifacts["metrics.json"]
    trajectory = artifacts["trajectory.json"]

    assert all(item["collision"] is False for item in trajectory)
    assert all(item["boundary_violation"] is False for item in trajectory)
    assert metrics["execution_status"] == "completed"
    assert metrics["scenario_outcome"] == "near_miss"
    assert metrics["target_scenario_outcome"] == "near_miss"
    assert metrics["target_outcome_match"] is True
    assert metrics["termination_reason"] == "success_predicates_satisfied"
    assert metrics["predicate_results"] == {
        "success": [
            {
                "predicate_id": "routes-completed",
                "kind": "route_completed",
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
                "predicate_id": "route-timeout",
                "kind": "timeout",
                "satisfied": False,
            },
        ],
    }
    metric_values = {item["metric"]: item for item in metrics["metric_values"]}
    assert metric_values["collision"]["value"] is False
    assert -15.503 <= metric_values["hard_braking"]["value"] <= -15.501
    assert metric_values["hard_braking"]["threshold_met"] is True
    assert 3.35 <= metric_values["minimum_ttc"]["value"] <= 3.352
    assert metric_values["minimum_ttc"]["threshold_met"] is True
    assert 8.599 <= metric_values["completion_time"]["value"] <= 8.601
    assert metric_values["termination_reason"]["value"] == (
        "success_predicates_satisfied"
    )
