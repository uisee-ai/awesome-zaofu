from __future__ import annotations

import json
from pathlib import Path

import pytest

from scenarioforge.replay import (
    ReplayProjectionError,
    replay_availability,
    rendering_failure,
)


ROOT = Path(__file__).resolve().parents[2]
REPLAY_MODULE = ROOT / "src" / "scenarioforge" / "replay" / "replay_scene.js"


@pytest.mark.parametrize(
    ("terminal", "expected"),
    [
        (
            {
                "terminal": True,
                "execution_status": "completed",
                "playable": True,
            },
            {
                "schema_version": "scenarioforge.replay-availability/v1",
                "state": "ready",
                "accessible_message": "Verified replay is ready.",
                "controls_enabled": True,
                "request_playback": True,
            },
        ),
        (
            {"terminal": True, "execution_status": "cancelled", "playable": False},
            {
                "schema_version": "scenarioforge.replay-availability/v1",
                "state": "cancelled",
                "accessible_message": "Cancelled runs do not have a replay.",
                "controls_enabled": False,
                "request_playback": False,
            },
        ),
        (
            {"terminal": False, "state": "running"},
            {
                "schema_version": "scenarioforge.replay-availability/v1",
                "state": "incomplete",
                "accessible_message": "Replay is available after verified completion.",
                "controls_enabled": False,
                "request_playback": False,
            },
        ),
        (
            {
                "terminal": True,
                "status": "success",
                "playable": False,
                "playback_reason": "trajectory_not_fully_verified",
            },
            {
                "schema_version": "scenarioforge.replay-availability/v1",
                "state": "unavailable",
                "accessible_message": "No fully verified trajectory is available.",
                "controls_enabled": False,
                "request_playback": False,
            },
        ),
    ],
)
def test_availability_is_explicit_and_cancelled_never_requests_trajectory(
    terminal: dict[str, object], expected: dict[str, object]
) -> None:
    assert replay_availability(terminal) == expected


def test_invalid_terminal_and_webgl_failures_are_accessible_and_fail_closed() -> None:
    with pytest.raises(ReplayProjectionError, match="terminal projection"):
        replay_availability({"terminal": True, "playable": "yes"})

    assert rendering_failure("webgl_context_lost") == {
        "schema_version": "scenarioforge.replay-availability/v1",
        "state": "rendering-failed",
        "accessible_message": (
            "3D replay is unavailable because the WebGL context was lost."
        ),
        "controls_enabled": False,
        "request_playback": False,
        "reason": "webgl_context_lost",
    }


def test_browser_module_declares_no_remote_or_dynamic_code_surface() -> None:
    source = REPLAY_MODULE.read_text(encoding="utf-8")
    lowered = source.lower()

    for required in (
        "projectReplayScene",
        "interpolatePose",
        "createFollowCameraState",
        "replayAvailability",
        "renderReplayFailure",
        "frameTimeP95",
        "scenarioforge.visual-replay-tolerance/v1",
        "shortest-wrapped-arc",
        "ego-follow",
    ):
        assert required in source
    for forbidden in (
        "http://",
        "https://",
        "eval(",
        "new function",
        "innerhtml",
        "insertadjacenthtml",
        "document.write",
        "websocket",
    ):
        assert forbidden not in lowered


def test_projection_errors_are_stable_json_safe_messages() -> None:
    error = ReplayProjectionError("trajectory sample is invalid")

    encoded = json.dumps({"detail": str(error)})

    assert encoded == '{"detail": "trajectory sample is invalid"}'
    assert "/home/" not in encoded
    assert "<script" not in encoded
