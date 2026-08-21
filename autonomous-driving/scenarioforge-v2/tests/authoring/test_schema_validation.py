from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from scenarioforge.authoring import (
    AUTHORING_SCHEMA,
    AUTHORING_SCHEMA_VERSION,
    CapabilityStatus,
    validate_authoring_spec,
)


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "authoring" / "valid_scenario.json"


@pytest.fixture
def valid_scenario() -> dict[str, Any]:
    value = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _diagnostic_for(report: object, code: str) -> object:
    matches = [item for item in report.diagnostics if item.code == code]
    assert len(matches) == 1, [item.to_dict() for item in report.diagnostics]
    return matches[0]


def test_authoring_schema_is_a_valid_draft_2020_12_schema() -> None:
    Draft202012Validator.check_schema(AUTHORING_SCHEMA)


def test_complete_backend_independent_fixture_is_exact(
    valid_scenario: dict[str, Any],
) -> None:
    report = validate_authoring_spec(valid_scenario)

    assert report.to_dict() == {
        "schema_version": "scenarioforge.authoring-validation/v1",
        "document_schema_version": AUTHORING_SCHEMA_VERSION,
        "valid": True,
        "overall_status": "exact",
        "diagnostics": [],
    }
    assert {actor["kind"] for actor in valid_scenario["actors"]} == {
        "pedestrian",
        "vehicle",
    }
    assert valid_scenario["static_obstacles"]
    assert valid_scenario["environment"]
    assert valid_scenario["events"]
    assert valid_scenario["constraints"]["success_conditions"]
    assert valid_scenario["constraints"]["failure_conditions"]
    assert valid_scenario["parameters"][0]["distribution"]
    assert valid_scenario["policy"]["id"]
    assert valid_scenario["required_capabilities"]

    serialized_schema = json.dumps(AUTHORING_SCHEMA, sort_keys=True).lower()
    for backend_internal in (
        "metadrive",
        "engine_lane_index",
        "start_node",
        "end_node",
        "engine object",
    ):
        assert backend_internal not in serialized_schema


@pytest.mark.parametrize(
    ("mutate", "code", "path"),
    [
        (
            lambda value: value.__setitem__("seed", -1),
            "value_out_of_range",
            "$.seed",
        ),
        (
            lambda value: value["environment"].__setitem__(
                "weather", "volcanic_ash"
            ),
            "invalid_enum",
            "$.environment.weather",
        ),
        (
            lambda value: value["road"]["lanes"][0].__setitem__(
                "engine_lane_index", [">>", ">>>", 0]
            ),
            "unknown_field",
            "$.road.lanes[0].engine_lane_index",
        ),
        (
            lambda value: value["actors"][0]["spawn"].__setitem__(
                "speed_mps", "fast"
            ),
            "invalid_type",
            "$.actors[0].spawn.speed_mps",
        ),
    ],
)
def test_schema_errors_have_stable_paths_statuses_and_suggestions(
    valid_scenario: dict[str, Any],
    mutate: object,
    code: str,
    path: str,
) -> None:
    mutate(valid_scenario)

    report = validate_authoring_spec(valid_scenario)

    diagnostic = _diagnostic_for(report, code)
    assert report.valid is False
    assert report.overall_status is CapabilityStatus.UNSUPPORTED
    assert diagnostic.path == path
    assert diagnostic.status is CapabilityStatus.UNSUPPORTED
    assert diagnostic.capability == "authoring.schema"
    assert diagnostic.reason
    assert diagnostic.suggestion
    assert "metadrive" not in diagnostic.reason.lower()
    assert "metadrive" not in diagnostic.suggestion.lower()


def test_missing_fields_are_reported_at_the_missing_field_path(
    valid_scenario: dict[str, Any],
) -> None:
    del valid_scenario["policy"]["version"]

    report = validate_authoring_spec(valid_scenario)

    diagnostic = _diagnostic_for(report, "required_field_missing")
    assert diagnostic.path == "$.policy.version"
    assert diagnostic.to_dict() == {
        "code": "required_field_missing",
        "path": "$.policy.version",
        "capability": "authoring.schema",
        "status": "unsupported",
        "reason": "a required authoring field is missing",
        "suggestion": "provide the required field using the documented authoring contract",
    }


def test_invalid_route_references_and_disconnected_lanes_fail_closed(
    valid_scenario: dict[str, Any],
) -> None:
    missing_lane = copy.deepcopy(valid_scenario)
    missing_lane["routes"][0]["lane_ids"][1] = "missing-lane"
    missing_report = validate_authoring_spec(missing_lane)
    missing = _diagnostic_for(missing_report, "route_lane_missing")
    assert missing.path == "$.routes[0].lane_ids[1]"
    assert missing.capability == "route.connected"
    assert missing.status is CapabilityStatus.UNSUPPORTED

    disconnected = copy.deepcopy(valid_scenario)
    disconnected["road"]["lanes"][0]["successor_lane_ids"] = []
    disconnected_report = validate_authoring_spec(disconnected)
    disconnected_diagnostic = _diagnostic_for(
        disconnected_report, "route_lanes_disconnected"
    )
    assert disconnected_diagnostic.path == "$.routes[0].lane_ids[1]"
    assert disconnected_diagnostic.suggestion == (
        "connect consecutive route lanes or choose an existing connected route"
    )


def test_spawn_overlap_and_route_mismatch_have_actor_paths(
    valid_scenario: dict[str, Any],
) -> None:
    overlap = copy.deepcopy(valid_scenario)
    overlap["actors"][1]["spawn"] = copy.deepcopy(
        overlap["actors"][0]["spawn"]
    )
    overlap["actors"][1]["route_id"] = overlap["actors"][0]["route_id"]
    overlap_report = validate_authoring_spec(overlap)
    collision = _diagnostic_for(overlap_report, "spawn_overlap")
    assert collision.path == "$.actors[1].spawn"
    assert collision.capability == "actor.spawn.non-overlap"

    mismatch = copy.deepcopy(valid_scenario)
    mismatch["actors"][0]["route_id"] = "crosswalk-route"
    mismatch_report = validate_authoring_spec(mismatch)
    route = _diagnostic_for(mismatch_report, "spawn_route_mismatch")
    assert route.path == "$.actors[0].route_id"
    assert route.suggestion == (
        "choose a route whose first lane matches the actor spawn lane"
    )


def test_obstacle_overlap_and_late_event_are_obviously_unexecutable(
    valid_scenario: dict[str, Any],
) -> None:
    obstacle_overlap = copy.deepcopy(valid_scenario)
    obstacle_overlap["static_obstacles"][0]["lane_id"] = "approach"
    obstacle_overlap["static_obstacles"][0]["longitudinal_m"] = 10.0
    obstacle_overlap["static_obstacles"][0]["lateral_m"] = 0.0
    overlap_report = validate_authoring_spec(obstacle_overlap)
    overlap = _diagnostic_for(overlap_report, "spawn_obstacle_overlap")
    assert overlap.path == "$.static_obstacles[0]"
    assert overlap.capability == "actor.spawn.non-overlap"

    late_event = copy.deepcopy(valid_scenario)
    late_event["events"][0]["trigger"]["time_s"] = 31.0
    late_report = validate_authoring_spec(late_event)
    late = _diagnostic_for(late_report, "event_outside_duration")
    assert late.path == "$.events[0].trigger.time_s"
    assert late.capability == "event.executable"


@pytest.mark.parametrize(
    ("actor_index", "field", "value", "code", "path"),
    [
        (2, "role", "ego", "actor_role_kind_mismatch", "$.actors[2].role"),
        (
            1,
            "behavior",
            {"profile": "walking"},
            "actor_behavior_kind_mismatch",
            "$.actors[1].behavior.profile",
        ),
    ],
)
def test_actor_kind_role_and_behavior_combinations_fail_closed(
    valid_scenario: dict[str, Any],
    actor_index: int,
    field: str,
    value: object,
    code: str,
    path: str,
) -> None:
    valid_scenario["actors"][actor_index][field] = value

    report = validate_authoring_spec(valid_scenario)

    diagnostic = _diagnostic_for(report, code)
    assert report.valid is False
    assert report.overall_status is CapabilityStatus.UNSUPPORTED
    assert diagnostic.path == path
    assert diagnostic.status is CapabilityStatus.UNSUPPORTED
    assert diagnostic.suggestion


def test_normal_distribution_mean_must_be_inside_its_declared_bounds(
    valid_scenario: dict[str, Any],
) -> None:
    valid_scenario["parameters"][0]["distribution"] = {
        "kind": "normal",
        "mean": 60.0,
        "standard_deviation": 2.0,
        "minimum": 40.0,
        "maximum": 50.0,
    }

    report = validate_authoring_spec(valid_scenario)

    diagnostic = _diagnostic_for(report, "distribution_mean_outside_bounds")
    assert report.valid is False
    assert report.overall_status is CapabilityStatus.UNSUPPORTED
    assert diagnostic.path == "$.parameters[0].distribution.mean"
    assert diagnostic.capability == "parameter.distribution"
    assert diagnostic.suggestion == (
        "place the normal mean between minimum and maximum"
    )


def test_validation_reports_all_semantic_errors_without_mutating_input(
    valid_scenario: dict[str, Any],
) -> None:
    invalid = copy.deepcopy(valid_scenario)
    invalid["routes"][0]["lane_ids"][1] = "missing-lane"
    invalid["events"][0]["actor_id"] = "missing-actor"
    invalid["constraints"]["success_conditions"][0]["actor_ids"] = [
        "missing-actor"
    ]
    before = copy.deepcopy(invalid)

    report = validate_authoring_spec(invalid)

    assert invalid == before
    assert report.valid is False
    assert report.overall_status is CapabilityStatus.UNSUPPORTED
    assert {item.code for item in report.diagnostics} >= {
        "route_lane_missing",
        "event_actor_missing",
        "constraint_actor_missing",
    }
    assert [item.path for item in report.diagnostics] == sorted(
        item.path for item in report.diagnostics
    )


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_non_finite_numbers_fail_closed_before_schema_validation(
    valid_scenario: dict[str, Any], value: float
) -> None:
    valid_scenario["policy"]["config"]["target_speed_mps"] = value

    report = validate_authoring_spec(valid_scenario)

    diagnostic = _diagnostic_for(report, "non_finite_number")
    assert diagnostic.path == "$.policy.config.target_speed_mps"
    assert diagnostic.status is CapabilityStatus.UNSUPPORTED
    assert "nan" not in diagnostic.reason.lower()
    assert "inf" not in diagnostic.reason.lower()


def test_parameter_target_must_resolve_to_a_numeric_field(
    valid_scenario: dict[str, Any],
) -> None:
    valid_scenario["parameters"][0]["target_path"] = (
        "$.actors[99].spawn.longitudinal_m"
    )

    report = validate_authoring_spec(valid_scenario)

    diagnostic = _diagnostic_for(report, "parameter_target_missing")
    assert diagnostic.path == "$.parameters[0].target_path"
    assert diagnostic.capability == "parameter.target"
    assert diagnostic.suggestion == (
        "reference an existing numeric authoring field"
    )


def test_integer_target_with_continuous_distribution_is_explicitly_lossy(
    valid_scenario: dict[str, Any],
) -> None:
    valid_scenario["parameters"][0]["value_type"] = "integer"

    report = validate_authoring_spec(valid_scenario)

    diagnostic = _diagnostic_for(report, "integer_distribution_requires_rounding")
    assert report.valid is True
    assert report.overall_status is CapabilityStatus.LOSSY
    assert diagnostic.path == "$.parameters[0].distribution"
    assert diagnostic.status is CapabilityStatus.LOSSY
    assert diagnostic.capability == "parameter.integer-distribution"
    assert diagnostic.suggestion == (
        "use fixed or choice with integer values for exact semantics"
    )
