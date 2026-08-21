from __future__ import annotations

import json
from pathlib import Path

from scenarioforge.core import (
    CompilationStatus,
    ScenarioCompiler,
    instantiate_scenario,
    load_scenario,
)
from scenarioforge.runtime.adapter import MetaDriveAdapter
from scenarioforge.runtime.policy import resolve_tick_actions


ROOT = Path(__file__).resolve().parents[4]
SCENARIO = ROOT / "examples" / "p0c" / "highway_merge.json"

EXPECTED_TOPOLOGY = {
    "schema_version": "scenarioforge.topology/v2",
    "topology_kind": "ramp_merge",
    "map_block_sequence": "S",
    "lane_width_m": 3.5,
    "coordinate_system": "right-handed-x-forward-y-left",
    "units": {
        "distance": "m",
        "speed": "m/s",
        "heading": "deg",
        "time": "tick",
    },
    "lanes": [
        {
            "id": "ramp-merge",
            "road_id": "entrance-ramp",
            "engine_lane_index": {
                "start_node": ">>",
                "end_node": ">>>",
                "lane_index": 0,
            },
            "kind": "ramp",
            "length_m": 180.0,
            "predecessor_lane_ids": [],
            "successor_lane_ids": ["merged-lane"],
        },
        {
            "id": "merged-lane",
            "road_id": "mainline",
            "engine_lane_index": {
                "start_node": ">>",
                "end_node": ">>>",
                "lane_index": 1,
            },
            "kind": "merge",
            "length_m": 180.0,
            "predecessor_lane_ids": ["ramp-merge"],
            "successor_lane_ids": [],
        },
        {
            "id": "mainline-wrong-lane",
            "road_id": "opposing-mainline",
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
    ],
    "conflict_zones": [
        {
            "id": "ramp-conflict",
            "lane_ids": ["ramp-merge", "merged-lane"],
            "start_m": 35.0,
            "end_m": 80.0,
        }
    ],
}

EXPECTED_PARTICIPANTS = [
    {
        "id": "ego",
        "role": "ego",
        "actor_type": "vehicle",
        "spawn": {
            "schema_version": "scenarioforge.actor-spawn/v2",
            "lane_id": "ramp-merge",
            "longitudinal_m": 15.0,
            "lateral_m": 0.0,
            "speed_mps": 20.0,
            "heading_deg": 0.0,
        },
        "route": {
            "schema_version": "scenarioforge.route/v2",
            "id": "ego-ramp-merge",
            "lane_ids": ["ramp-merge", "merged-lane"],
            "goal": {"lane_id": "merged-lane", "longitudinal_m": 60.0},
        },
    },
    {
        "id": "front",
        "role": "social",
        "actor_type": "vehicle",
        "spawn": {
            "schema_version": "scenarioforge.actor-spawn/v2",
            "lane_id": "merged-lane",
            "longitudinal_m": 100.0,
            "lateral_m": 0.0,
            "speed_mps": 23.0,
            "heading_deg": 0.0,
        },
        "route": {
            "schema_version": "scenarioforge.route/v2",
            "id": "front-mainline",
            "lane_ids": ["merged-lane"],
            "goal": {"lane_id": "merged-lane", "longitudinal_m": 160.0},
        },
    },
    {
        "id": "rear",
        "role": "social",
        "actor_type": "vehicle",
        "spawn": {
            "schema_version": "scenarioforge.actor-spawn/v2",
            "lane_id": "merged-lane",
            "longitudinal_m": 0.0,
            "lateral_m": 0.0,
            "speed_mps": 18.0,
            "heading_deg": 0.0,
        },
        "route": {
            "schema_version": "scenarioforge.route/v2",
            "id": "rear-mainline",
            "lane_ids": ["merged-lane"],
            "goal": {"lane_id": "merged-lane", "longitudinal_m": 160.0},
        },
    },
]

EXPECTED_EVENTS = [
    {
        "id": "gap-selected",
        "sequence": 0,
        "type": "control_override",
        "participant_id": "ego",
        "trigger": {
            "schema_version": "scenarioforge.trigger/v2",
            "kind": "tick",
            "tick": 5,
        },
        "action": {
            "schema_version": "scenarioforge.control-action/v2",
            "steering": -1.0,
            "throttle_brake": 0.1,
        },
    },
    {
        "id": "gap-merge-control-2",
        "sequence": 1,
        "type": "control_override",
        "participant_id": "ego",
        "trigger": {
            "schema_version": "scenarioforge.trigger/v2",
            "kind": "tick",
            "tick": 6,
        },
        "action": {
            "schema_version": "scenarioforge.control-action/v2",
            "steering": -1.0,
            "throttle_brake": 0.1,
        },
    },
    {
        "id": "gap-merge-control-3",
        "sequence": 2,
        "type": "control_override",
        "participant_id": "ego",
        "trigger": {
            "schema_version": "scenarioforge.trigger/v2",
            "kind": "tick",
            "tick": 7,
        },
        "action": {
            "schema_version": "scenarioforge.control-action/v2",
            "steering": -1.0,
            "throttle_brake": 0.1,
        },
    },
    {
        "id": "gap-merge-control-4",
        "sequence": 3,
        "type": "control_override",
        "participant_id": "ego",
        "trigger": {
            "schema_version": "scenarioforge.trigger/v2",
            "kind": "tick",
            "tick": 8,
        },
        "action": {
            "schema_version": "scenarioforge.control-action/v2",
            "steering": -1.0,
            "throttle_brake": 0.1,
        },
    },
    {
        "id": "gap-merge-control-5",
        "sequence": 4,
        "type": "control_override",
        "participant_id": "ego",
        "trigger": {
            "schema_version": "scenarioforge.trigger/v2",
            "kind": "tick",
            "tick": 9,
        },
        "action": {
            "schema_version": "scenarioforge.control-action/v2",
            "steering": -1.0,
            "throttle_brake": 0.1,
        },
    },
    {
        "id": "gap-merge-control-6",
        "sequence": 5,
        "type": "control_override",
        "participant_id": "ego",
        "trigger": {
            "schema_version": "scenarioforge.trigger/v2",
            "kind": "tick",
            "tick": 10,
        },
        "action": {
            "schema_version": "scenarioforge.control-action/v2",
            "steering": -1.0,
            "throttle_brake": 0.1,
        },
    },
    {
        "id": "gap-merge-control-7",
        "sequence": 6,
        "type": "control_override",
        "participant_id": "ego",
        "trigger": {
            "schema_version": "scenarioforge.trigger/v2",
            "kind": "tick",
            "tick": 11,
        },
        "action": {
            "schema_version": "scenarioforge.control-action/v2",
            "steering": -1.0,
            "throttle_brake": 0.1,
        },
    },
]

EXPECTED_FAILURE_PREDICATES = [
    {
        "id": "collision-observed",
        "kind": "collision",
        "participant_ids": ["ego", "front", "rear"],
        "lane_ids": [],
    },
    {
        "id": "ego-route-departure",
        "kind": "boundary_violation",
        "participant_ids": ["ego"],
        "lane_ids": [],
    },
    {
        "id": "wrong-mainline-lane-entered",
        "kind": "wrong_lane",
        "participant_ids": ["ego"],
        "lane_ids": ["mainline-wrong-lane"],
    },
    {
        "id": "merge-timeout",
        "kind": "timeout",
        "participant_ids": ["ego"],
        "lane_ids": [],
    },
]

EXPECTED_METRICS = [
    {
        "definition_id": "scenarioforge.metric.collision/v2",
        "metric": "collision",
        "unit": "boolean",
        "applies_to": {
            "participant_ids": ["ego", "front", "rear"],
            "topology_kinds": ["ramp_merge"],
        },
        "threshold": None,
        "null_semantics": "not_applicable",
        "evidence_field": "collision",
    },
    {
        "definition_id": "scenarioforge.metric.hard-braking/v2",
        "metric": "hard_braking",
        "unit": "m/s^2",
        "applies_to": {
            "participant_ids": ["ego"],
            "topology_kinds": ["ramp_merge"],
        },
        "threshold": None,
        "null_semantics": "threshold_pending_calibration",
        "evidence_field": "minimum_acceleration_mps2",
    },
    {
        "definition_id": "scenarioforge.metric.minimum-ttc/v2",
        "metric": "minimum_ttc",
        "unit": "s",
        "applies_to": {
            "participant_ids": ["ego", "front", "rear"],
            "topology_kinds": ["ramp_merge"],
        },
        "threshold": None,
        "null_semantics": "no_closing_pair",
        "evidence_field": "min_ttc_s",
    },
    {
        "definition_id": "scenarioforge.metric.completion-time/v2",
        "metric": "completion_time",
        "unit": "s",
        "applies_to": {
            "participant_ids": ["ego"],
            "topology_kinds": ["ramp_merge"],
        },
        "threshold": None,
        "null_semantics": "execution_incomplete",
        "evidence_field": "completion_time_s",
    },
    {
        "definition_id": "scenarioforge.metric.termination-reason/v2",
        "metric": "termination_reason",
        "unit": "category",
        "applies_to": {
            "participant_ids": [],
            "topology_kinds": ["ramp_merge"],
        },
        "threshold": None,
        "null_semantics": "never_null_for_terminal_run",
        "evidence_field": "termination_reason",
    },
]

EXPECTED_POLICY = {
    "schema_version": "scenarioforge.deterministic-policy/v2",
    "id": "scenarioforge.deterministic-control",
    "version": "2.0.0",
    "determinism": {
        "fixed_seed_required": True,
        "decision_order": "participant_order",
        "floating_point_contract": "backend_bound",
    },
    "config": {
        "default_action": {"steering": 0.0, "throttle_brake": 0.0},
        "participant_actions": [
            {"participant_id": "ego", "steering": 0.0, "throttle_brake": 0.1},
            {"participant_id": "front", "steering": 0.0, "throttle_brake": 0.05},
            {"participant_id": "rear", "steering": 0.0, "throttle_brake": 0.05},
        ],
    },
}

EXPECTED_CAPABILITIES = [
    "topology.versioned.v2",
    "lane.stable-id.v2",
    "route.stable-id.v2",
    "actor.spawn.v2",
    "trigger.tick.v2",
    "policy.deterministic.v2",
    "event.ordered.v2",
    "metric.definition.v2",
    "terminal.dual-axis.v2",
]


def _expected_scenario() -> dict[str, object]:
    return {
        "schema_version": "scenarioforge.scenario/v2",
        "scenario_id": "highway_merge",
        "seed": 37,
        "road": EXPECTED_TOPOLOGY,
        "participants": EXPECTED_PARTICIPANTS,
        "parameters": {
            "initial_gap_m": 20.0,
            "vehicle_speed_mps": 21.0,
            "brake_tick": 4,
            "brake_intensity": 0.7,
        },
        "events": EXPECTED_EVENTS,
        "constraints": {
            "schema_version": "scenarioforge.outcome-contract/v2",
            "max_steps": 120,
            "duration_s": 12.0,
            "collision_is_failure": True,
            "target_outcome": "safe_pass",
            "success_predicates": [
                {
                    "id": "merge-completed",
                    "kind": "merge_completed",
                    "participant_ids": ["ego"],
                    "lane_ids": ["merged-lane"],
                }
            ],
            "failure_predicates": EXPECTED_FAILURE_PREDICATES,
            "expected_events": [
                "gap-selected",
                "gap-merge-control-2",
                "gap-merge-control-3",
                "gap-merge-control-4",
                "gap-merge-control-5",
                "gap-merge-control-6",
                "gap-merge-control-7",
            ],
            "metric_definitions": EXPECTED_METRICS,
        },
        "policy": EXPECTED_POLICY,
        "required_capabilities": EXPECTED_CAPABILITIES,
        "backend_extensions": {
            "schema_version": "scenarioforge.backend-extensions/v2",
            "extensions": {},
        },
    }


def test_highway_merge_fixture_is_the_exact_owner_and_calibration_contract() -> None:
    observed = json.loads(SCENARIO.read_text(encoding="utf-8"))

    assert observed == _expected_scenario()


def test_highway_merge_compiles_exactly_and_projects_every_stable_lane() -> None:
    scenario = instantiate_scenario(load_scenario(SCENARIO))
    bundle = ScenarioCompiler().compile(scenario)

    assert bundle.report.overall_status is CompilationStatus.EXACT
    assert bundle.report.diagnostics == ()
    assert bundle.execution_plan is not None
    plan = bundle.execution_plan.to_dict()
    assert plan["simulation"]["topology"] == EXPECTED_TOPOLOGY
    assert plan["participants"] == EXPECTED_PARTICIPANTS
    assert plan["events"] == EXPECTED_EVENTS
    assert plan["constraints"] == _expected_scenario()["constraints"]
    assert plan["policy"] == EXPECTED_POLICY
    assert MetaDriveAdapter(plan)._config()["map_config"] == {
        "type": "block_sequence",
        "config": "S",
        "lane_width": 3.5,
        "lane_num": 2,
        "exit_length": 190.0,
        "start_position": [0, 0],
    }


def test_gap_selection_controls_only_ego_for_the_exact_frozen_tick_window() -> None:
    scenario = instantiate_scenario(load_scenario(SCENARIO))
    plan_model = ScenarioCompiler().compile(scenario).execution_plan
    assert plan_model is not None
    plan = plan_model.to_dict()

    before, before_records, before_events = resolve_tick_actions(plan, 4)
    after, after_records, after_events = resolve_tick_actions(plan, 12)

    assert before == {
        "ego": [0.0, 0.1],
        "front": [0.0, 0.05],
        "rear": [0.0, 0.05],
    }
    assert [item["source"] for item in before_records] == [
        "policy",
        "policy",
        "policy",
    ]
    assert before_events == []
    observed_events = []
    for tick, expected in enumerate(EXPECTED_EVENTS, start=5):
        selected, selected_records, selected_events = resolve_tick_actions(plan, tick)

        assert selected == {
            "ego": [-1.0, 0.1],
            "front": [0.0, 0.05],
            "rear": [0.0, 0.05],
        }
        assert [item["source"] for item in selected_records] == [
            "scenario_override",
            "policy",
            "policy",
        ]
        assert selected_events == [
            {
                "schema_version": "scenarioforge.event/v2",
                "event_id": expected["id"],
                "sequence": expected["sequence"],
                "type": "trigger_fired",
                "participant_id": "ego",
                "trigger_tick": tick,
                "effect_state_tick": tick + 1,
                "priority_contract": "scenarioforge.trigger-priority/v2",
                "action": {"steering": -1.0, "throttle_brake": 0.1},
            }
        ]
        observed_events.extend(selected_events)

    assert [item["event_id"] for item in observed_events] == [
        "gap-selected",
        "gap-merge-control-2",
        "gap-merge-control-3",
        "gap-merge-control-4",
        "gap-merge-control-5",
        "gap-merge-control-6",
        "gap-merge-control-7",
    ]
    assert after == {
        "ego": [0.0, 0.1],
        "front": [0.0, 0.05],
        "rear": [0.0, 0.05],
    }
    assert [item["source"] for item in after_records] == [
        "policy",
        "policy",
        "policy",
    ]
    assert after_events == []
