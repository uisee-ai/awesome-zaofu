from __future__ import annotations

from typing import Any, Mapping

from scenarioforge.core.canonical import freeze_json, thaw_json
from scenarioforge.core.models import ScenarioInstance

from .contracts import SeedContract


def _apply_parameter(
    name: str,
    value: object,
    parameters: dict[str, Any],
    participants: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> None:
    parameters[name] = value
    if name == "initial_gap_m":
        ego = next(item for item in participants if item["id"] == "ego")
        lead = next(item for item in participants if item["id"] == "lead")
        lead["initial"]["longitudinal_m"] = float(ego["initial"]["longitudinal_m"]) + float(value)
    elif name == "vehicle_speed_mps":
        for participant in participants:
            participant["initial"]["speed_mps"] = float(value)
    elif name == "brake_tick":
        for event in events:
            if event["type"] == "vehicle_brake":
                event["trigger"]["tick"] = int(value)
    elif name == "brake_intensity":
        for event in events:
            if event["type"] == "vehicle_brake":
                event["action"]["brake"] = float(value)
    else:
        raise ValueError(f"unsupported resolved parameter: {name}")


def rebuild_instance(
    instance: ScenarioInstance,
    *,
    seed: int | None = None,
    parameters: Mapping[str, Any] | None = None,
    participants: list[dict[str, Any]] | None = None,
    events: list[dict[str, Any]] | None = None,
    required_capabilities: tuple[str, ...] | None = None,
) -> ScenarioInstance:
    return ScenarioInstance(
        schema_version=instance.schema_version,
        scenario_id=instance.scenario_id,
        source_schema_version=instance.source_schema_version,
        source_spec_digest=instance.source_spec_digest,
        seed=instance.seed if seed is None else seed,
        road=freeze_json(thaw_json(instance.road)),
        participants=freeze_json(
            thaw_json(instance.participants) if participants is None else participants
        ),
        parameters=freeze_json(
            thaw_json(instance.parameters) if parameters is None else parameters
        ),
        events=freeze_json(thaw_json(instance.events) if events is None else events),
        constraints=freeze_json(thaw_json(instance.constraints)),
        policy=freeze_json(thaw_json(instance.policy)),
        required_capabilities=(
            instance.required_capabilities
            if required_capabilities is None
            else required_capabilities
        ),
        backend_extensions=freeze_json(thaw_json(instance.backend_extensions)),
    )


def resolve_seeded_instance(
    instance: ScenarioInstance,
    contract: SeedContract,
    *,
    seed: int,
) -> ScenarioInstance:
    if not 0 <= seed <= 2_147_483_647:
        raise ValueError("seed is outside the P0-A contract")
    parameters = thaw_json(instance.parameters)
    participants = thaw_json(instance.participants)
    events = thaw_json(instance.events)
    assert isinstance(parameters, dict)
    assert isinstance(participants, list)
    assert isinstance(events, list)
    for field_index, field in enumerate(contract.fields):
        choice_index = (seed + field_index) % len(field.choices)
        selected = thaw_json(field.choices[choice_index])
        parameter_name = field.path.removeprefix("$.parameters.")
        _apply_parameter(parameter_name, selected, parameters, participants, events)
    return rebuild_instance(
        instance,
        seed=seed,
        parameters=parameters,
        participants=participants,
        events=events,
    )


def set_initial_gap(instance: ScenarioInstance, initial_gap_m: float) -> ScenarioInstance:
    parameters = thaw_json(instance.parameters)
    participants = thaw_json(instance.participants)
    events = thaw_json(instance.events)
    assert isinstance(parameters, dict)
    assert isinstance(participants, list)
    assert isinstance(events, list)
    _apply_parameter(
        "initial_gap_m",
        initial_gap_m,
        parameters,
        participants,
        events,
    )
    return rebuild_instance(
        instance,
        parameters=parameters,
        participants=participants,
        events=events,
    )
