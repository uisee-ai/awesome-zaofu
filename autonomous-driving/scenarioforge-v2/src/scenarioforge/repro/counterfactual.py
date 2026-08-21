from __future__ import annotations

from typing import Any, Mapping

from scenarioforge.core.canonical import freeze_json, thaw_json
from scenarioforge.core.models import ScenarioInstance

from .contracts import CounterfactualResult, CounterfactualSpec, freeze_mapping
from .seed import rebuild_instance, set_initial_gap


def apply_counterfactual(
    instance: ScenarioInstance,
    counterfactual: CounterfactualSpec,
) -> ScenarioInstance:
    if counterfactual.kind == "increase_initial_gap":
        assert counterfactual.initial_gap_m is not None
        current_gap = float(instance.parameters["initial_gap_m"])
        if counterfactual.initial_gap_m <= current_gap:
            raise ValueError("increase_initial_gap must increase the resolved initial gap")
        return set_initial_gap(instance, counterfactual.initial_gap_m)

    if counterfactual.kind == "cancel_braking":
        parameters = thaw_json(instance.parameters)
        participants = thaw_json(instance.participants)
        events = thaw_json(instance.events)
        assert isinstance(parameters, dict)
        assert isinstance(participants, list)
        assert isinstance(events, list)
        parameters["brake_intensity"] = 0.0
        remaining_events = [event for event in events if event["type"] != "vehicle_brake"]
        capabilities = tuple(
            item for item in instance.required_capabilities if item != "event.tick-brake"
        )
        return rebuild_instance(
            instance,
            parameters=parameters,
            participants=participants,
            events=remaining_events,
            required_capabilities=capabilities,
        )

    raise ValueError(f"unsupported counterfactual kind: {counterfactual.kind}")


def _key_events(outputs: Mapping[str, Any]) -> list[dict[str, Any]]:
    events = outputs.get("events.json")
    if not isinstance(events, list):
        raise ValueError("counterfactual outputs do not contain an event list")
    signature = [
        {
            "event_id": event["event_id"],
            "type": event["type"],
            "participant_id": event["participant_id"],
            "trigger_tick": event["trigger_tick"],
            "effect_state_tick": event["effect_state_tick"],
        }
        for event in events
    ]
    metrics = outputs.get("metrics.json")
    if not isinstance(metrics, dict):
        raise ValueError("counterfactual outputs do not contain metrics")
    minimum_ttc = metrics.get("min_ttc_s")
    if minimum_ttc is not None and float(minimum_ttc) < 2.0:
        completed_steps = int(metrics["completed_steps"])
        signature.append(
            {
                "event_id": "minimum-ttc-below-2s",
                "type": "minimum_ttc_below_threshold",
                "participant_id": "ego,lead",
                "trigger_tick": completed_steps,
                "effect_state_tick": completed_steps,
            }
        )
    return signature


def _terminal_result(outputs: Mapping[str, Any]) -> dict[str, Any]:
    metrics = outputs.get("metrics.json")
    if not isinstance(metrics, dict):
        raise ValueError("counterfactual outputs do not contain metrics")
    return {
        "terminal_status": metrics["terminal_status"],
        "termination_reason": metrics["termination_reason"],
        "collision": metrics["collision"],
    }


def assess_counterfactual(
    baseline_outputs: Mapping[str, Any],
    variant_outputs: Mapping[str, Any],
    counterfactual: CounterfactualSpec,
) -> CounterfactualResult:
    if counterfactual.expected_change == "key_event":
        baseline = {"key_events": _key_events(baseline_outputs)}
        variant = {"key_events": _key_events(variant_outputs)}
    elif counterfactual.expected_change == "terminal_result":
        baseline = _terminal_result(baseline_outputs)
        variant = _terminal_result(variant_outputs)
    else:
        raise ValueError("unsupported counterfactual expected_change")
    observed_change = baseline != variant
    return CounterfactualResult(
        schema_version="scenarioforge.counterfactual-result/v1",
        counterfactual_id=counterfactual.counterfactual_id,
        kind=counterfactual.kind,
        expected_change=counterfactual.expected_change,
        observed_change=observed_change,
        baseline=freeze_mapping(baseline),
        variant=freeze_mapping(variant),
        passed=observed_change,
    )
