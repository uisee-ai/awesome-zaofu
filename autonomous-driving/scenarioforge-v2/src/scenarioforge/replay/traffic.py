from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

from .interpolation import (
    ReplayProjectionError,
    normalize_heading_deg,
    shortest_heading_delta_deg,
)


_SCHEMA = "scenarioforge.right-hand-traffic/v1"
_COORDINATE_SYSTEM = "right-handed-x-forward-y-left"
_TOP_LEVEL_FIELDS = {
    "schema_version",
    "traffic_side",
    "coordinate_system",
    "yellow_line",
    "model_instances",
    "lanes",
    "routes",
    "samples",
}
_LANE_FIELDS = {
    "lane_id",
    "kind",
    "carriageway_id",
    "travel_direction_deg",
    "center_offset_m",
    "width_m",
    "centerline_m",
    "predecessor_lane_ids",
    "successor_lane_ids",
}
_ROUTE_FIELDS = {"participant_id", "role", "lane_ids"}
_SAMPLE_FIELDS = {
    "tick",
    "participant_id",
    "lane_id",
    "position_m",
    "heading_deg",
    "speed_mps",
    "brake",
}
_DIMENSIONS = {"length", "width", "height"}
_VEHICLE_ROLES = {"ego", "controlled", "controlled_agent", "social", "social_vehicle"}
_MODEL_SCALE_ERROR_MAX = 0.02
_LANE_CENTER_ERROR_M_MAX = 0.25
_YELLOW_LINE_EPSILON_M_MAX = 0.02
_HEADING_TANGENT_ERROR_DEG_MAX = 10.0
_EPSILON = 1e-9


def _finite(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _identifier(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 128
        or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for character in value)
    ):
        raise ReplayProjectionError(f"{label} is invalid")
    return value


def _point(value: object, label: str) -> tuple[float, float]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or len(value) != 2
        or not all(_finite(item) for item in value)
    ):
        raise ReplayProjectionError(f"{label} is invalid")
    return float(value[0]), float(value[1])


def _centerline(value: object) -> list[tuple[float, float]]:
    if not isinstance(value, list) or not 2 <= len(value) <= 512:
        raise ReplayProjectionError("lane centerline is invalid")
    points = [_point(item, "lane centerline") for item in value]
    if any(left == right for left, right in zip(points, points[1:])):
        raise ReplayProjectionError("lane centerline is invalid")
    return points


def _string_list(
    value: object, label: str, *, allow_duplicates: bool = False
) -> list[str]:
    if not isinstance(value, list):
        raise ReplayProjectionError(f"{label} is invalid")
    values = [_identifier(item, label) for item in value]
    if not allow_duplicates and len(values) != len(set(values)):
        raise ReplayProjectionError(f"{label} is invalid")
    return values


def _distance_to_segment(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    delta_x = end[0] - start[0]
    delta_y = end[1] - start[1]
    length_squared = delta_x * delta_x + delta_y * delta_y
    projection = (
        (point[0] - start[0]) * delta_x + (point[1] - start[1]) * delta_y
    ) / length_squared
    clamped = min(1.0, max(0.0, projection))
    nearest = (start[0] + clamped * delta_x, start[1] + clamped * delta_y)
    return math.hypot(point[0] - nearest[0], point[1] - nearest[1])


def _distance_to_polyline(
    point: tuple[float, float], centerline: Sequence[tuple[float, float]]
) -> float:
    return min(
        _distance_to_segment(point, start, end)
        for start, end in zip(centerline, centerline[1:])
    )


def _model_scale_error(value: object) -> float:
    if not isinstance(value, list) or not value:
        raise ReplayProjectionError("model scale evidence is invalid")
    observed = 0.0
    participant_ids: list[str] = []
    for model in value:
        if not isinstance(model, Mapping) or set(model) != {
            "participant_id",
            "role",
            "declared_dimensions_m",
            "render_dimensions_m",
        }:
            raise ReplayProjectionError("model scale evidence is invalid")
        participant_ids.append(_identifier(model["participant_id"], "participant id"))
        if model["role"] not in _VEHICLE_ROLES | {"pedestrian"}:
            raise ReplayProjectionError("participant role is invalid")
        declared = model["declared_dimensions_m"]
        rendered = model["render_dimensions_m"]
        if (
            not isinstance(declared, Mapping)
            or not isinstance(rendered, Mapping)
            or set(declared) != _DIMENSIONS
            or set(rendered) != _DIMENSIONS
        ):
            raise ReplayProjectionError("model scale evidence is invalid")
        for dimension in sorted(_DIMENSIONS):
            expected = declared[dimension]
            actual = rendered[dimension]
            if not _finite(expected) or float(expected) <= 0 or not _finite(actual):
                raise ReplayProjectionError("model scale evidence is invalid")
            error = abs(float(actual) - float(expected)) / float(expected)
            observed = max(observed, error)
    if len(participant_ids) != len(set(participant_ids)):
        raise ReplayProjectionError("model scale evidence is invalid")
    if observed > _MODEL_SCALE_ERROR_MAX + _EPSILON:
        raise ReplayProjectionError("model scale error exceeds 2 percent")
    return observed


def _lanes(value: object) -> tuple[list[dict[str, object]], dict[str, dict[str, object]]]:
    if not isinstance(value, list) or not value:
        raise ReplayProjectionError("right-hand lane graph is invalid")
    lanes: list[dict[str, object]] = []
    for raw in value:
        if not isinstance(raw, Mapping) or set(raw) != _LANE_FIELDS:
            raise ReplayProjectionError("right-hand lane graph is invalid")
        lane_id = _identifier(raw["lane_id"], "lane id")
        kind = raw["kind"]
        if kind not in {"travel", "intersection_connector"}:
            raise ReplayProjectionError("lane kind is invalid")
        carriageway_id = _identifier(raw["carriageway_id"], "carriageway id")
        direction = raw["travel_direction_deg"]
        offset = raw["center_offset_m"]
        width = raw["width_m"]
        if (
            not _finite(direction)
            or not _finite(offset)
            or not _finite(width)
            or float(width) <= 0
        ):
            raise ReplayProjectionError("right-hand lane geometry is invalid")
        if kind == "travel" and float(offset) >= 0:
            raise ReplayProjectionError("left-side carriageway is not legal right-hand traffic")
        lanes.append(
            {
                "lane_id": lane_id,
                "kind": kind,
                "carriageway_id": carriageway_id,
                "travel_direction_deg": normalize_heading_deg(float(direction)),
                "center_offset_m": float(offset),
                "width_m": float(width),
                "centerline_m": _centerline(raw["centerline_m"]),
                "predecessor_lane_ids": _string_list(
                    raw["predecessor_lane_ids"], "predecessor lane ids"
                ),
                "successor_lane_ids": _string_list(
                    raw["successor_lane_ids"], "successor lane ids"
                ),
            }
        )
    lane_ids = [str(lane["lane_id"]) for lane in lanes]
    if len(lane_ids) != len(set(lane_ids)):
        raise ReplayProjectionError("right-hand lane graph is invalid")
    by_id = {str(lane["lane_id"]): lane for lane in lanes}
    for lane in lanes:
        lane_id = str(lane["lane_id"])
        predecessors = lane["predecessor_lane_ids"]
        successors = lane["successor_lane_ids"]
        assert isinstance(predecessors, list) and isinstance(successors, list)
        if any(item not in by_id for item in predecessors + successors):
            raise ReplayProjectionError("right-hand lane graph is invalid")
        if any(lane_id not in by_id[item]["successor_lane_ids"] for item in predecessors):
            raise ReplayProjectionError("right-hand lane graph is invalid")
        if any(lane_id not in by_id[item]["predecessor_lane_ids"] for item in successors):
            raise ReplayProjectionError("right-hand lane graph is invalid")
        if lane["kind"] == "intersection_connector" and (
            not predecessors or not successors
        ):
            raise ReplayProjectionError("intersection connector is invalid")
    return lanes, by_id


def _routes(
    value: object, lanes_by_id: Mapping[str, Mapping[str, object]]
) -> list[dict[str, object]]:
    if not isinstance(value, list) or not value:
        raise ReplayProjectionError("right-hand routes are invalid")
    projected: list[dict[str, object]] = []
    participant_ids: list[str] = []
    for route in value:
        if not isinstance(route, Mapping) or set(route) != _ROUTE_FIELDS:
            raise ReplayProjectionError("right-hand route is invalid")
        participant_id = _identifier(route["participant_id"], "participant id")
        participant_ids.append(participant_id)
        role = route["role"]
        if role not in _VEHICLE_ROLES:
            raise ReplayProjectionError("participant role is invalid")
        lane_ids = _string_list(
            route["lane_ids"], "route lane ids", allow_duplicates=True
        )
        if not lane_ids or any(lane_id not in lanes_by_id for lane_id in lane_ids):
            raise ReplayProjectionError("right-hand route is invalid")
        for previous_id, current_id in zip(lane_ids, lane_ids[1:]):
            previous = lanes_by_id[previous_id]
            current = lanes_by_id[current_id]
            if current["kind"] == "intersection_connector" and previous_id not in current["predecessor_lane_ids"]:
                raise ReplayProjectionError("wrong turn entry lane")
            if previous["kind"] == "intersection_connector" and current_id not in previous["successor_lane_ids"]:
                raise ReplayProjectionError("wrong receiving lane")
            if current_id not in previous["successor_lane_ids"]:
                raise ReplayProjectionError("route lane transition is invalid")
        receiving = next(
            (
                lane_ids[index + 1]
                for index, lane_id in enumerate(lane_ids[:-1])
                if lanes_by_id[lane_id]["kind"] == "intersection_connector"
            ),
            lane_ids[-1],
        )
        projected.append(
            {
                "participant_id": participant_id,
                "role": str(role),
                "lane_ids": lane_ids,
                "receiving_lane_id": receiving,
            }
        )
    if len(participant_ids) != len(set(participant_ids)):
        raise ReplayProjectionError("right-hand routes are invalid")
    return projected


def _samples(
    value: object,
    lanes_by_id: Mapping[str, Mapping[str, object]],
    routes: Sequence[Mapping[str, object]],
) -> tuple[float, float]:
    if not isinstance(value, list) or not value:
        raise ReplayProjectionError("traffic samples are invalid")
    routes_by_participant = {str(route["participant_id"]): route for route in routes}
    samples_by_participant: dict[str, list[dict[str, object]]] = {
        participant_id: [] for participant_id in routes_by_participant
    }
    lane_center_error = 0.0
    for sample in value:
        if not isinstance(sample, Mapping) or set(sample) != _SAMPLE_FIELDS:
            raise ReplayProjectionError("traffic sample is invalid")
        tick = sample["tick"]
        participant_id = sample["participant_id"]
        lane_id = sample["lane_id"]
        if (
            not isinstance(tick, int)
            or isinstance(tick, bool)
            or tick < 0
            or participant_id not in routes_by_participant
            or lane_id not in lanes_by_id
            or lane_id not in routes_by_participant[str(participant_id)]["lane_ids"]
            or not _finite(sample["heading_deg"])
            or not _finite(sample["speed_mps"])
            or float(sample["speed_mps"]) < 0
            or not _finite(sample["brake"])
            or not 0 <= float(sample["brake"]) <= 1
        ):
            raise ReplayProjectionError("traffic sample is invalid")
        position = _point(sample["position_m"], "traffic sample position")
        centerline = lanes_by_id[str(lane_id)]["centerline_m"]
        assert isinstance(centerline, list)
        lane_center_error = max(
            lane_center_error, _distance_to_polyline(position, centerline)
        )
        samples_by_participant[str(participant_id)].append(
            {
                "tick": tick,
                "lane_id": str(lane_id),
                "position_m": position,
                "heading_deg": normalize_heading_deg(float(sample["heading_deg"])),
            }
        )
    if lane_center_error > _LANE_CENTER_ERROR_M_MAX + _EPSILON:
        raise ReplayProjectionError("lane-center error exceeds 0.25 m")

    heading_error = 0.0
    for participant_id, samples in samples_by_participant.items():
        if not samples:
            raise ReplayProjectionError("traffic samples are invalid")
        ticks = [int(sample["tick"]) for sample in samples]
        if ticks != sorted(set(ticks)):
            raise ReplayProjectionError("traffic samples are not ordered")
        if len(samples) == 1:
            sample = samples[0]
            lane = lanes_by_id[str(sample["lane_id"])]
            heading_error = max(
                heading_error,
                abs(
                    shortest_heading_delta_deg(
                        float(lane["travel_direction_deg"]),
                        float(sample["heading_deg"]),
                    )
                ),
            )
        else:
            for index, sample in enumerate(samples):
                adjacent = samples[index + 1] if index < len(samples) - 1 else samples[index - 1]
                start = sample["position_m"] if index < len(samples) - 1 else adjacent["position_m"]
                end = adjacent["position_m"] if index < len(samples) - 1 else sample["position_m"]
                assert isinstance(start, tuple) and isinstance(end, tuple)
                tangent = math.degrees(math.atan2(end[1] - start[1], end[0] - start[0]))
                heading_error = max(
                    heading_error,
                    abs(shortest_heading_delta_deg(tangent, float(sample["heading_deg"]))),
                )
        if heading_error > _HEADING_TANGENT_ERROR_DEG_MAX + _EPSILON:
            raise ReplayProjectionError(
                f"wrong-way traffic sample for participant {participant_id}"
            )
    return lane_center_error, heading_error


def _rounded(value: float) -> float:
    rounded = round(value, 6)
    return 0.0 if abs(rounded) < 1e-6 else rounded


def validate_right_hand_traffic(value: Mapping[str, object]) -> dict[str, object]:
    """Validate deterministic right-hand road, route, model and motion evidence."""

    if not isinstance(value, Mapping) or set(value) != _TOP_LEVEL_FIELDS:
        raise ReplayProjectionError("right-hand traffic contract is invalid")
    if value["schema_version"] != _SCHEMA or value["traffic_side"] != "right":
        raise ReplayProjectionError("right-hand traffic is required")
    if value["coordinate_system"] != _COORDINATE_SYSTEM:
        raise ReplayProjectionError("right-hand traffic coordinate system is invalid")
    yellow_line = value["yellow_line"]
    if (
        not isinstance(yellow_line, Mapping)
        or set(yellow_line) != {"footprint_epsilon_m"}
        or not _finite(yellow_line["footprint_epsilon_m"])
        or float(yellow_line["footprint_epsilon_m"]) < 0
    ):
        raise ReplayProjectionError("yellow-line footprint evidence is invalid")
    yellow_epsilon = float(yellow_line["footprint_epsilon_m"])
    if yellow_epsilon > _YELLOW_LINE_EPSILON_M_MAX + _EPSILON:
        raise ReplayProjectionError("yellow-line footprint epsilon exceeds 0.02 m")
    scale_error = _model_scale_error(value["model_instances"])
    lanes, lanes_by_id = _lanes(value["lanes"])
    routes = _routes(value["routes"], lanes_by_id)
    lane_error, heading_error = _samples(value["samples"], lanes_by_id, routes)
    connectors = [
        {
            "lane_id": lane["lane_id"],
            "predecessor_lane_ids": lane["predecessor_lane_ids"],
            "successor_lane_ids": lane["successor_lane_ids"],
        }
        for lane in lanes
        if lane["kind"] == "intersection_connector"
    ]
    carriageways = sorted(
        {
            str(lane["carriageway_id"])
            for lane in lanes
            if lane["kind"] == "travel"
        }
    )
    return {
        "schema_version": "scenarioforge.right-hand-traffic-validation/v1",
        "traffic_side": "right",
        "coordinate_system": _COORDINATE_SYSTEM,
        "lane_ids": [lane["lane_id"] for lane in lanes],
        "carriageway_ids": carriageways,
        "intersection_connectors": connectors,
        "route_bindings": routes,
        "tolerances": {
            "model_scale_relative_error_max": _MODEL_SCALE_ERROR_MAX,
            "lane_center_error_m_max": _LANE_CENTER_ERROR_M_MAX,
            "yellow_line_footprint_epsilon_m_max": _YELLOW_LINE_EPSILON_M_MAX,
            "heading_tangent_error_deg_max": _HEADING_TANGENT_ERROR_DEG_MAX,
        },
        "observed": {
            "model_scale_relative_error_max": _rounded(scale_error),
            "lane_center_error_m_max": _rounded(lane_error),
            "yellow_line_footprint_epsilon_m": _rounded(yellow_epsilon),
            "heading_tangent_error_deg_max": _rounded(heading_error),
        },
    }


__all__ = ["validate_right_hand_traffic"]
