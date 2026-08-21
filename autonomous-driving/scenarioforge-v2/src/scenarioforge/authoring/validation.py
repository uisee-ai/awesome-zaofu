from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from itertools import combinations
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from .models import (
    AuthoringDiagnostic,
    AuthoringValidationReport,
    CapabilityStatus,
)
from .schema import AUTHORING_SCHEMA


_SCHEMA_DIAGNOSTICS = {
    "type": (
        "invalid_type",
        "the field uses a value of the wrong JSON type",
        "replace it with a value of the documented JSON type",
    ),
    "enum": (
        "invalid_enum",
        "the field is not one of the supported authoring primitives",
        "choose one of the finite values declared by the authoring contract",
    ),
    "const": (
        "invalid_constant",
        "the field does not match the frozen authoring contract value",
        "use the exact value declared by the authoring contract",
    ),
    "pattern": (
        "invalid_format",
        "the field does not match the bounded authoring identifier format",
        "use the documented lowercase identifier or reference format",
    ),
    "minLength": (
        "value_out_of_range",
        "the string is shorter than the supported bound",
        "provide a value within the documented authoring bounds",
    ),
    "maxLength": (
        "value_out_of_range",
        "the string is longer than the supported bound",
        "provide a value within the documented authoring bounds",
    ),
    "minimum": (
        "value_out_of_range",
        "the numeric value is outside the supported authoring range",
        "provide a value within the documented inclusive bounds",
    ),
    "maximum": (
        "value_out_of_range",
        "the numeric value is outside the supported authoring range",
        "provide a value within the documented inclusive bounds",
    ),
    "exclusiveMinimum": (
        "value_out_of_range",
        "the numeric value is outside the supported authoring range",
        "provide a value strictly above the documented lower bound",
    ),
    "exclusiveMaximum": (
        "value_out_of_range",
        "the numeric value is outside the supported authoring range",
        "provide a value strictly below the documented upper bound",
    ),
    "minItems": (
        "value_out_of_range",
        "the collection has fewer items than the authoring contract requires",
        "add items until the documented minimum is met",
    ),
    "maxItems": (
        "value_out_of_range",
        "the collection has more items than the authoring contract permits",
        "remove items until the documented maximum is met",
    ),
    "uniqueItems": (
        "duplicate_item",
        "the collection contains duplicate values",
        "remove duplicate values",
    ),
    "oneOf": (
        "invalid_union_value",
        "the field does not match exactly one supported authoring shape",
        "use one complete shape declared by the authoring contract",
    ),
}


def _path(parts: Sequence[object]) -> str:
    rendered = "$"
    for part in parts:
        if isinstance(part, int):
            rendered += f"[{part}]"
        else:
            rendered += f".{part}"
    return rendered


def _diagnostic(
    code: str,
    path: str,
    capability: str,
    reason: str,
    suggestion: str,
    *,
    status: CapabilityStatus = CapabilityStatus.UNSUPPORTED,
) -> AuthoringDiagnostic:
    return AuthoringDiagnostic(
        code=code,
        path=path,
        capability=capability,
        status=status,
        reason=reason,
        suggestion=suggestion,
    )


def _schema_diagnostics(error: ValidationError) -> list[AuthoringDiagnostic]:
    base_path = list(error.absolute_path)
    if error.validator == "required" and isinstance(error.instance, Mapping):
        required = error.validator_value
        missing = sorted(
            field for field in required if field not in error.instance
        )
        return [
            _diagnostic(
                "required_field_missing",
                _path([*base_path, field]),
                "authoring.schema",
                "a required authoring field is missing",
                "provide the required field using the documented authoring contract",
            )
            for field in missing
        ]
    if error.validator == "additionalProperties" and isinstance(
        error.instance, Mapping
    ):
        declared = set(error.schema.get("properties", {}))
        unexpected = sorted(set(error.instance) - declared)
        return [
            _diagnostic(
                "unknown_field",
                _path([*base_path, field]),
                "authoring.schema",
                "the authoring contract rejects unknown fields",
                "remove the unknown field and express the intent with a documented semantic field",
            )
            for field in unexpected
        ]
    code, reason, suggestion = _SCHEMA_DIAGNOSTICS.get(
        str(error.validator),
        (
            "schema_validation_failed",
            "the field does not satisfy the authoring contract",
            "replace the field with a value accepted by the documented authoring contract",
        ),
    )
    return [
        _diagnostic(
            code,
            _path(base_path),
            "authoring.schema",
            reason,
            suggestion,
        )
    ]


def _schema_validate(value: Any) -> list[AuthoringDiagnostic]:
    validator = Draft202012Validator(AUTHORING_SCHEMA)
    errors = sorted(
        validator.iter_errors(value),
        key=lambda item: (_path(list(item.absolute_path)), str(item.validator)),
    )
    diagnostics: list[AuthoringDiagnostic] = []
    for error in errors:
        diagnostics.extend(_schema_diagnostics(error))
    return diagnostics


def _non_finite_diagnostics(
    value: Any, parts: tuple[object, ...] = ()
) -> list[AuthoringDiagnostic]:
    diagnostics: list[AuthoringDiagnostic] = []
    if isinstance(value, float) and not math.isfinite(value):
        diagnostics.append(
            _diagnostic(
                "non_finite_number",
                _path(parts),
                "authoring.finite-number",
                "authoring numbers must be finite",
                "replace the value with a finite number within the documented bounds",
            )
        )
    elif isinstance(value, Mapping):
        for key, item in value.items():
            diagnostics.extend(
                _non_finite_diagnostics(item, (*parts, str(key)))
            )
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            diagnostics.extend(_non_finite_diagnostics(item, (*parts, index)))
    return diagnostics


_TARGET_TOKEN = re.compile(r"\.([a-z][a-z0-9_]*)|\[([0-9]+)\]")
_MISSING = object()


def _resolve_target(value: Mapping[str, Any], path: str) -> Any:
    current: Any = value
    position = 1
    for match in _TARGET_TOKEN.finditer(path, position):
        if match.start() != position:
            return _MISSING
        field, index = match.groups()
        if field is not None and isinstance(current, Mapping) and field in current:
            current = current[field]
        elif index is not None and isinstance(current, (list, tuple)):
            offset = int(index)
            if offset >= len(current):
                return _MISSING
            current = current[offset]
        else:
            return _MISSING
        position = match.end()
    return current if position == len(path) else _MISSING


def _semantic_validate(value: Mapping[str, Any]) -> list[AuthoringDiagnostic]:
    diagnostics: list[AuthoringDiagnostic] = []
    lanes = value["road"]["lanes"]
    routes = value["routes"]
    actors = value["actors"]
    obstacles = value["static_obstacles"]
    events = value["events"]
    constraints = value["constraints"]

    def add(
        code: str,
        path: str,
        capability: str,
        reason: str,
        suggestion: str,
        *,
        status: CapabilityStatus = CapabilityStatus.UNSUPPORTED,
    ) -> None:
        diagnostics.append(
            _diagnostic(
                code,
                path,
                capability,
                reason,
                suggestion,
                status=status,
            )
        )

    def check_unique_ids(items: Sequence[Mapping[str, Any]], base: str) -> None:
        seen: set[str] = set()
        for index, item in enumerate(items):
            identifier = str(item["id"])
            if identifier in seen:
                add(
                    "duplicate_identifier",
                    f"{base}[{index}].id",
                    "identity.stable-id",
                    "stable identifiers must be unique within their collection",
                    "choose a unique stable identifier",
                )
            seen.add(identifier)

    for items, base in (
        (lanes, "$.road.lanes"),
        (value["road"]["conflict_zones"], "$.road.conflict_zones"),
        (routes, "$.routes"),
        (actors, "$.actors"),
        (obstacles, "$.static_obstacles"),
        (events, "$.events"),
        (value["parameters"], "$.parameters"),
    ):
        check_unique_ids(items, base)

    lane_by_id = {str(lane["id"]): lane for lane in lanes}
    route_by_id = {str(route["id"]): route for route in routes}
    actor_by_id = {str(actor["id"]): actor for actor in actors}

    for lane_index, lane in enumerate(lanes):
        for relation in ("predecessor_lane_ids", "successor_lane_ids"):
            for reference_index, lane_id in enumerate(lane[relation]):
                if lane_id not in lane_by_id:
                    add(
                        "lane_reference_missing",
                        f"$.road.lanes[{lane_index}].{relation}[{reference_index}]",
                        "road.topology.connected",
                        "the lane relation references a lane that does not exist",
                        "reference an existing stable lane identifier",
                    )

    for zone_index, zone in enumerate(value["road"]["conflict_zones"]):
        for lane_index, lane_id in enumerate(zone["lane_ids"]):
            if lane_id not in lane_by_id:
                add(
                    "conflict_zone_lane_missing",
                    f"$.road.conflict_zones[{zone_index}].lane_ids[{lane_index}]",
                    "road.conflict-zone",
                    "the conflict zone references a lane that does not exist",
                    "reference an existing stable lane identifier",
                )

    for route_index, route in enumerate(routes):
        route_lane_ids = list(route["lane_ids"])
        for lane_index, lane_id in enumerate(route_lane_ids):
            if lane_id not in lane_by_id:
                add(
                    "route_lane_missing",
                    f"$.routes[{route_index}].lane_ids[{lane_index}]",
                    "route.connected",
                    "the route references a lane that does not exist",
                    "replace it with an existing stable lane identifier",
                )
        for lane_index, (current, following) in enumerate(
            zip(route_lane_ids, route_lane_ids[1:]), start=1
        ):
            if current in lane_by_id and following in lane_by_id:
                if following not in lane_by_id[current]["successor_lane_ids"]:
                    add(
                        "route_lanes_disconnected",
                        f"$.routes[{route_index}].lane_ids[{lane_index}]",
                        "route.connected",
                        "consecutive route lanes are not connected by the road topology",
                        "connect consecutive route lanes or choose an existing connected route",
                    )
        goal = route["goal"]
        if goal["lane_id"] not in lane_by_id:
            add(
                "route_goal_lane_missing",
                f"$.routes[{route_index}].goal.lane_id",
                "route.goal",
                "the route goal references a lane that does not exist",
                "choose an existing route lane as the goal",
            )
        elif goal["lane_id"] != route_lane_ids[-1]:
            add(
                "route_goal_mismatch",
                f"$.routes[{route_index}].goal.lane_id",
                "route.goal",
                "the route goal must lie on the final route lane",
                "set the goal lane to the final lane in lane_ids",
            )
        elif float(goal["longitudinal_m"]) > float(
            lane_by_id[goal["lane_id"]]["length_m"]
        ):
            add(
                "route_goal_outside_lane",
                f"$.routes[{route_index}].goal.longitudinal_m",
                "route.goal",
                "the route goal lies beyond the declared lane length",
                "move the goal within the final lane length",
            )

    ego_indexes = [index for index, actor in enumerate(actors) if actor["role"] == "ego"]
    if len(ego_indexes) != 1:
        add(
            "ego_count_invalid",
            "$.actors",
            "actor.ego",
            "an executable authoring scenario requires exactly one ego actor",
            "mark exactly one vehicle actor with role ego",
        )

    for actor_index, actor in enumerate(actors):
        spawn = actor["spawn"]
        route = route_by_id.get(str(actor["route_id"]))
        actor_kind = str(actor["kind"])
        actor_role = str(actor["role"])
        allowed_roles = {
            "vehicle": {"ego", "social"},
            "pedestrian": {"vulnerable_road_user"},
        }
        if actor_role not in allowed_roles[actor_kind]:
            add(
                "actor_role_kind_mismatch",
                f"$.actors[{actor_index}].role",
                "actor.role-kind",
                "the actor role is incompatible with the actor kind",
                "choose a role declared for this actor kind",
            )
        behavior_profile = str(actor["behavior"]["profile"])
        allowed_profiles = {
            "vehicle": {"deterministic", "conservative", "normal", "aggressive"},
            "pedestrian": {"walking", "standing"},
        }
        if behavior_profile not in allowed_profiles[actor_kind]:
            add(
                "actor_behavior_kind_mismatch",
                f"$.actors[{actor_index}].behavior.profile",
                "actor.behavior-kind",
                "the behavior profile is incompatible with the actor kind",
                "choose a behavior profile declared for this actor kind",
            )
        if spawn["lane_id"] not in lane_by_id:
            add(
                "spawn_lane_missing",
                f"$.actors[{actor_index}].spawn.lane_id",
                "actor.spawn",
                "the actor spawn references a lane that does not exist",
                "choose an existing stable lane identifier",
            )
        elif float(spawn["longitudinal_m"]) > float(
            lane_by_id[spawn["lane_id"]]["length_m"]
        ):
            add(
                "spawn_outside_lane",
                f"$.actors[{actor_index}].spawn.longitudinal_m",
                "actor.spawn",
                "the actor spawn lies beyond the declared lane length",
                "move the actor spawn within the lane length",
            )
        if route is None:
            add(
                "actor_route_missing",
                f"$.actors[{actor_index}].route_id",
                "route.connected",
                "the actor references a route that does not exist",
                "choose an existing stable route identifier",
            )
        else:
            if spawn["lane_id"] != route["lane_ids"][0]:
                add(
                    "spawn_route_mismatch",
                    f"$.actors[{actor_index}].route_id",
                    "route.connected",
                    "the actor spawn lane does not match the first route lane",
                    "choose a route whose first lane matches the actor spawn lane",
                )
            if actor["kind"] != route["kind"]:
                add(
                    "actor_route_kind_mismatch",
                    f"$.actors[{actor_index}].route_id",
                    "route.actor-kind",
                    "the route kind is incompatible with the actor kind",
                    "choose a route declared for this actor kind",
                )

    for (_, first), (second_index, second) in combinations(enumerate(actors), 2):
        first_spawn = first["spawn"]
        second_spawn = second["spawn"]
        longitudinal_limit = (
            float(first["dimensions"]["length_m"])
            + float(second["dimensions"]["length_m"])
        ) / 2.0
        lateral_limit = (
            float(first["dimensions"]["width_m"])
            + float(second["dimensions"]["width_m"])
        ) / 2.0
        if (
            first_spawn["lane_id"] == second_spawn["lane_id"]
            and abs(
                float(first_spawn["longitudinal_m"])
                - float(second_spawn["longitudinal_m"])
            )
            < longitudinal_limit
            and abs(
                float(first_spawn["lateral_m"])
                - float(second_spawn["lateral_m"])
            )
            < lateral_limit
        ):
            add(
                "spawn_overlap",
                f"$.actors[{second_index}].spawn",
                "actor.spawn.non-overlap",
                "actor footprints overlap at scenario start",
                "separate actor spawn positions by their declared footprints",
            )

    for obstacle_index, obstacle in enumerate(obstacles):
        if obstacle["lane_id"] not in lane_by_id:
            add(
                "obstacle_lane_missing",
                f"$.static_obstacles[{obstacle_index}].lane_id",
                "static-obstacle.placement",
                "the static obstacle references a lane that does not exist",
                "choose an existing stable lane identifier",
            )
            continue
        if float(obstacle["longitudinal_m"]) > float(
            lane_by_id[obstacle["lane_id"]]["length_m"]
        ):
            add(
                "obstacle_outside_lane",
                f"$.static_obstacles[{obstacle_index}].longitudinal_m",
                "static-obstacle.placement",
                "the static obstacle lies beyond the declared lane length",
                "move the obstacle within the lane length",
            )
        for actor in actors:
            spawn = actor["spawn"]
            longitudinal_limit = (
                float(obstacle["dimensions"]["length_m"])
                + float(actor["dimensions"]["length_m"])
            ) / 2.0
            lateral_limit = (
                float(obstacle["dimensions"]["width_m"])
                + float(actor["dimensions"]["width_m"])
            ) / 2.0
            if (
                obstacle["lane_id"] == spawn["lane_id"]
                and abs(
                    float(obstacle["longitudinal_m"])
                    - float(spawn["longitudinal_m"])
                )
                < longitudinal_limit
                and abs(
                    float(obstacle["lateral_m"])
                    - float(spawn["lateral_m"])
                )
                < lateral_limit
            ):
                add(
                    "spawn_obstacle_overlap",
                    f"$.static_obstacles[{obstacle_index}]",
                    "actor.spawn.non-overlap",
                    "an actor footprint overlaps a static obstacle at scenario start",
                    "separate actor and obstacle positions by their declared footprints",
                )
                break

    expected_sequences = list(range(len(events)))
    if [event["sequence"] for event in events] != expected_sequences:
        add(
            "event_sequence_invalid",
            "$.events",
            "event.ordered",
            "event sequence values must be contiguous and preserve author order",
            "number events from zero in execution order",
        )
    for event_index, event in enumerate(events):
        actor = actor_by_id.get(str(event["actor_id"]))
        if actor is None:
            add(
                "event_actor_missing",
                f"$.events[{event_index}].actor_id",
                "event.actor-reference",
                "the event references an actor that does not exist",
                "choose an existing stable actor identifier",
            )
        elif (
            event["action"]["kind"] == "vehicle_control"
            and actor["kind"] != "vehicle"
        ) or (
            event["action"]["kind"] == "pedestrian_speed"
            and actor["kind"] != "pedestrian"
        ):
            add(
                "event_action_kind_mismatch",
                f"$.events[{event_index}].action.kind",
                "event.actor-action",
                "the event action is incompatible with the referenced actor kind",
                "choose an action declared for the referenced actor kind",
            )
        if float(event["trigger"]["time_s"]) >= float(constraints["duration_s"]):
            add(
                "event_outside_duration",
                f"$.events[{event_index}].trigger.time_s",
                "event.executable",
                "the event cannot trigger before the scenario duration ends",
                "move the trigger before constraints.duration_s",
            )

    condition_ids: set[str] = set()
    for collection in ("success_conditions", "failure_conditions"):
        for condition_index, condition in enumerate(constraints[collection]):
            if condition["id"] in condition_ids:
                add(
                    "condition_identifier_conflict",
                    f"$.constraints.{collection}[{condition_index}].id",
                    "constraint.unambiguous",
                    "condition identifiers must be unique across success and failure",
                    "choose a unique stable condition identifier",
                )
            condition_ids.add(str(condition["id"]))
            for actor_index, actor_id in enumerate(condition["actor_ids"]):
                if actor_id not in actor_by_id:
                    add(
                        "constraint_actor_missing",
                        f"$.constraints.{collection}[{condition_index}].actor_ids[{actor_index}]",
                        "constraint.actor-reference",
                        "the constraint references an actor that does not exist",
                        "choose an existing stable actor identifier",
                    )
            route_id = condition["route_id"]
            if route_id is not None and route_id not in route_by_id:
                add(
                    "constraint_route_missing",
                    f"$.constraints.{collection}[{condition_index}].route_id",
                    "constraint.route-reference",
                    "the constraint references a route that does not exist",
                    "choose an existing stable route identifier",
                )

    for parameter_index, parameter in enumerate(value["parameters"]):
        distribution = parameter["distribution"]
        target = _resolve_target(value, str(parameter["target_path"]))
        if target is _MISSING or isinstance(target, bool) or not isinstance(
            target, (int, float)
        ):
            add(
                "parameter_target_missing",
                f"$.parameters[{parameter_index}].target_path",
                "parameter.target",
                "the parameter target does not resolve to an existing numeric field",
                "reference an existing numeric authoring field",
            )
        if distribution["kind"] in {"uniform", "normal"} and float(
            distribution["minimum"]
        ) > float(distribution["maximum"]):
            add(
                "distribution_bounds_invalid",
                f"$.parameters[{parameter_index}].distribution.minimum",
                "parameter.distribution",
                "the distribution minimum is greater than its maximum",
                "set minimum less than or equal to maximum",
            )
        if distribution["kind"] == "normal" and not (
            float(distribution["minimum"])
            <= float(distribution["mean"])
            <= float(distribution["maximum"])
        ):
            add(
                "distribution_mean_outside_bounds",
                f"$.parameters[{parameter_index}].distribution.mean",
                "parameter.distribution",
                "the normal distribution mean lies outside its declared bounds",
                "place the normal mean between minimum and maximum",
            )
        if (
            parameter["value_type"] == "integer"
            and distribution["kind"] in {"uniform", "normal"}
        ):
            add(
                "integer_distribution_requires_rounding",
                f"$.parameters[{parameter_index}].distribution",
                "parameter.integer-distribution",
                "a continuous distribution cannot preserve integer semantics exactly",
                "use fixed or choice with integer values for exact semantics",
                status=CapabilityStatus.LOSSY,
            )

    return diagnostics


def _deduplicate(
    diagnostics: Sequence[AuthoringDiagnostic],
) -> tuple[AuthoringDiagnostic, ...]:
    by_identity = {
        (item.path, item.code, item.capability): item for item in diagnostics
    }
    return tuple(
        sorted(by_identity.values(), key=lambda item: (item.path, item.code))
    )


def validate_authoring_spec(value: Any) -> AuthoringValidationReport:
    """Validate without normalization, mutation, backend imports, or exceptions."""

    diagnostics = _non_finite_diagnostics(value)
    if not diagnostics:
        diagnostics = _schema_validate(value)
    if not diagnostics and isinstance(value, Mapping):
        diagnostics.extend(_semantic_validate(value))
    frozen_diagnostics = _deduplicate(diagnostics)
    statuses = {item.status for item in frozen_diagnostics}
    if CapabilityStatus.UNSUPPORTED in statuses:
        overall_status = CapabilityStatus.UNSUPPORTED
    elif CapabilityStatus.LOSSY in statuses:
        overall_status = CapabilityStatus.LOSSY
    else:
        overall_status = CapabilityStatus.EXACT
    schema_version = (
        value.get("schema_version")
        if isinstance(value, Mapping) and isinstance(value.get("schema_version"), str)
        else None
    )
    return AuthoringValidationReport(
        schema_version="scenarioforge.authoring-validation/v1",
        document_schema_version=schema_version,
        valid=CapabilityStatus.UNSUPPORTED not in statuses,
        overall_status=overall_status,
        diagnostics=frozen_diagnostics,
    )
