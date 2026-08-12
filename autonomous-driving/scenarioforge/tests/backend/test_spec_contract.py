from __future__ import annotations

import hashlib
import json
from copy import deepcopy

import pytest

from scenarioforge.spec import (
    ScenarioInputError,
    canonical_scenario,
    export_scenario,
    load_scenario,
)

EXPECTED_CANONICAL = (
    b'{"actors":[{"id":"ego","role":"ego"},{"id":"npc-1","role":"traffic"}],'
    b'"environment":{"traffic_density":0.1},'
    b'"map":{"block_sequence":"S","lane_count":2,"lane_width":3.5},'
    b'"name":"canonical-demo","schema_version":"scenarioforge.scenario-spec.v1",'
    b'"tags":["demo"]}'
)


def test_equivalent_json_and_yaml_have_one_rfc8785_identity_and_round_trip(
    scenario_payload: dict[str, object],
) -> None:
    json_source = json.dumps(scenario_payload, indent=2)
    yaml_source = """\
schema_version: scenarioforge.scenario-spec.v1
name: canonical-demo
map:
  lane_width: 3.5
  block_sequence: S
  lane_count: 2
actors:
  - role: ego
    id: ego
  - id: npc-1
    role: traffic
environment:
  traffic_density: 0.10
tags: [demo]
"""

    from_json = load_scenario(json_source, media_type="application/json")
    from_yaml = load_scenario(yaml_source, media_type="application/yaml")

    assert canonical_scenario(from_json).bytes == EXPECTED_CANONICAL
    assert canonical_scenario(from_yaml).bytes == EXPECTED_CANONICAL
    assert canonical_scenario(from_json).digest == hashlib.sha256(EXPECTED_CANONICAL).hexdigest()
    assert canonical_scenario(from_yaml).digest == canonical_scenario(from_json).digest

    json_round_trip = load_scenario(export_scenario(from_json, "json"), "application/json")
    yaml_round_trip = load_scenario(export_scenario(from_json, "yaml"), "application/yaml")
    assert json_round_trip == from_json
    assert yaml_round_trip == from_json


@pytest.mark.parametrize(
    ("source", "media_type", "location"),
    [
        ('{"schema_version":"scenarioforge.scenario-spec.v2"}', "application/json", "schema_version"),
        (
            '{"schema_version":"scenarioforge.scenario-spec.v1","unknown":true}',
            "application/json",
            "unknown",
        ),
        ('{"schema_version":"scenarioforge.scenario-spec.v1","name":NaN}', "application/json", "$"),
        (
            "!!python/object/apply:os.system ['echo unsafe']",
            "application/yaml",
            "$",
        ),
        (
            "schema_version: scenarioforge.scenario-spec.v1\nname: https://evil.invalid/x\n",
            "application/yaml",
            "name",
        ),
        (
            "schema_version: scenarioforge.scenario-spec.v1\nname: ../../etc/passwd\n",
            "application/yaml",
            "name",
        ),
        (
            "schema_version: scenarioforge.scenario-spec.v1\nname: ${HOME}\n",
            "application/yaml",
            "name",
        ),
    ],
)
def test_untrusted_inputs_fail_preflight_with_field_location(
    source: str, media_type: str, location: str
) -> None:
    with pytest.raises(ScenarioInputError) as raised:
        load_scenario(source, media_type)

    assert raised.value.diagnostics
    assert raised.value.diagnostics[0]["location"] == location
    assert raised.value.diagnostics[0]["code"]
    assert raised.value.diagnostics[0]["message"]


def test_yaml_aliases_duplicate_keys_and_oversized_documents_are_rejected(
    scenario_payload: dict[str, object],
) -> None:
    unsafe_documents = [
        "schema_version: &version scenarioforge.scenario-spec.v1\nname: *version\n",
        "schema_version: scenarioforge.scenario-spec.v1\nname: first\nname: second\n",
        json.dumps(scenario_payload) + (" " * 1_048_577),
    ]

    for source in unsafe_documents:
        with pytest.raises(ScenarioInputError) as raised:
            load_scenario(source, "application/yaml")
        assert raised.value.diagnostics[0]["location"] == "$"


def test_exactly_one_ego_and_at_most_eight_actors_are_required(
    scenario_payload: dict[str, object], copied
) -> None:
    no_ego = copied(scenario_payload)
    no_ego["actors"] = [{"id": "npc", "role": "traffic"}]
    too_many = copied(scenario_payload)
    too_many["actors"] = [
        {"id": "ego", "role": "ego"},
        *({"id": f"npc-{index}", "role": "traffic"} for index in range(8)),
    ]

    for payload in (no_ego, too_many):
        with pytest.raises(ScenarioInputError) as raised:
            load_scenario(json.dumps(payload), "application/json")
        assert raised.value.diagnostics[0]["location"] == "actors"


def test_p0_typed_fields_round_trip_without_changing_canonical_identity(
    scenario_payload: dict[str, object],
) -> None:
    payload = deepcopy(scenario_payload)
    payload["actors"][0].update(
        {
            "initial_state": {"lane": 0, "longitudinal": 8.0, "speed": 7.5},
            "goal": {"kind": "route_progress", "minimum_progress": 0.8},
            "behavior": "follow_lead",
        }
    )
    payload["static_obstacles"] = [
        {"id": "barrier-1", "kind": "barrier", "lane": 1, "longitudinal": 35.0, "length": 2.0}
    ]
    payload["event_triggers"] = [
        {"id": "slow-traffic", "kind": "at_distance", "distance": 25.0, "action": "set_speed_limit"}
    ]
    payload["safety"] = {"max_speed": 20.0, "minimum_headway": 1.5, "collision_free": True}

    scenario = load_scenario(json.dumps(payload), "application/json")
    reloaded = load_scenario(export_scenario(scenario, "yaml"), "application/yaml")

    assert reloaded == scenario
    assert canonical_scenario(reloaded) == canonical_scenario(scenario)


@pytest.mark.parametrize(
    ("mutation", "location"),
    [
        ({"behavior": "python_plugin"}, "actors.0.behavior"),
        ({"initial_state": {"lane": 8, "longitudinal": 0.0, "speed": 1.0}}, "actors.0.initial_state.lane"),
        ({"goal": {"kind": "route_progress", "minimum_progress": 1.5}}, "actors.0.goal.minimum_progress"),
    ],
)
def test_malformed_p0_actor_fields_report_precise_locations(
    scenario_payload: dict[str, object], mutation: dict[str, object], location: str
) -> None:
    payload = deepcopy(scenario_payload)
    payload["actors"][0].update(mutation)

    with pytest.raises(ScenarioInputError) as raised:
        load_scenario(json.dumps(payload), "application/json")

    assert raised.value.diagnostics[0]["location"] == location


@pytest.mark.parametrize(
    ("field", "value", "location"),
    [
        ("static_obstacles", [{"id": "../../escape", "kind": "barrier", "lane": 0, "longitudinal": 3.0, "length": 1.0}], "static_obstacles.0.id"),
        ("event_triggers", [{"id": "trigger", "kind": "at_time", "seconds": 1.0, "action": "https://unsafe.invalid"}], "event_triggers.0.action"),
        ("safety", {"max_speed": 20.0, "minimum_headway": 1.0, "collision_free": True, "plugin": "x"}, "safety.plugin"),
    ],
)
def test_unsafe_p0_values_are_rejected_before_execution(
    scenario_payload: dict[str, object], field: str, value: object, location: str
) -> None:
    payload = deepcopy(scenario_payload)
    payload[field] = value

    with pytest.raises(ScenarioInputError) as raised:
        load_scenario(json.dumps(payload), "application/json")

    assert raised.value.diagnostics[0]["location"] == location
