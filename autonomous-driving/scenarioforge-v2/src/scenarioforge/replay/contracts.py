from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class VisualReplayTolerance:
    schema_version: str = "scenarioforge.visual-replay-tolerance/v1"
    rear_offset_m: float = 8.0
    height_offset_m: float = 4.0
    look_ahead_m: float = 12.0
    damping_half_life_ms: float = 150.0
    settle_time_s: float = 0.5
    max_follow_error_m: float = 2.0
    max_look_direction_error_deg: float = 5.0
    minimum_tangent_displacement_m_per_tick: float = 0.25
    max_heading_tangent_error_deg: float = 10.0
    max_frame_time_p95_ms: float = 33.0

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "follow_camera": {
                "rear_offset_m": self.rear_offset_m,
                "height_offset_m": self.height_offset_m,
                "look_ahead_m": self.look_ahead_m,
                "damping_half_life_ms": self.damping_half_life_ms,
                "settle_time_s": self.settle_time_s,
                "max_follow_error_m": self.max_follow_error_m,
                "max_look_direction_error_deg": (
                    self.max_look_direction_error_deg
                ),
            },
            "pose": {
                "minimum_tangent_displacement_m_per_tick": (
                    self.minimum_tangent_displacement_m_per_tick
                ),
                "max_heading_tangent_error_deg": (
                    self.max_heading_tangent_error_deg
                ),
                "heading_interpolation": "shortest-wrapped-arc",
                "local_forward_axis": "+x",
            },
            "performance": {
                "max_frame_time_p95_ms": self.max_frame_time_p95_ms
            },
        }


VISUAL_REPLAY_TOLERANCE_V1 = VisualReplayTolerance()


COORDINATE_CONTRACT_V1: dict[str, object] = {
    "schema_version": "scenarioforge.replay-coordinate/v1",
    "evidence_coordinate_system": "right-handed-x-forward-y-left",
    "renderer_coordinate_system": "right-handed-x-forward-y-up",
    "evidence_position_axes": ["x-forward", "y-left"],
    "renderer_position_mapping": ["x", "elevation", "-y"],
    "heading_unit": "deg",
    "heading_rotation_axis": "+y",
    "heading_rotation_sign": 1,
    "local_forward_axis": "+x",
    "stable_horizon_axis": "+y",
}


__all__ = [
    "COORDINATE_CONTRACT_V1",
    "VISUAL_REPLAY_TOLERANCE_V1",
    "VisualReplayTolerance",
]
