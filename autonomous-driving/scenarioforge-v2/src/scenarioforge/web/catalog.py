from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Final

from .coordinator import InvalidIdentifierError, UnknownScenarioError

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_P0B_PROFILE: Final = "p0b"
_P0C_PROFILE: Final = "p0c"
_P1_BACKEND: Final = {
    "id": "scenarioforge.smarts",
    "version": "2.0.1",
    "status": "exact",
}
_REGISTERED_INSTANCE_ID = "brake-lead-happy"
_P0B_METADATA = {
    "scenario_id": "brake_lead",
    "display_name": "Lead Vehicle Emergency Braking",
    "description": "An ego vehicle follows a lead vehicle that brakes at a fixed tick.",
}
_P0C_METADATA: tuple[dict[str, object], ...] = (
    {
        "scenario_id": "brake_lead",
        "display_name": "Lead Vehicle Emergency Braking",
        "description": (
            "Ego follows a lead vehicle that brakes suddenly on a straight road."
        ),
        "target_outcome": "near_miss",
        "participants": [
            {"id": "ego", "role": "ego", "label": "Following vehicle"},
            {"id": "lead", "role": "social", "label": "Lead vehicle"},
        ],
        "routes": [
            {
                "participant_id": "ego",
                "summary": "Continue along the following lane behind the lead vehicle.",
            },
            {
                "participant_id": "lead",
                "summary": "Continue along the same lane while slowing sharply.",
            },
        ],
        "danger": "The lead vehicle brakes at tick 35 while ego is following closely.",
        "expected_reaction": "Ego brakes at tick 40 to avoid the lead vehicle.",
        "success_meaning": "Both vehicles finish their routes without a collision.",
        "failure_meaning": "A collision, boundary violation, or route timeout occurs.",
    },
    {
        "scenario_id": "construction_merge",
        "display_name": "Construction Lane Closure",
        "description": (
            "Ego starts in a closing lane and must merge into the open lane."
        ),
        "target_outcome": "safe_pass",
        "participants": [
            {"id": "ego", "role": "ego", "label": "Merging vehicle"},
            {"id": "social", "role": "social", "label": "Open-lane vehicle"},
        ],
        "routes": [
            {
                "participant_id": "ego",
                "summary": "Move from the closing lane into the open lane.",
            },
            {
                "participant_id": "social",
                "summary": "Continue straight in the open lane.",
            },
        ],
        "danger": (
            "The closing lane reaches a construction taper between 60 m and 90 m."
        ),
        "expected_reaction": "Ego selects a gap and merges before entering the closure.",
        "success_meaning": "Ego reaches the open lane and passes the construction zone.",
        "failure_meaning": (
            "A collision, boundary violation, closed-region entry, or timeout occurs."
        ),
    },
    {
        "scenario_id": "dangerous_cut_in",
        "display_name": "Dangerous Adjacent-Lane Cut-In",
        "description": (
            "A nearby vehicle cuts abruptly into ego's lane inside a conflict area."
        ),
        "target_outcome": "collision_failure",
        "participants": [
            {"id": "ego", "role": "ego", "label": "Main-lane vehicle"},
            {"id": "cutter", "role": "social", "label": "Cut-in vehicle"},
        ],
        "routes": [
            {
                "participant_id": "ego",
                "summary": "Continue straight in the ego lane.",
            },
            {
                "participant_id": "cutter",
                "summary": "Move from the adjacent lane into the ego lane.",
            },
        ],
        "danger": (
            "The cut-in begins at tick 5 in the 35 m to 80 m conflict area."
        ),
        "expected_reaction": (
            "Observe the forced cut-in and the resulting collision evidence."
        ),
        "success_meaning": (
            "The expected collision failure is recorded with complete evidence."
        ),
        "failure_meaning": (
            "The run diverges from the frozen cut-in or lacks complete evidence."
        ),
    },
    {
        "scenario_id": "highway_merge",
        "display_name": "Highway Entrance-Ramp Merge",
        "description": (
            "Ego enters from a ramp and must merge between two mainline vehicles."
        ),
        "target_outcome": "safe_pass",
        "participants": [
            {"id": "ego", "role": "ego", "label": "Ramp vehicle"},
            {
                "id": "front",
                "role": "social",
                "label": "Front mainline vehicle",
            },
            {
                "id": "rear",
                "role": "social",
                "label": "Rear mainline vehicle",
            },
        ],
        "routes": [
            {
                "participant_id": "ego",
                "summary": "Follow the ramp and enter the right mainline lane.",
            },
            {
                "participant_id": "front",
                "summary": "Continue ahead in the right mainline lane.",
            },
            {
                "participant_id": "rear",
                "summary": "Continue behind the available merge gap.",
            },
        ],
        "danger": "The ramp and mainline overlap in the 35 m to 80 m merge area.",
        "expected_reaction": (
            "Ego observes both mainline vehicles and selects the gap."
        ),
        "success_meaning": (
            "Ego reaches the right mainline lane without a collision."
        ),
        "failure_meaning": (
            "A collision, route departure, wrong-lane entry, or timeout occurs."
        ),
    },
    {
        "scenario_id": "unprotected_left_turn",
        "display_name": "Unprotected Left Turn",
        "description": (
            "Ego turns left across the path of an oncoming through vehicle."
        ),
        "target_outcome": "near_miss",
        "participants": [
            {"id": "ego", "role": "ego", "label": "Left-turning vehicle"},
            {"id": "oncoming", "role": "social", "label": "Oncoming vehicle"},
        ],
        "routes": [
            {
                "participant_id": "ego",
                "summary": "Yield, cross the intersection, and reach the north exit.",
            },
            {
                "participant_id": "oncoming",
                "summary": (
                    "Travel straight through the intersection to the west exit."
                ),
            },
        ],
        "danger": (
            "Both routes cross in the left-turn conflict zone at the intersection."
        ),
        "expected_reaction": (
            "Ego yields first, then commits to the turn after oncoming clears."
        ),
        "success_meaning": (
            "Ego yields and completes the left-turn route without collision."
        ),
        "failure_meaning": (
            "A collision, boundary violation, wrong route, or timeout occurs."
        ),
    },
)
_P0C_RELATIVE_PATHS = {
    str(item["scenario_id"]): Path("examples/p0c") / f"{item['scenario_id']}.json"
    for item in _P0C_METADATA
}

_P1_METADATA: tuple[dict[str, object], ...] = (
    {
        "scenario_id": "highway_merge",
        "display_name": "Canonical Highway Merge",
        "description": (
            "Ego joins a right-hand-traffic mainline between recorded SMARTS "
            "participants."
        ),
        "target_outcome": "recorded",
        "participants": [
            {"id": "ego", "role": "ego", "label": "Merging ego"},
            {"id": "front", "role": "controlled", "label": "Front agent"},
            {"id": "rear", "role": "social_vehicle", "label": "Rear traffic"},
            {"id": "traffic", "role": "social_vehicle", "label": "Mainline traffic"},
        ],
        "backend": _P1_BACKEND,
    },
    {
        "scenario_id": "competitive_lane_change",
        "display_name": "Canonical Competitive Lane Change",
        "description": (
            "Two controlled vehicles compete for a gap on a recorded SMARTS road."
        ),
        "target_outcome": "recorded",
        "participants": [
            {"id": "ego", "role": "ego", "label": "Ego"},
            {"id": "challenger", "role": "controlled", "label": "Challenger"},
            {"id": "traffic", "role": "social_vehicle", "label": "Traffic"},
        ],
        "backend": _P1_BACKEND,
    },
    {
        "scenario_id": "cross_traffic_red_light_violation",
        "display_name": "Canonical Cross-Traffic Red-Light Violation",
        "description": (
            "Cross traffic violates a signal in a right-hand-traffic SMARTS intersection."
        ),
        "target_outcome": "recorded",
        "participants": [
            {"id": "ego", "role": "ego", "label": "Ego"},
            {"id": "violator", "role": "controlled", "label": "Violator"},
            {"id": "traffic", "role": "social_vehicle", "label": "Traffic"},
        ],
        "backend": _P1_BACKEND,
    },
    {
        "scenario_id": "unprotected_left_turn",
        "display_name": "Canonical Unprotected Left Turn",
        "description": (
            "Ego yields and turns across recorded oncoming traffic in SMARTS."
        ),
        "target_outcome": "recorded",
        "participants": [
            {"id": "ego", "role": "ego", "label": "Turning ego"},
            {"id": "oncoming", "role": "controlled", "label": "Oncoming agent"},
            {"id": "traffic", "role": "social_vehicle", "label": "Traffic"},
        ],
        "backend": _P1_BACKEND,
    },
    {
        "scenario_id": "pedestrian_red_light_crossing",
        "display_name": "Canonical Pedestrian Red-Light Crossing",
        "description": (
            "A recorded pedestrian crosses against the light in a SMARTS intersection."
        ),
        "target_outcome": "recorded",
        "participants": [
            {"id": "ego", "role": "ego", "label": "Ego"},
            {"id": "traffic", "role": "controlled", "label": "Controlled traffic"},
            {"id": "pedestrian", "role": "pedestrian", "label": "Pedestrian"},
        ],
        "backend": _P1_BACKEND,
    },
)


def _metadata_for_profile(profile: str) -> tuple[dict[str, object], ...]:
    if profile == _P0B_PROFILE:
        return (_P0B_METADATA,)
    if profile == _P0C_PROFILE:
        return _P0C_METADATA
    raise ValueError("unknown scenario catalog profile")


def _validated_scenario_id(scenario_id: str, *, profile: str) -> str:
    if not isinstance(scenario_id, str) or _SAFE_ID.fullmatch(scenario_id) is None:
        raise InvalidIdentifierError("invalid scenario_id")
    if scenario_id not in {
        str(item["scenario_id"]) for item in _metadata_for_profile(profile)
    }:
        raise UnknownScenarioError("unknown scenario_id")
    return scenario_id


def scenario_catalog(*, profile: str = _P0B_PROFILE) -> dict[str, object]:
    """Return bounded display metadata without source paths or ScenarioSpecs."""
    metadata = _metadata_for_profile(profile)
    if profile == _P0B_PROFILE:
        return {
            "schema_version": "scenarioforge.scenario-catalog/v1",
            "scenarios": copy.deepcopy(list(metadata)),
        }
    return {
        "schema_version": "scenarioforge.scenario-catalog/v2",
        "default_scenario_id": "brake_lead",
        "scenarios": copy.deepcopy(list(metadata)),
    }


def scenario_metadata(
    scenario_id: str,
    *,
    profile: str = _P0B_PROFILE,
) -> dict[str, object]:
    validated = _validated_scenario_id(scenario_id, profile=profile)
    metadata = next(
        item
        for item in _metadata_for_profile(profile)
        if item["scenario_id"] == validated
    )
    return copy.deepcopy(metadata)


def p1_scenario_catalog() -> dict[str, object]:
    """Expose the distinct canonical SMARTS catalog without relabeling P0."""
    return {
        "schema_version": "scenarioforge.p1-scenario-catalog/v1",
        "default_scenario_id": "highway_merge",
        "scenarios": copy.deepcopy(list(_P1_METADATA)),
    }


def p1_scenario_metadata(scenario_id: str) -> dict[str, object]:
    if not isinstance(scenario_id, str) or _SAFE_ID.fullmatch(scenario_id) is None:
        raise InvalidIdentifierError("invalid scenario_id")
    try:
        metadata = next(
            item for item in _P1_METADATA if item["scenario_id"] == scenario_id
        )
    except StopIteration as error:
        raise UnknownScenarioError("unknown P1 SMARTS scenario_id") from error
    return copy.deepcopy(metadata)


def registered_scenario_ids(*, profile: str = _P0B_PROFILE) -> tuple[str, ...]:
    return tuple(str(item["scenario_id"]) for item in _metadata_for_profile(profile))


def registered_scenario_path(
    scenario_id: str,
    *,
    profile: str = _P0B_PROFILE,
) -> Path:
    validated = _validated_scenario_id(scenario_id, profile=profile)
    if profile == _P0B_PROFILE:
        return Path("examples/p0a/brake_lead.json")
    return _P0C_RELATIVE_PATHS[validated]


def registered_scenario_for_instance(instance_id: str) -> str:
    """Bind immutable P0-A evidence to the historical registered scenario."""
    if instance_id != _REGISTERED_INSTANCE_ID:
        raise UnknownScenarioError("published evidence references an unknown scenario")
    return "brake_lead"


__all__ = [
    "p1_scenario_catalog",
    "p1_scenario_metadata",
    "registered_scenario_for_instance",
    "registered_scenario_ids",
    "registered_scenario_path",
    "scenario_catalog",
    "scenario_metadata",
]
