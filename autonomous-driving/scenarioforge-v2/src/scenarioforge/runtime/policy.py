from __future__ import annotations

import math
from typing import Any, Mapping

from scenarioforge.policies.defensive import planned_defensive_throttle_brake
from scenarioforge.policies.registry import (
    BOUND_EXECUTION_SCHEMA_VERSION,
    CANDIDATE_POLICY_ID,
    validate_bound_policy_execution,
)


def apply_declared_route_control(
    actions: Mapping[str, list[float]],
    records: list[dict[str, Any]],
    control_by_participant: Mapping[str, list[float]],
) -> tuple[dict[str, list[float]], list[dict[str, Any]]]:
    """Overlay safe route control without defeating same-tick scenario events."""
    adjusted_actions = {
        participant_id: list(action)
        for participant_id, action in actions.items()
    }
    adjusted_records: list[dict[str, Any]] = []
    for record in records:
        participant_id = str(record["participant_id"])
        adjusted = {
            **record,
            "policy_action": dict(record["policy_action"]),
            "final_action": dict(record["final_action"]),
        }
        if participant_id in control_by_participant:
            route_control = control_by_participant[participant_id]
            steering = float(route_control[0])
            throttle_brake = min(
                float(adjusted["policy_action"]["throttle_brake"]),
                float(route_control[1]),
            )
            if not math.isfinite(steering) or not math.isfinite(throttle_brake):
                raise RuntimeError(
                    f"non-finite route control for {participant_id}: "
                    f"{steering}, {throttle_brake}"
                )
            steering = max(-1.0, min(1.0, steering))
            throttle_brake = max(-1.0, min(1.0, throttle_brake))
            adjusted["policy_action"]["steering"] = steering
            adjusted["policy_action"]["throttle_brake"] = throttle_brake
            if adjusted["source"] == "policy":
                adjusted["final_action"]["steering"] = steering
                adjusted["final_action"]["throttle_brake"] = throttle_brake
                adjusted_actions[participant_id][0] = steering
                adjusted_actions[participant_id][1] = throttle_brake
        adjusted_records.append(adjusted)
    return adjusted_actions, adjusted_records


def resolve_tick_actions(
    plan: Mapping[str, Any],
    tick: int,
) -> tuple[dict[str, list[float]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Resolve deterministic policy actions and scenario overrides for tick N."""
    if plan["schema_version"] == "scenarioforge.execution-plan/v2":
        return _resolve_v2_tick_actions(plan, tick)
    policy_action = {
        "steering": float(plan["policy"]["config"]["steering"]),
        "throttle_brake": float(plan["policy"]["config"]["throttle_brake"]),
    }
    final_by_participant = {
        participant["id"]: dict(policy_action) for participant in plan["participants"]
    }
    source_by_participant = {
        participant["id"]: "policy" for participant in plan["participants"]
    }
    fired: list[dict[str, Any]] = []
    for event in plan["events"]:
        if event["trigger"]["kind"] != "tick" or int(event["trigger"]["tick"]) != tick:
            continue
        participant_id = event["participant_id"]
        final_by_participant[participant_id] = {
            "steering": policy_action["steering"],
            "throttle_brake": -float(event["action"]["brake"]),
        }
        source_by_participant[participant_id] = "scenario_override"
        fired.append(
            {
                "schema_version": "scenarioforge.event/v1",
                "event_id": event["id"],
                "type": "trigger_fired",
                "participant_id": participant_id,
                "trigger_tick": tick,
                "effect_state_tick": tick + int(plan["tick_contract"]["event_effect_offset"]),
                "priority_contract": "scenarioforge.trigger-priority/v1",
                "action": dict(final_by_participant[participant_id]),
            }
        )

    records: list[dict[str, Any]] = []
    actions: dict[str, list[float]] = {}
    for participant in plan["participants"]:
        participant_id = participant["id"]
        final = final_by_participant[participant_id]
        records.append(
            {
                "schema_version": "scenarioforge.action/v1",
                "tick": tick,
                "participant_id": participant_id,
                "policy_action": dict(policy_action),
                "final_action": dict(final),
                "source": source_by_participant[participant_id],
            }
        )
        actions[participant_id] = [final["steering"], final["throttle_brake"]]
    return actions, records, fired


def _resolve_v2_tick_actions(
    plan: Mapping[str, Any],
    tick: int,
) -> tuple[dict[str, list[float]], list[dict[str, Any]], list[dict[str, Any]]]:
    policy = plan["policy"]
    binding = None
    if policy.get("schema_version") == BOUND_EXECUTION_SCHEMA_VERSION:
        baseline_policy, binding = validate_bound_policy_execution(policy)
    else:
        baseline_policy = policy
    config = baseline_policy["config"]
    default_action = {
        "steering": float(config["default_action"]["steering"]),
        "throttle_brake": float(config["default_action"]["throttle_brake"]),
    }
    policy_by_participant = {
        str(participant["id"]): dict(default_action)
        for participant in plan["participants"]
    }
    for configured in config["participant_actions"]:
        participant_id = str(configured["participant_id"])
        if participant_id in policy_by_participant:
            policy_by_participant[participant_id] = {
                "steering": float(configured["steering"]),
                "throttle_brake": float(configured["throttle_brake"]),
            }

    if binding is not None and binding.id == CANDIDATE_POLICY_ID:
        for participant in plan["participants"]:
            participant_id = str(participant["id"])
            action = policy_by_participant[participant_id]
            action["throttle_brake"] = planned_defensive_throttle_brake(
                plan,
                tick,
                participant_id,
                float(action["throttle_brake"]),
            )

    final_by_participant = {
        participant_id: dict(action)
        for participant_id, action in policy_by_participant.items()
    }
    source_by_participant = {
        participant_id: "policy" for participant_id in policy_by_participant
    }
    fired: list[dict[str, Any]] = []
    for event in plan["events"]:
        trigger = event["trigger"]
        trigger_tick = int(trigger["tick"])
        duration_ticks = int(event.get("duration_ticks", 1))
        if (
            trigger["kind"] != "tick"
            or tick < trigger_tick
            or tick >= trigger_tick + duration_ticks
        ):
            continue
        participant_id = str(event["participant_id"])
        action = event["action"]
        final_by_participant[participant_id] = {
            "steering": float(action["steering"]),
            "throttle_brake": float(action["throttle_brake"]),
        }
        source_by_participant[participant_id] = "scenario_override"
        if tick == trigger_tick:
            fired.append(
                {
                    "schema_version": "scenarioforge.event/v2",
                    "event_id": str(event["id"]),
                    "sequence": int(event["sequence"]),
                    "type": "trigger_fired",
                    "participant_id": participant_id,
                    "trigger_tick": tick,
                    "effect_state_tick": tick
                    + int(plan["tick_contract"]["event_effect_offset"]),
                    "priority_contract": "scenarioforge.trigger-priority/v2",
                    "action": dict(final_by_participant[participant_id]),
                }
            )

    records: list[dict[str, Any]] = []
    actions: dict[str, list[float]] = {}
    for participant in plan["participants"]:
        participant_id = str(participant["id"])
        final = final_by_participant[participant_id]
        records.append(
            {
                "schema_version": "scenarioforge.action/v2",
                "tick": tick,
                "participant_id": participant_id,
                "route_id": str(participant["route"]["id"]),
                "policy_action": dict(policy_by_participant[participant_id]),
                "final_action": dict(final),
                "source": source_by_participant[participant_id],
            }
        )
        actions[participant_id] = [final["steering"], final["throttle_brake"]]
    return actions, records, fired
