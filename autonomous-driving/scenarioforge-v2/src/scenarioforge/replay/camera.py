from __future__ import annotations

import copy
import math
from collections.abc import Mapping, Sequence

from .contracts import VISUAL_REPLAY_TOLERANCE_V1
from .interpolation import ReplayProjectionError


P1_CAMERA_MODES = ("follow", "overview", "fixed", "free")
_MODE_ALIASES = {"ego-follow": "follow", **{mode: mode for mode in P1_CAMERA_MODES}}


def _finite(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _pair(value: object, label: str) -> tuple[float, float]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or len(value) != 2
        or not all(_finite(item) for item in value)
    ):
        raise ReplayProjectionError(f"{label} is invalid")
    return float(value[0]), float(value[1])


def _vector(value: object, label: str) -> list[float]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or len(value) != 3
        or not all(_finite(item) for item in value)
    ):
        raise ReplayProjectionError(f"{label} is invalid")
    return [float(item) for item in value]


def _target(value: object) -> tuple[list[float], float]:
    if not isinstance(value, Mapping):
        raise ReplayProjectionError("camera target is invalid")
    position = _pair(value.get("position_m"), "camera target")
    heading = value.get("heading_deg")
    if not _finite(heading):
        raise ReplayProjectionError("camera target is invalid")
    return [position[0], 0.0, -position[1]], float(heading)


def _bounds(value: object) -> tuple[list[float], list[float]]:
    if not isinstance(value, Mapping):
        raise ReplayProjectionError("camera bounds are invalid")
    center = _pair(value.get("center_m"), "camera bounds")
    half_extents = _pair(value.get("half_extents_m"), "camera bounds")
    if half_extents[0] <= 0 or half_extents[1] <= 0:
        raise ReplayProjectionError("camera bounds are invalid")
    return [center[0], 0.0, -center[1]], [half_extents[0], half_extents[1]]


def _angles(position: Sequence[float], look_at: Sequence[float]) -> tuple[float, float, float]:
    offset = [position[index] - look_at[index] for index in range(3)]
    distance = math.sqrt(sum(value * value for value in offset))
    if distance <= 0:
        raise ReplayProjectionError("camera state is invalid")
    yaw = math.degrees(math.atan2(offset[0], offset[2]))
    pitch = math.degrees(math.asin(max(-1.0, min(1.0, offset[1] / distance))))
    return yaw, pitch, distance


def _state(mode: str, position: Sequence[float], look_at: Sequence[float]) -> dict[str, object]:
    projected_position = _vector(position, "camera state")
    projected_look_at = _vector(look_at, "camera state")
    yaw, pitch, distance = _angles(projected_position, projected_look_at)
    return {
        "schema_version": "scenarioforge.replay-camera-state/v1",
        "mode": mode,
        "position": projected_position,
        "look_at": projected_look_at,
        "yaw_deg": yaw,
        "pitch_deg": pitch,
        "distance_m": distance,
        "initialized": True,
    }


def _orbital_state(
    mode: str, look_at: Sequence[float], yaw: float, pitch: float, distance: float
) -> dict[str, object]:
    if not all(_finite(value) for value in (yaw, pitch, distance)) or distance <= 0:
        raise ReplayProjectionError("camera input is invalid")
    pitch = min(85.0, max(-20.0, float(pitch)))
    distance = min(500.0, max(2.0, float(distance)))
    yaw_radians = math.radians(float(yaw))
    pitch_radians = math.radians(pitch)
    horizontal = math.cos(pitch_radians) * distance
    position = [
        float(look_at[0]) + math.sin(yaw_radians) * horizontal,
        float(look_at[1]) + math.sin(pitch_radians) * distance,
        float(look_at[2]) + math.cos(yaw_radians) * horizontal,
    ]
    return _state(mode, position, look_at)


def create_camera_state(
    mode: str,
    *,
    target_pose: Mapping[str, object],
    bounds: Mapping[str, object],
) -> dict[str, object]:
    normalized_mode = _MODE_ALIASES.get(mode)
    if normalized_mode is None:
        raise ReplayProjectionError("camera mode is invalid")
    target, heading = _target(target_pose)
    center, half_extents = _bounds(bounds)
    if normalized_mode == "follow":
        heading_radians = math.radians(heading)
        forward = [math.cos(heading_radians), 0.0, -math.sin(heading_radians)]
        tolerance = VISUAL_REPLAY_TOLERANCE_V1
        position = [
            target[0] - forward[0] * tolerance.rear_offset_m,
            tolerance.height_offset_m,
            target[2] - forward[2] * tolerance.rear_offset_m,
        ]
        look_at = [
            target[0] + forward[0] * tolerance.look_ahead_m,
            0.0,
            target[2] + forward[2] * tolerance.look_ahead_m,
        ]
        return _state(normalized_mode, position, look_at)
    extent = max(half_extents)
    if normalized_mode == "overview":
        distance = max(24.0, extent * 1.8)
        return _orbital_state(normalized_mode, center, 0.0, 58.0, distance)
    if normalized_mode == "fixed":
        return _state(normalized_mode, [-16.0, 14.0, 18.0], center)
    distance = max(20.0, extent * 1.2)
    return _orbital_state(normalized_mode, center, 25.0, 32.0, distance)


def switch_camera_mode(
    state: Mapping[str, object],
    mode: str,
    *,
    target_pose: Mapping[str, object],
    bounds: Mapping[str, object],
) -> dict[str, object]:
    _validated_state(state)
    return create_camera_state(mode, target_pose=target_pose, bounds=bounds)


def _validated_state(value: Mapping[str, object]) -> dict[str, object]:
    if (
        not isinstance(value, Mapping)
        or value.get("schema_version") != "scenarioforge.replay-camera-state/v1"
        or value.get("mode") not in P1_CAMERA_MODES
        or value.get("initialized") is not True
        or not all(_finite(value.get(field)) for field in ("yaw_deg", "pitch_deg", "distance_m"))
    ):
        raise ReplayProjectionError("camera state is invalid")
    projected = dict(value)
    projected["position"] = _vector(value.get("position"), "camera state")
    projected["look_at"] = _vector(value.get("look_at"), "camera state")
    return projected


def apply_camera_input(
    state: Mapping[str, object], camera_input: Mapping[str, object]
) -> dict[str, object]:
    current = _validated_state(state)
    if not isinstance(camera_input, Mapping) or not isinstance(camera_input.get("kind"), str):
        raise ReplayProjectionError("camera input is invalid")
    if camera_input.get("trusted") is not True:
        return copy.deepcopy(current)
    if current["mode"] != "free":
        return copy.deepcopy(current)
    kind = camera_input["kind"]
    yaw = float(current["yaw_deg"])
    pitch = float(current["pitch_deg"])
    distance = float(current["distance_m"])
    look_at = list(current["look_at"])
    if kind == "pointer":
        action = camera_input.get("action")
        delta_x = camera_input.get("delta_x")
        delta_y = camera_input.get("delta_y")
        if action not in {"rotate", "pan"} or not _finite(delta_x) or not _finite(delta_y):
            raise ReplayProjectionError("camera input is invalid")
        if action == "rotate":
            yaw -= float(delta_x) * 0.25
            pitch += float(delta_y) * 0.25
        else:
            scale = max(0.01, distance * 0.0025)
            yaw_radians = math.radians(yaw)
            look_at[0] -= math.cos(yaw_radians) * float(delta_x) * scale
            look_at[2] += math.sin(yaw_radians) * float(delta_x) * scale
            look_at[1] += float(delta_y) * scale
    elif kind == "wheel":
        delta_y = camera_input.get("delta_y")
        if not _finite(delta_y):
            raise ReplayProjectionError("camera input is invalid")
        distance *= math.exp(float(delta_y) * 0.001)
    elif kind == "keyboard":
        key = camera_input.get("key")
        if not isinstance(key, str):
            raise ReplayProjectionError("camera input is invalid")
        step = max(0.5, distance * 0.04)
        yaw_radians = math.radians(yaw)
        if key in {"w", "W", "s", "S"}:
            sign = 1.0 if key.lower() == "w" else -1.0
            look_at[0] -= math.sin(yaw_radians) * step * sign
            look_at[2] -= math.cos(yaw_radians) * step * sign
        elif key in {"a", "A", "d", "D"}:
            sign = -1.0 if key.lower() == "a" else 1.0
            look_at[0] += math.cos(yaw_radians) * step * sign
            look_at[2] -= math.sin(yaw_radians) * step * sign
        elif key in {"q", "Q", "e", "E"}:
            look_at[1] += step * (1.0 if key.lower() == "e" else -1.0)
        elif key == "ArrowLeft":
            yaw += 4.0
        elif key == "ArrowRight":
            yaw -= 4.0
        elif key == "ArrowUp":
            pitch += 4.0
        elif key == "ArrowDown":
            pitch -= 4.0
        else:
            return copy.deepcopy(current)
    else:
        raise ReplayProjectionError("camera input is invalid")
    return _orbital_state("free", look_at, yaw, pitch, distance)


def _angle_between(left: Sequence[float], right: Sequence[float]) -> float:
    left_length = math.sqrt(sum(value * value for value in left))
    right_length = math.sqrt(sum(value * value for value in right))
    if left_length <= 0 or right_length <= 0:
        raise ReplayProjectionError("camera state is invalid")
    cosine = sum(a * b for a, b in zip(left, right)) / (left_length * right_length)
    return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))


def camera_quality(
    state: Mapping[str, object], target_pose: Mapping[str, object]
) -> dict[str, object]:
    current = _validated_state(state)
    if current["mode"] != "follow":
        raise ReplayProjectionError("follow camera state is required")
    desired = create_camera_state(
        "follow",
        target_pose=target_pose,
        bounds={"center_m": [0.0, 0.0], "half_extents_m": [1.0, 1.0]},
    )
    error = math.sqrt(
        sum(
            (float(current["position"][index]) - float(desired["position"][index])) ** 2
            for index in range(3)
        )
    )
    current_direction = [
        float(current["look_at"][index]) - float(current["position"][index])
        for index in range(3)
    ]
    desired_direction = [
        float(desired["look_at"][index]) - float(desired["position"][index])
        for index in range(3)
    ]
    direction_error = _angle_between(current_direction, desired_direction)
    if error < 1e-9:
        error = 0.0
    if direction_error < 1e-9:
        direction_error = 0.0
    return {
        "follow_target_error_m": round(error, 6),
        "view_direction_error_deg": round(direction_error, 6),
        "within_tolerance": (
            error <= VISUAL_REPLAY_TOLERANCE_V1.max_follow_error_m
            and direction_error
            <= VISUAL_REPLAY_TOLERANCE_V1.max_look_direction_error_deg
        ),
    }


__all__ = [
    "P1_CAMERA_MODES",
    "apply_camera_input",
    "camera_quality",
    "create_camera_state",
    "switch_camera_mode",
]
