from __future__ import annotations

import bisect
import math
from collections.abc import Mapping, Sequence


class ReplayProjectionError(ValueError):
    """A public, stable failure raised for invalid replay projections."""


def _finite_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def normalize_heading_deg(value: float) -> float:
    if not _finite_number(value):
        raise ReplayProjectionError("heading is invalid")
    normalized = (float(value) + 180.0) % 360.0 - 180.0
    return 0.0 if normalized == 0.0 else normalized


def shortest_heading_delta_deg(start: float, end: float) -> float:
    if not _finite_number(start) or not _finite_number(end):
        raise ReplayProjectionError("heading is invalid")
    return normalize_heading_deg(float(end) - float(start))


def _sample_number(sample: Mapping[str, object], field: str) -> float:
    value = sample.get(field)
    if not _finite_number(value):
        raise ReplayProjectionError("trajectory sample is invalid")
    return float(value)


def _sample_position(sample: Mapping[str, object]) -> tuple[float, float]:
    value = sample.get("position_m")
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or len(value) != 2
        or not all(_finite_number(item) for item in value)
    ):
        raise ReplayProjectionError("trajectory sample is invalid")
    return float(value[0]), float(value[1])


def _tangent_for_pair(
    lower: Mapping[str, object], upper: Mapping[str, object]
) -> float | None:
    lower_position = _sample_position(lower)
    upper_position = _sample_position(upper)
    delta_x = upper_position[0] - lower_position[0]
    delta_y = upper_position[1] - lower_position[1]
    if math.hypot(delta_x, delta_y) < 1e-12:
        return None
    return normalize_heading_deg(math.degrees(math.atan2(delta_y, delta_x)))


def interpolate_pose(
    samples: Sequence[Mapping[str, object]], simulation_time_s: float
) -> dict[str, object]:
    """Interpolate display pose without replacing either evidence endpoint."""

    if not samples or not _finite_number(simulation_time_s):
        raise ReplayProjectionError("interpolation input is invalid")
    times: list[float] = []
    ticks: list[int] = []
    for sample in samples:
        time_value = sample.get("simulation_time_s")
        tick_value = sample.get("tick")
        if (
            not _finite_number(time_value)
            or not isinstance(tick_value, int)
            or isinstance(tick_value, bool)
            or tick_value < 0
        ):
            raise ReplayProjectionError("trajectory sample is invalid")
        times.append(float(time_value))
        ticks.append(tick_value)
    if times != sorted(times) or len(times) != len(set(times)):
        raise ReplayProjectionError("trajectory sample time is invalid")

    requested = min(max(float(simulation_time_s), times[0]), times[-1])
    upper_index = bisect.bisect_left(times, requested)
    if upper_index == 0:
        lower_index = upper_index = 0
        alpha = 0.0
    elif upper_index >= len(samples):
        lower_index = upper_index = len(samples) - 1
        alpha = 0.0
    elif times[upper_index] == requested:
        lower_index = upper_index
        alpha = 0.0
    else:
        lower_index = upper_index - 1
        span = times[upper_index] - times[lower_index]
        alpha = (requested - times[lower_index]) / span

    lower = samples[lower_index]
    upper = samples[upper_index]
    lower_position = _sample_position(lower)
    upper_position = _sample_position(upper)
    position = [
        lower_position[axis]
        + (upper_position[axis] - lower_position[axis]) * alpha
        for axis in (0, 1)
    ]
    lower_heading = _sample_number(lower, "heading_deg")
    upper_heading = _sample_number(upper, "heading_deg")
    heading = normalize_heading_deg(
        lower_heading + shortest_heading_delta_deg(lower_heading, upper_heading) * alpha
    )
    speed = _sample_number(lower, "speed_mps") + (
        _sample_number(upper, "speed_mps") - _sample_number(lower, "speed_mps")
    ) * alpha

    tangent: float | None
    if lower_index != upper_index:
        tangent = _tangent_for_pair(lower, upper)
    elif len(samples) == 1:
        tangent = None
    elif lower_index == len(samples) - 1:
        tangent = _tangent_for_pair(samples[lower_index - 1], lower)
    else:
        tangent = _tangent_for_pair(lower, samples[lower_index + 1])
    tangent_error = (
        None
        if tangent is None
        else abs(shortest_heading_delta_deg(tangent, heading))
    )
    # Discrete evidence state changes only when its recorded tick is reached.
    collision = bool(lower.get("collision"))
    heading_radians = math.radians(heading)
    return {
        "simulation_time_s": requested,
        "lower_tick": ticks[lower_index],
        "upper_tick": ticks[upper_index],
        "alpha": alpha,
        "position_m": position,
        "render_position_m": [position[0], 0.0, -position[1]],
        "heading_deg": heading,
        "render_yaw_rad": heading_radians,
        "speed_mps": speed,
        "collision": collision,
        "local_forward": [math.cos(heading_radians), math.sin(heading_radians)],
        "trajectory_tangent_deg": tangent,
        "heading_tangent_error_deg": tangent_error,
        "source_classification": "display-derived",
        "source_ticks": [ticks[lower_index], ticks[upper_index]],
    }


__all__ = [
    "ReplayProjectionError",
    "interpolate_pose",
    "normalize_heading_deg",
    "shortest_heading_delta_deg",
]
