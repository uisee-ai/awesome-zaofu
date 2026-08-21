from __future__ import annotations

from collections.abc import Mapping

from .interpolation import ReplayProjectionError


def _state(
    name: str,
    message: str,
    *,
    controls_enabled: bool = False,
    request_playback: bool = False,
) -> dict[str, object]:
    return {
        "schema_version": "scenarioforge.replay-availability/v1",
        "state": name,
        "accessible_message": message,
        "controls_enabled": controls_enabled,
        "request_playback": request_playback,
    }


def replay_availability(terminal: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(terminal, Mapping):
        raise ReplayProjectionError("terminal projection is invalid")
    playable = terminal.get("playable")
    if playable is not None and not isinstance(playable, bool):
        raise ReplayProjectionError("terminal projection is invalid")
    status = terminal.get(
        "execution_status", terminal.get("status", terminal.get("state"))
    )
    if status == "cancelled":
        return _state("cancelled", "Cancelled runs do not have a replay.")
    if terminal.get("terminal") is not True:
        return _state(
            "incomplete", "Replay is available after verified completion."
        )
    if playable is True and status in {"completed", "success"}:
        return _state(
            "ready",
            "Verified replay is ready.",
            controls_enabled=True,
            request_playback=True,
        )
    if playable is False:
        return _state(
            "unavailable", "No fully verified trajectory is available."
        )
    raise ReplayProjectionError("terminal projection is invalid")


def rendering_failure(reason: str) -> dict[str, object]:
    messages = {
        "webgl_initialization_failed": (
            "3D replay is unavailable because WebGL could not be initialized."
        ),
        "webgl_context_lost": (
            "3D replay is unavailable because the WebGL context was lost."
        ),
    }
    if reason not in messages:
        raise ReplayProjectionError("rendering failure reason is invalid")
    state = _state("rendering-failed", messages[reason])
    state["reason"] = reason
    return state


__all__ = ["rendering_failure", "replay_availability"]
