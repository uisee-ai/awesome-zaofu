from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scenarioforge.core import (
    ScenarioCompiler,
    canonical_bytes,
    instantiate_scenario,
    load_scenario,
)


ROOT = Path(__file__).resolve().parents[3]
PROTOTYPE = ROOT / "tests" / "fixtures" / "p0c" / "contracts" / "prototype_v2.json"


def _angular_distance_deg(left: float, right: float) -> float:
    return abs((left - right + 180.0) % 360.0 - 180.0)


def _runtime_candidate(path: Path) -> Path:
    candidate = json.loads(PROTOTYPE.read_text(encoding="utf-8"))
    candidate["scenario_id"] = "metadrive_v2_runtime_contract"
    candidate["seed"] = 73
    candidate["road"]["topology_kind"] = "straight"
    candidate["road"]["map_block_sequence"] = "S"
    candidate["road"]["lanes"] = [
        {
            "id": "eastbound",
            "road_id": "corridor",
            "engine_lane_index": {
                "start_node": ">>",
                "end_node": ">>>",
                "lane_index": 0,
            },
            "kind": "travel",
            "length_m": 180.0,
            "predecessor_lane_ids": [],
            "successor_lane_ids": [],
        },
        {
            "id": "westbound",
            "road_id": "corridor",
            "engine_lane_index": {
                "start_node": "->>>",
                "end_node": "->>",
                "lane_index": 0,
            },
            "kind": "travel",
            "length_m": 180.0,
            "predecessor_lane_ids": [],
            "successor_lane_ids": [],
        },
    ]
    candidate["road"]["conflict_zones"] = [
        {
            "id": "opposing-pass",
            "lane_ids": ["eastbound", "westbound"],
            "start_m": 20.0,
            "end_m": 50.0,
        }
    ]
    candidate["participants"] = [
        {
            "id": "ego",
            "role": "ego",
            "actor_type": "vehicle",
            "spawn": {
                "schema_version": "scenarioforge.actor-spawn/v2",
                "lane_id": "eastbound",
                "longitudinal_m": 5.0,
                "lateral_m": 0.0,
                "speed_mps": 8.0,
                "heading_deg": 0.0,
            },
            "route": {
                "schema_version": "scenarioforge.route/v2",
                "id": "ego-eastbound",
                "lane_ids": ["eastbound"],
                "goal": {"lane_id": "eastbound", "longitudinal_m": 35.0},
            },
        },
        {
            "id": "oncoming",
            "role": "social",
            "actor_type": "vehicle",
            "spawn": {
                "schema_version": "scenarioforge.actor-spawn/v2",
                "lane_id": "westbound",
                "longitudinal_m": 5.0,
                "lateral_m": 0.0,
                "speed_mps": 8.0,
                "heading_deg": 180.0,
            },
            "route": {
                "schema_version": "scenarioforge.route/v2",
                "id": "oncoming-westbound",
                "lane_ids": ["westbound"],
                "goal": {"lane_id": "westbound", "longitudinal_m": 35.0},
            },
        },
    ]
    candidate["events"] = [
        {
            "id": "contract-probe",
            "sequence": 0,
            "type": "control_override",
            "participant_id": "ego",
            "trigger": {
                "schema_version": "scenarioforge.trigger/v2",
                "kind": "tick",
                "tick": 3,
            },
            "action": {
                "schema_version": "scenarioforge.control-action/v2",
                "steering": 0.0,
                "throttle_brake": 0.15,
            },
        }
    ]
    candidate["constraints"]["max_steps"] = 100
    candidate["constraints"]["duration_s"] = 10.0
    candidate["constraints"]["target_outcome"] = "collision_failure"
    candidate["constraints"]["success_predicates"] = [
        {
            "id": "routes-completed",
            "kind": "route_completed",
            "participant_ids": ["ego", "oncoming"],
            "lane_ids": ["eastbound", "westbound"],
        }
    ]
    candidate["constraints"]["failure_predicates"] = [
        {
            "id": "collision-observed",
            "kind": "collision",
            "participant_ids": ["ego", "oncoming"],
            "lane_ids": [],
        },
        {
            "id": "execution-incomplete",
            "kind": "execution_incomplete",
            "participant_ids": [],
            "lane_ids": [],
        },
    ]
    candidate["constraints"]["expected_events"] = ["contract-probe"]
    for definition in candidate["constraints"]["metric_definitions"]:
        definition["applies_to"]["participant_ids"] = ["ego", "oncoming"]
        definition["applies_to"]["topology_kinds"] = ["straight"]
        definition["threshold"] = None
    candidate["policy"]["config"]["participant_actions"] = [
        {"participant_id": "ego", "steering": 0.0, "throttle_brake": 0.15},
        {
            "participant_id": "oncoming",
            "steering": 0.0,
            "throttle_brake": 0.15,
        },
    ]
    path.write_bytes(canonical_bytes(candidate))
    return path


def _intersection_runtime_candidate(path: Path) -> Path:
    candidate = json.loads(PROTOTYPE.read_text(encoding="utf-8"))
    candidate["scenario_id"] = "metadrive_v2_intersection_runtime_contract"
    candidate["seed"] = 43
    candidate["road"]["topology_kind"] = "intersection"
    candidate["road"]["map_block_sequence"] = "X"
    candidate["road"]["lanes"] = [
        {
            "id": "ego-inbound",
            "road_id": "west-approach",
            "engine_lane_index": {
                "start_node": ">>",
                "end_node": ">>>",
                "lane_index": 0,
            },
            "kind": "travel",
            "length_m": 70.0,
            "predecessor_lane_ids": [],
            "successor_lane_ids": ["ego-left-turn"],
        },
        {
            "id": "ego-left-turn",
            "road_id": "intersection",
            "engine_lane_index": {
                "start_node": ">>>",
                "end_node": "1X2_0_",
                "lane_index": 0,
            },
            "kind": "travel",
            "length_m": 22.0,
            "predecessor_lane_ids": ["ego-inbound"],
            "successor_lane_ids": ["ego-exit"],
        },
        {
            "id": "ego-exit",
            "road_id": "north-exit",
            "engine_lane_index": {
                "start_node": "1X2_0_",
                "end_node": "1X2_1_",
                "lane_index": 0,
            },
            "kind": "travel",
            "length_m": 35.0,
            "predecessor_lane_ids": ["ego-left-turn"],
            "successor_lane_ids": [],
        },
        {
            "id": "oncoming-inbound",
            "road_id": "east-approach",
            "engine_lane_index": {
                "start_node": "-1X1_1_",
                "end_node": "-1X1_0_",
                "lane_index": 0,
            },
            "kind": "travel",
            "length_m": 35.0,
            "predecessor_lane_ids": [],
            "successor_lane_ids": ["oncoming-through"],
        },
        {
            "id": "oncoming-through",
            "road_id": "intersection",
            "engine_lane_index": {
                "start_node": "-1X1_0_",
                "end_node": "->>>",
                "lane_index": 0,
            },
            "kind": "travel",
            "length_m": 24.0,
            "predecessor_lane_ids": ["oncoming-inbound"],
            "successor_lane_ids": ["oncoming-exit"],
        },
        {
            "id": "oncoming-exit",
            "road_id": "west-exit",
            "engine_lane_index": {
                "start_node": "->>>",
                "end_node": "->>",
                "lane_index": 0,
            },
            "kind": "travel",
            "length_m": 70.0,
            "predecessor_lane_ids": ["oncoming-through"],
            "successor_lane_ids": [],
        },
    ]
    candidate["road"]["conflict_zones"] = [
        {
            "id": "unprotected-left-conflict",
            "lane_ids": ["ego-left-turn", "oncoming-through"],
            "start_m": 0.0,
            "end_m": 20.0,
        }
    ]
    candidate["participants"] = [
        {
            "id": "ego",
            "role": "ego",
            "actor_type": "vehicle",
            "spawn": {
                "schema_version": "scenarioforge.actor-spawn/v2",
                "lane_id": "ego-inbound",
                "longitudinal_m": 10.0,
                "lateral_m": 0.0,
                "speed_mps": 8.0,
                "heading_deg": 0.0,
            },
            "route": {
                "schema_version": "scenarioforge.route/v2",
                "id": "ego-unprotected-left",
                "lane_ids": ["ego-inbound", "ego-left-turn", "ego-exit"],
                "goal": {"lane_id": "ego-exit", "longitudinal_m": 20.0},
            },
        },
        {
            "id": "oncoming",
            "role": "social",
            "actor_type": "vehicle",
            "spawn": {
                "schema_version": "scenarioforge.actor-spawn/v2",
                "lane_id": "oncoming-inbound",
                "longitudinal_m": 5.0,
                "lateral_m": 0.0,
                "speed_mps": 14.0,
                "heading_deg": 180.0,
            },
            "route": {
                "schema_version": "scenarioforge.route/v2",
                "id": "oncoming-through-route",
                "lane_ids": [
                    "oncoming-inbound",
                    "oncoming-through",
                    "oncoming-exit",
                ],
                "goal": {"lane_id": "oncoming-exit", "longitudinal_m": 20.0},
            },
        },
    ]
    candidate["events"] = [
        {
            "id": "contract-probe",
            "sequence": 0,
            "type": "control_override",
            "participant_id": "ego",
            "trigger": {
                "schema_version": "scenarioforge.trigger/v2",
                "kind": "tick",
                "tick": 3,
            },
            "action": {
                "schema_version": "scenarioforge.control-action/v2",
                "steering": 0.0,
                "throttle_brake": 0.15,
            },
        }
    ]
    candidate["constraints"]["max_steps"] = 100
    candidate["constraints"]["duration_s"] = 10.0
    candidate["constraints"]["target_outcome"] = "collision_failure"
    candidate["constraints"]["success_predicates"] = [
        {
            "id": "routes-completed",
            "kind": "route_completed",
            "participant_ids": ["ego", "oncoming"],
            "lane_ids": ["ego-exit", "oncoming-exit"],
        }
    ]
    candidate["constraints"]["failure_predicates"] = [
        {
            "id": "collision-observed",
            "kind": "collision",
            "participant_ids": ["ego", "oncoming"],
            "lane_ids": [],
        },
        {
            "id": "execution-incomplete",
            "kind": "execution_incomplete",
            "participant_ids": [],
            "lane_ids": [],
        },
    ]
    candidate["constraints"]["expected_events"] = ["contract-probe"]
    for definition in candidate["constraints"]["metric_definitions"]:
        definition["applies_to"]["participant_ids"] = ["ego", "oncoming"]
        definition["applies_to"]["topology_kinds"] = ["intersection"]
        definition["threshold"] = None
    candidate["policy"]["config"]["participant_actions"] = [
        {"participant_id": "ego", "steering": 0.0, "throttle_brake": 0.15},
        {
            "participant_id": "oncoming",
            "steering": 0.0,
            "throttle_brake": 0.15,
        },
    ]
    path.write_bytes(canonical_bytes(candidate))
    return path


def _execute_runtime_candidate(
    candidate_path: Path,
    runtime_path: Path,
) -> tuple[dict[str, object], dict[str, object]]:
    scenario = instantiate_scenario(load_scenario(candidate_path))
    bundle = ScenarioCompiler().compile(scenario)

    assert bundle.report.executable is True
    assert bundle.execution_plan is not None
    plan = bundle.execution_plan.to_dict()
    plan_path = runtime_path / "execution_plan.json"
    artifacts_path = runtime_path / "artifacts.json"
    plan_path.write_bytes(canonical_bytes(plan))
    child_environment = dict(os.environ)
    inherited_python_path = child_environment.get("PYTHONPATH", "")
    child_environment["PYTHONPATH"] = str(ROOT / "src") + (
        os.pathsep + inherited_python_path if inherited_python_path else ""
    )
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
    artifacts = json.loads(artifacts_path.read_text(encoding="utf-8"))
    return plan, artifacts


@pytest.fixture(scope="module")
def real_runtime_artifacts(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[dict[str, object], dict[str, object]]:
    runtime_path = tmp_path_factory.mktemp("p0c-runtime")
    candidate_path = _runtime_candidate(runtime_path / "candidate.json")
    return _execute_runtime_candidate(candidate_path, runtime_path)


@pytest.fixture(scope="module")
def real_intersection_runtime_artifacts(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[dict[str, object], dict[str, object]]:
    runtime_path = tmp_path_factory.mktemp("p0c-intersection-runtime")
    candidate_path = _intersection_runtime_candidate(
        runtime_path / "candidate.json"
    )
    return _execute_runtime_candidate(candidate_path, runtime_path)


def test_real_metadrive_projects_spawn_heading_lane_and_declared_destination(
    real_runtime_artifacts: tuple[dict[str, object], dict[str, object]],
) -> None:
    plan, artifacts = real_runtime_artifacts
    trajectory = artifacts["trajectory.json"]
    assert isinstance(trajectory, list)
    initial = {
        point["participant_id"]: point
        for point in trajectory
        if point["tick"] == 0
    }

    oncoming = initial["oncoming"]
    assert _angular_distance_deg(oncoming["heading_deg"], 180.0) <= 1.0
    assert oncoming["lane_id"] == "westbound"
    assert oncoming["engine_lane_index"] == ["->>>", "->>", 0]
    assert oncoming["route_id"] == "oncoming-westbound"
    assert oncoming["route_destination_lane_id"] == "westbound"
    assert oncoming["route_destination_engine_lane_index"] == [
        "->>>",
        "->>",
        0,
    ]
    assert oncoming["route_checkpoints"] == ["->>>", "->>"]
    assert oncoming["route_destination_matches"] is True
    assert plan["participants"][1]["route"]["goal"]["lane_id"] == "westbound"

    terminal = {
        point["participant_id"]: point
        for point in trajectory
        if point["tick"] == artifacts["metrics.json"]["completed_steps"]
    }
    assert terminal["ego"]["route_completed"] is True
    assert terminal["oncoming"]["route_completed"] is True


def test_real_metadrive_derives_outcome_and_metrics_from_observations(
    real_runtime_artifacts: tuple[dict[str, object], dict[str, object]],
) -> None:
    plan, artifacts = real_runtime_artifacts
    metrics = artifacts["metrics.json"]
    events = artifacts["events.json"]

    assert plan["constraints"]["target_outcome"] == "collision_failure"
    assert metrics["execution_status"] == "completed"
    assert metrics["scenario_outcome"] == "safe_pass"
    assert metrics["termination_reason"] == "success_predicates_satisfied"
    assert metrics["collision"] is False
    assert [event["event_id"] for event in events] == ["contract-probe"]

    values = {
        item["metric"]: item
        for item in metrics["metric_values"]
    }
    assert set(values) == {
        "collision",
        "hard_braking",
        "minimum_ttc",
        "completion_time",
        "termination_reason",
    }
    assert values["collision"]["value"] is False
    assert values["collision"]["definition_id"] == (
        "scenarioforge.metric.collision/v2"
    )
    assert isinstance(values["hard_braking"]["value"], float)
    assert isinstance(values["minimum_ttc"]["value"], float)
    assert values["completion_time"]["value"] > 0.0
    assert values["termination_reason"]["value"] == "success_predicates_satisfied"
    assert all(item["raw_evidence_value"] == item["value"] for item in values.values())
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
                "predicate_id": "execution-incomplete",
                "kind": "execution_incomplete",
                "satisfied": False,
            },
        ],
    }


def test_real_metadrive_projects_unprotected_left_and_oncoming_routes(
    real_intersection_runtime_artifacts: tuple[
        dict[str, object], dict[str, object]
    ],
) -> None:
    plan, artifacts = real_intersection_runtime_artifacts
    trajectory = artifacts["trajectory.json"]
    assert isinstance(trajectory, list)
    initial = {
        point["participant_id"]: point
        for point in trajectory
        if point["tick"] == 0
    }

    ego = initial["ego"]
    assert _angular_distance_deg(ego["heading_deg"], 0.0) <= 1.0
    assert ego["lane_id"] == "ego-inbound"
    assert ego["engine_lane_index"] == [">>", ">>>", 0]
    assert ego["route_checkpoints"] == [">>", ">>>", "1X2_0_", "1X2_1_"]
    assert ego["route_destination_engine_lane_index"] == [
        "1X2_0_",
        "1X2_1_",
        0,
    ]
    assert ego["route_destination_matches"] is True

    oncoming = initial["oncoming"]
    assert _angular_distance_deg(oncoming["heading_deg"], 180.0) <= 1.0
    assert oncoming["lane_id"] == "oncoming-inbound"
    assert oncoming["engine_lane_index"] == ["-1X1_1_", "-1X1_0_", 0]
    assert oncoming["route_checkpoints"] == [
        "-1X1_1_",
        "-1X1_0_",
        "->>>",
        "->>",
    ]
    assert oncoming["route_destination_engine_lane_index"] == [
        "->>>",
        "->>",
        0,
    ]
    assert oncoming["route_destination_matches"] is True

    metrics = artifacts["metrics.json"]
    oncoming_trajectory = [
        point for point in trajectory if point["participant_id"] == "oncoming"
    ]
    assert oncoming_trajectory[-1]["tick"] < metrics["completed_steps"]
    assert oncoming_trajectory[-1]["lane_id"] == "oncoming-exit"
    assert oncoming_trajectory[-1]["route_completed"] is True
    oncoming_actions = [
        action
        for action in artifacts["actions.json"]
        if action["participant_id"] == "oncoming"
    ]
    assert oncoming_actions[-1]["tick"] + 1 == oncoming_trajectory[-1]["tick"]
    assert plan["constraints"]["target_outcome"] == "collision_failure"
    assert metrics["scenario_outcome"] == "near_miss"
    assert metrics["target_outcome_match"] is False
    assert metrics["collision"] is False
    assert metrics["termination_reason"] == "horizon_completed"
