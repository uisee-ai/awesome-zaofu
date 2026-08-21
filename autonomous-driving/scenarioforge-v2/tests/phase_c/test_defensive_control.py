from __future__ import annotations

from scenarioforge.policies import (
    DefensiveControlState,
    DefensiveObservation,
    decide_defensive_control,
    trusted_policy_pair,
)
from scenarioforge.policies.registry import bind_policy_execution
from scenarioforge.runtime.policy import apply_declared_route_control, resolve_tick_actions


def _baseline_policy() -> dict[str, object]:
    return {
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
                {"participant_id": "ego", "steering": 0.0, "throttle_brake": 0.0},
                {"participant_id": "lead", "steering": 0.0, "throttle_brake": 0.0},
            ],
        },
    }


def _plan(binding_role: str) -> dict[str, object]:
    baseline_policy = _baseline_policy()
    bindings = trusted_policy_pair(baseline_policy["config"])
    binding = bindings[0 if binding_role == "baseline" else 1]
    return {
        "schema_version": "scenarioforge.execution-plan/v2",
        "simulation": {
            "physics_world_step_size_s": 0.02,
            "decision_repeat": 5,
        },
        "participants": [
            {
                "id": "ego",
                "role": "ego",
                "spawn": {
                    "lane_id": "lane-1",
                    "longitudinal_m": 10.0,
                    "speed_mps": 20.0,
                },
                "route": {"id": "ego-route"},
            },
            {
                "id": "lead",
                "role": "social",
                "spawn": {
                    "lane_id": "lane-1",
                    "longitudinal_m": 35.0,
                    "speed_mps": 20.0,
                },
                "route": {"id": "lead-route"},
            },
        ],
        "events": [
            {
                "id": "lead-brake",
                "sequence": 0,
                "participant_id": "lead",
                "trigger": {"kind": "tick", "tick": 30},
                "duration_ticks": 4,
                "action": {"steering": 0.0, "throttle_brake": -1.0},
            },
            {
                "id": "ego-brake",
                "sequence": 1,
                "participant_id": "ego",
                "trigger": {"kind": "tick", "tick": 35},
                "duration_ticks": 4,
                "action": {"steering": 0.0, "throttle_brake": -0.7},
            },
        ],
        "tick_contract": {"event_effect_offset": 1},
        "policy": bind_policy_execution(baseline_policy, binding),
    }


def test_defensive_controller_brakes_for_gap_ttc_or_merge_and_releases_after_hysteresis() -> None:
    initial = DefensiveControlState.initial()
    safe = DefensiveObservation(
        elapsed_s=0.0,
        ego_speed_mps=10.0,
        lead_gap_m=50.0,
        lead_speed_mps=10.0,
        merge_yield_required=False,
    )
    decision, state = decide_defensive_control(safe, initial)
    assert decision.to_dict() == {
        "schema_version": "scenarioforge.defensive-decision/v1",
        "nominal_target_speed_scale": 1.0,
        "steering_override": None,
        "throttle_brake": 0.0,
        "reason": "nominal",
    }
    assert state == initial

    gap_hazard = DefensiveObservation(
        elapsed_s=1.0,
        ego_speed_mps=10.0,
        lead_gap_m=4.0,
        lead_speed_mps=10.0,
        merge_yield_required=False,
    )
    gap_decision, braking = decide_defensive_control(gap_hazard, state)
    assert gap_decision.reason == "minimum_gap"
    assert -1.0 <= gap_decision.throttle_brake < 0.0
    assert gap_decision.steering_override is None

    ttc_hazard = DefensiveObservation(
        elapsed_s=2.0,
        ego_speed_mps=20.0,
        lead_gap_m=20.0,
        lead_speed_mps=10.0,
        merge_yield_required=False,
    )
    ttc_decision, _ = decide_defensive_control(ttc_hazard, braking)
    assert ttc_decision.reason == "time_headway_and_ttc"
    assert ttc_decision.throttle_brake < 0.0

    merge_hazard = DefensiveObservation(
        elapsed_s=3.0,
        ego_speed_mps=10.0,
        lead_gap_m=None,
        lead_speed_mps=None,
        merge_yield_required=True,
    )
    merge_decision, braking = decide_defensive_control(merge_hazard, braking)
    assert merge_decision.reason == "merge_yield"
    assert merge_decision.throttle_brake < 0.0

    just_safe = DefensiveObservation(
        elapsed_s=3.2,
        ego_speed_mps=10.0,
        lead_gap_m=50.0,
        lead_speed_mps=10.0,
        merge_yield_required=False,
    )
    held, braking = decide_defensive_control(just_safe, braking)
    assert held.reason == "release_hysteresis"
    assert held.throttle_brake < 0.0
    released, released_state = decide_defensive_control(
        DefensiveObservation(
            elapsed_s=3.8,
            ego_speed_mps=10.0,
            lead_gap_m=50.0,
            lead_speed_mps=10.0,
            merge_yield_required=False,
        ),
        braking,
    )
    assert released.reason == "nominal"
    assert released.throttle_brake == 0.0
    assert released_state == DefensiveControlState.initial()


def test_candidate_brakes_before_declared_hazard_without_changing_route_or_event_priority() -> None:
    baseline_plan = _plan("baseline")
    candidate_plan = _plan("candidate")

    baseline_actions, baseline_records, _ = resolve_tick_actions(baseline_plan, 29)
    candidate_actions, candidate_records, _ = resolve_tick_actions(candidate_plan, 29)
    assert baseline_actions["ego"] == [0.0, 0.0]
    assert candidate_actions["ego"][0] == 0.0
    assert candidate_actions["ego"][1] < 0.0
    assert candidate_records[0]["route_id"] == baseline_records[0]["route_id"]

    adjusted, adjusted_records = apply_declared_route_control(
        candidate_actions,
        candidate_records,
        {"ego": [0.35, 0.4], "lead": [0.0, 0.4]},
    )
    assert adjusted["ego"][0] == 0.35
    assert adjusted["ego"][1] == candidate_actions["ego"][1]
    assert adjusted_records[0]["route_id"] == "ego-route"

    event_actions, event_records, fired = resolve_tick_actions(candidate_plan, 35)
    ego_record = next(item for item in event_records if item["participant_id"] == "ego")
    assert event_actions["ego"] == [0.0, -0.7]
    assert ego_record["source"] == "scenario_override"
    assert [item["event_id"] for item in fired] == ["ego-brake"]
