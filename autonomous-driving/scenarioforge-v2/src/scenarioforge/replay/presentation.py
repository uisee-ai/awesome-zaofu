from __future__ import annotations

import math
import re
from collections.abc import Mapping

from .interpolation import ReplayProjectionError


_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_ROLE_ALIASES = {
    "ego": "ego",
    "controlled": "controlled_agent",
    "controlled_agent": "controlled_agent",
    "other_controllable_agent": "controlled_agent",
    "social": "social_vehicle",
    "social_vehicle": "social_vehicle",
    "pedestrian": "pedestrian",
    "vulnerable_road_user": "pedestrian",
}
_APPEARANCE = {
    "ego": {"color": "#32d6c5", "shape": "vehicle", "visual_pattern": "solid"},
    "controlled_agent": {
        "color": "#8ea7ff",
        "shape": "vehicle",
        "visual_pattern": "striped",
    },
    "social_vehicle": {
        "color": "#ffb454",
        "shape": "vehicle",
        "visual_pattern": "outline",
    },
    "pedestrian": {
        "color": "#f88bc4",
        "shape": "pedestrian",
        "visual_pattern": "upright",
    },
}


def _finite(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _participant_id(value: object) -> str:
    if not isinstance(value, str) or _SAFE_ID.fullmatch(value) is None:
        raise ReplayProjectionError("participant id is invalid")
    return value


def _role(value: object) -> str:
    if not isinstance(value, str) or value not in _ROLE_ALIASES:
        raise ReplayProjectionError("participant role is invalid")
    return _ROLE_ALIASES[value]


def _role_label(role: str) -> str:
    return role.replace("_", " ")


def build_participant_legend(
    participants: object,
    samples: object,
    events: object,
    *,
    tick: int,
) -> list[dict[str, object]]:
    """Build a stable, non-color-only replay legend at a recorded tick."""

    if (
        not isinstance(participants, list)
        or not participants
        or not isinstance(samples, list)
        or not isinstance(events, list)
        or not isinstance(tick, int)
        or isinstance(tick, bool)
        or tick < 0
    ):
        raise ReplayProjectionError("participants are invalid")
    normalized: list[tuple[str, str]] = []
    for participant in participants:
        if not isinstance(participant, Mapping) or set(participant) != {"id", "role"}:
            raise ReplayProjectionError("participants are invalid")
        normalized.append(
            (_participant_id(participant["id"]), _role(participant["role"]))
        )
    participant_ids = [participant_id for participant_id, _ in normalized]
    if len(participant_ids) != len(set(participant_ids)):
        raise ReplayProjectionError("participants are invalid")

    by_participant: dict[str, list[tuple[int, float, float]]] = {
        participant_id: [] for participant_id in participant_ids
    }
    seen_samples: set[tuple[str, int]] = set()
    for sample in samples:
        if not isinstance(sample, Mapping) or set(sample) != {
            "tick",
            "participant_id",
            "speed_mps",
            "brake",
        }:
            raise ReplayProjectionError("participant sample is invalid")
        participant_id = sample["participant_id"]
        sample_tick = sample["tick"]
        if (
            participant_id not in by_participant
            or not isinstance(sample_tick, int)
            or isinstance(sample_tick, bool)
            or sample_tick < 0
            or not _finite(sample["speed_mps"])
            or float(sample["speed_mps"]) < 0
            or not _finite(sample["brake"])
            or not 0 <= float(sample["brake"]) <= 1
            or (str(participant_id), sample_tick) in seen_samples
        ):
            raise ReplayProjectionError("participant sample is invalid")
        seen_samples.add((str(participant_id), sample_tick))
        by_participant[str(participant_id)].append(
            (sample_tick, float(sample["speed_mps"]), float(sample["brake"]))
        )
    for participant_samples in by_participant.values():
        participant_samples.sort(key=lambda item: item[0])

    active_events: dict[str, list[str]] = {participant_id: [] for participant_id in participant_ids}
    event_ids: set[str] = set()
    for event in events:
        if not isinstance(event, Mapping):
            raise ReplayProjectionError("participant event is invalid")
        event_id = _participant_id(event.get("event_id"))
        participant_id = event.get("participant_id")
        trigger = event.get("trigger_tick")
        duration = event.get("duration_ticks", 1)
        end = event.get("end_tick")
        if (
            event_id in event_ids
            or participant_id not in active_events
            or not isinstance(trigger, int)
            or isinstance(trigger, bool)
            or not isinstance(duration, int)
            or isinstance(duration, bool)
            or duration < 1
            or (end is not None and (not isinstance(end, int) or isinstance(end, bool)))
        ):
            raise ReplayProjectionError("participant event is invalid")
        event_ids.add(event_id)
        end_tick = trigger + duration - 1 if end is None else end
        if end_tick < trigger:
            raise ReplayProjectionError("participant event is invalid")
        if trigger <= tick <= end_tick:
            active_events[str(participant_id)].append(event_id)

    legend: list[dict[str, object]] = []
    for participant_id, role in normalized:
        available = [sample for sample in by_participant[participant_id] if sample[0] <= tick]
        if not available:
            raise ReplayProjectionError("participant sample is missing")
        _, speed, brake = available[-1]
        brake_state = (
            "not-applicable"
            if role == "pedestrian"
            else "braking" if brake > 0 else "coasting"
        )
        key_event_state = ", ".join(active_events[participant_id]) or "none"
        event_label = (
            f"event {key_event_state}"
            if key_event_state != "none"
            else "no key event"
        )
        brake_label = (
            "brake not applicable" if brake_state == "not-applicable" else brake_state
        )
        appearance = _APPEARANCE[role]
        legend.append(
            {
                "participant_id": participant_id,
                "role": role,
                **appearance,
                "speed_mps": speed,
                "brake_state": brake_state,
                "key_event_state": key_event_state,
                "accessible_label": (
                    f"{participant_id} · {_role_label(role)} · {speed} m/s · "
                    f"{brake_label} · {event_label}"
                ),
            }
        )
    return legend


__all__ = ["build_participant_legend"]
