"""Shared fixed observation adapter for Gymnasium and ONNX inference."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np


OBSERVATION_LOW = np.array(
    [-1.0, -1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    dtype=np.float32,
)
OBSERVATION_HIGH = np.array(
    [1.0, 1.0, 1.5, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
    dtype=np.float32,
)


def observation_vector(snapshot: Mapping[str, Any]) -> np.ndarray:
    """Convert one Python-authoritative snapshot into the frozen 10-vector."""

    ego = snapshot["ego"]
    construction = snapshot["construction"]
    target_lane = int(construction["target_lane_index"])
    ego_x = float(ego["position_m"]["x"])
    front = [
        float(vehicle["position_m"]["x"]) - ego_x
        for vehicle in snapshot["vehicles"]
        if int(vehicle["lane_index"]) == target_lane
        and float(vehicle["position_m"]["x"]) >= ego_x
    ]
    rear = [
        ego_x - float(vehicle["position_m"]["x"])
        for vehicle in snapshot["vehicles"]
        if int(vehicle["lane_index"]) == target_lane
        and float(vehicle["position_m"]["x"]) < ego_x
    ]
    ttc = snapshot["safety"]["min_ttc_s"]
    distance_to_construction = float(construction["zone_start_m"]) - ego_x
    values = np.array(
        [
            np.clip(distance_to_construction / 300.0, -1.0, 1.0),
            np.clip((float(construction["zone_end_m"]) - ego_x) / 300.0, -1.0, 1.0),
            np.clip(float(ego["speed_mps"]) / 40.0, 0.0, 1.5),
            float(int(ego["lane_index"]) == target_lane),
            float(any(gap < 15.0 for gap in front) or any(gap < 12.0 for gap in rear)),
            np.clip((min(front) if front else 100.0) / 100.0, 0.0, 1.0),
            np.clip((min(rear) if rear else 100.0) / 100.0, 0.0, 1.0),
            np.clip((float(ttc) if ttc is not None else 10.0) / 10.0, 0.0, 1.0),
            float(bool(snapshot["safety"]["collision"])),
            np.clip(float(snapshot["step"]) / 500.0, 0.0, 1.0),
        ],
        dtype=np.float32,
    )
    return values


__all__ = ["OBSERVATION_HIGH", "OBSERVATION_LOW", "observation_vector"]
