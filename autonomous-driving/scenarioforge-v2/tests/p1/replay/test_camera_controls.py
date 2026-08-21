from __future__ import annotations

import math

import pytest

from scenarioforge.replay import (
    ReplayProjectionError,
    apply_camera_input,
    camera_quality,
    create_camera_state,
    switch_camera_mode,
)


TARGET = {"position_m": [10.0, 2.0], "heading_deg": 0.0}
BOUNDS = {"center_m": [0.0, 0.0], "half_extents_m": [30.0, 12.0]}


def _all_numbers(value: object) -> list[float]:
    if isinstance(value, dict):
        return [number for item in value.values() for number in _all_numbers(item)]
    if isinstance(value, list):
        return [number for item in value for number in _all_numbers(item)]
    return [float(value)] if isinstance(value, (int, float)) else []


def test_all_four_camera_modes_initialize_without_blank_or_nan_state() -> None:
    states = [
        create_camera_state(mode, target_pose=TARGET, bounds=BOUNDS)
        for mode in ("follow", "overview", "fixed", "free")
    ]

    assert [state["mode"] for state in states] == [
        "follow",
        "overview",
        "fixed",
        "free",
    ]
    assert states[0]["position"] == [2.0, 4.0, -2.0]
    assert states[0]["look_at"] == [22.0, 0.0, -2.0]
    assert all(state["initialized"] is True for state in states)
    assert all(math.isfinite(number) for state in states for number in _all_numbers(state))
    assert camera_quality(states[0], TARGET) == {
        "follow_target_error_m": 0.0,
        "view_direction_error_deg": 0.0,
        "within_tolerance": True,
    }


def test_switch_rotate_pan_zoom_and_keyboard_keep_finite_initialized_state() -> None:
    state = create_camera_state("follow", target_pose=TARGET, bounds=BOUNDS)
    for mode in ("overview", "fixed", "free", "follow"):
        state = switch_camera_mode(
            state, mode, target_pose=TARGET, bounds=BOUNDS
        )
        assert state["mode"] == mode
        assert state["initialized"] is True

    state = switch_camera_mode(state, "free", target_pose=TARGET, bounds=BOUNDS)
    for camera_input in (
        {"kind": "pointer", "action": "rotate", "delta_x": 30.0, "delta_y": -12.0, "trusted": True},
        {"kind": "pointer", "action": "pan", "delta_x": 8.0, "delta_y": 4.0, "trusted": True},
        {"kind": "wheel", "delta_y": -120.0, "trusted": True},
        {"kind": "keyboard", "key": "w", "trusted": True},
        {"kind": "keyboard", "key": "ArrowLeft", "trusted": True},
    ):
        state = apply_camera_input(state, camera_input)
        assert state["initialized"] is True
        assert all(math.isfinite(number) for number in _all_numbers(state))

    untrusted = apply_camera_input(
        state,
        {"kind": "wheel", "delta_y": 500.0, "trusted": False},
    )
    assert untrusted == state


def test_camera_state_fails_closed_for_unknown_mode_or_non_finite_input() -> None:
    with pytest.raises(ReplayProjectionError, match="camera mode"):
        create_camera_state("cinematic", target_pose=TARGET, bounds=BOUNDS)
    state = create_camera_state("free", target_pose=TARGET, bounds=BOUNDS)
    with pytest.raises(ReplayProjectionError, match="camera input"):
        apply_camera_input(
            state,
            {"kind": "pointer", "action": "rotate", "delta_x": float("nan"), "delta_y": 0.0, "trusted": True},
        )
