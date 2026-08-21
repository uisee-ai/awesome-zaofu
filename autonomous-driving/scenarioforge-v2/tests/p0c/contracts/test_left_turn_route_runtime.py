from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from scenarioforge.core import (
    ScenarioCompiler,
    canonical_bytes,
    instantiate_scenario,
    load_scenario,
)


ROOT = Path(__file__).resolve().parents[3]
PROTOTYPE = ROOT / "tests" / "fixtures" / "p0c" / "contracts" / "prototype_v2.json"


def _left_turn_candidate(path: Path) -> Path:
    candidate = json.loads(PROTOTYPE.read_text(encoding="utf-8"))
    candidate["scenario_id"] = "metadrive_v2_declared_left_turn_route"
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
    candidate["constraints"]["max_steps"] = 140
    candidate["constraints"]["duration_s"] = 14.0
    candidate["constraints"]["target_outcome"] = "safe_pass"
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


def _run_real_metadrive(candidate_path: Path, runtime_path: Path) -> dict[str, object]:
    scenario = instantiate_scenario(load_scenario(candidate_path))
    bundle = ScenarioCompiler().compile(scenario)
    assert bundle.report.executable is True
    assert bundle.execution_plan is not None
    plan_path = runtime_path / "execution_plan.json"
    artifacts_path = runtime_path / "artifacts.json"
    plan_path.write_bytes(canonical_bytes(bundle.execution_plan.to_dict()))
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
    return json.loads(artifacts_path.read_text(encoding="utf-8"))


def test_real_metadrive_follows_the_declared_left_turn_route(tmp_path: Path) -> None:
    candidate = _left_turn_candidate(tmp_path / "candidate.json")
    artifacts = _run_real_metadrive(candidate, tmp_path)
    trajectory = artifacts["trajectory.json"]
    ego_points = [
        point for point in trajectory if point["participant_id"] == "ego"
    ]
    visited_lane_ids = list(
        dict.fromkeys(point["lane_id"] for point in ego_points)
    )

    assert visited_lane_ids == ["ego-inbound", "ego-left-turn", "ego-exit"]
    assert all(point["wrong_route"] is False for point in ego_points)
    assert ego_points[-1]["route_completed"] is True
    assert ego_points[-1]["lane_id"] == "ego-exit"
    assert abs((ego_points[-1]["heading_deg"] - 90.0 + 180.0) % 360.0 - 180.0) <= 5.0

    ego_actions = [
        action
        for action in artifacts["actions.json"]
        if action["participant_id"] == "ego"
    ]
    override = next(action for action in ego_actions if action["tick"] == 3)
    assert override["source"] == "scenario_override"
    assert override["final_action"]["steering"] == 0.0
    assert any(
        action["source"] == "policy"
        and abs(action["final_action"]["steering"]) > 0.01
        for action in ego_actions
    )
    assert artifacts["metrics.json"]["termination_reason"] == (
        "success_predicates_satisfied"
    )
