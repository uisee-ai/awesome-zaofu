from __future__ import annotations

import copy
import math
import re
from collections.abc import Mapping, Sequence
from pathlib import PurePosixPath

from scenarioforge.core import canonical_digest

from .contracts import COORDINATE_CONTRACT_V1, VISUAL_REPLAY_TOLERANCE_V1
from .interpolation import (
    ReplayProjectionError,
    normalize_heading_deg,
    shortest_heading_delta_deg,
)
from .presentation import build_participant_legend
from .traffic import validate_right_hand_traffic


_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_PLAYBACK_SCHEMAS = {
    "scenarioforge.playback/v1",
    "scenarioforge.playback/v2",
}
_MAX_PARTICIPANTS = 64
_MAX_TRAJECTORY_SAMPLES = 500_000
_TRAJECTORY_FIELDS = {
    "scenarioforge.trajectory-point/v1": {
        "schema_version",
        "tick",
        "participant_id",
        "position_m",
        "speed_mps",
        "heading_deg",
        "collision",
    },
    "scenarioforge.trajectory-point/v2": {
        "schema_version",
        "tick",
        "participant_id",
        "position_m",
        "speed_mps",
        "heading_deg",
        "collision",
        "lane_id",
        "engine_lane_index",
        "lane_longitudinal_m",
        "route_id",
        "route_destination_lane_id",
        "route_destination_engine_lane_index",
        "route_destination_matches",
        "route_checkpoints",
        "route_completed",
        "boundary_violation",
        "wrong_route",
    },
    "scenarioforge.trajectory-point/v3": {
        "schema_version",
        "tick",
        "participant_id",
        "position_m",
        "speed_mps",
        "heading_deg",
        "collision",
        "brake",
        "signals",
        "lane_id",
        "engine_lane_index",
        "lane_longitudinal_m",
        "route_id",
        "route_destination_lane_id",
        "route_destination_engine_lane_index",
        "route_destination_matches",
        "route_checkpoints",
        "route_completed",
        "boundary_violation",
        "wrong_route",
    },
}
_ROLE_ALIASES = {
    "ego": "ego",
    "controlled": "controlled_agent",
    "controlled_agent": "controlled_agent",
    "other_controllable_agent": "controlled_agent",
    "social": "social",
    "social_vehicle": "social_vehicle",
    "pedestrian": "pedestrian",
    "vulnerable_road_user": "pedestrian",
}


def _finite_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _safe_id(value: object, label: str) -> str:
    if not isinstance(value, str) or _SAFE_ID.fullmatch(value) is None:
        raise ReplayProjectionError(f"{label} is invalid")
    return value


def _logical_ref(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ReplayProjectionError("logical ref is invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ReplayProjectionError("logical ref is invalid")
    if path.name != "trajectory.json":
        raise ReplayProjectionError("logical ref is invalid")
    return value


def _trajectory_digest(value: object) -> str:
    if (
        not isinstance(value, str)
        or _DIGEST.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise ReplayProjectionError("trajectory digest is invalid")
    return value


def _participants(value: object) -> list[dict[str, str]]:
    if (
        not isinstance(value, list)
        or not 1 <= len(value) <= _MAX_PARTICIPANTS
    ):
        raise ReplayProjectionError("participants are invalid")
    projected: list[dict[str, str]] = []
    ids: list[str] = []
    for item in value:
        if not isinstance(item, Mapping) or set(item) != {"id", "role"}:
            raise ReplayProjectionError("participants are invalid")
        participant_id = _safe_id(item["id"], "participant id")
        role = item["role"]
        if role not in _ROLE_ALIASES:
            raise ReplayProjectionError("participant role is invalid")
        ids.append(participant_id)
        projected.append({"id": participant_id, "role": _ROLE_ALIASES[str(role)]})
    if len(ids) != len(set(ids)):
        raise ReplayProjectionError("participants are invalid")
    egos = [item for item in projected if item["role"] == "ego"]
    if len(egos) != 1:
        raise ReplayProjectionError("unique ego participant is required")
    return projected


def _sample(
    value: object,
    participant_ids: set[str],
    terminal_tick: int,
    sample_interval_s: float,
) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ReplayProjectionError("trajectory sample is invalid")
    point_schema = value.get("schema_version")
    expected_fields = _TRAJECTORY_FIELDS.get(point_schema)
    tick = value.get("tick")
    participant_id = value.get("participant_id")
    position = value.get("position_m")
    if (
        expected_fields is None
        or set(value) != expected_fields
        or not isinstance(tick, int)
        or isinstance(tick, bool)
        or not 0 <= tick <= terminal_tick
        or participant_id not in participant_ids
        or not isinstance(position, Sequence)
        or isinstance(position, (str, bytes))
        or len(position) != 2
        or not all(_finite_number(item) for item in position)
        or not _finite_number(value.get("speed_mps"))
        or float(value["speed_mps"]) < 0
        or not _finite_number(value.get("heading_deg"))
        or not isinstance(value.get("collision"), bool)
    ):
        raise ReplayProjectionError("trajectory sample is invalid")
    brake: float | None = None
    signals: list[dict[str, str]] | None = None
    if point_schema == "scenarioforge.trajectory-point/v3":
        raw_brake = value.get("brake")
        raw_signals = value.get("signals")
        if (
            not _finite_number(raw_brake)
            or not 0 <= float(raw_brake) <= 1
        ):
            raise ReplayProjectionError("trajectory sample is invalid")
        brake = float(raw_brake)
        signals = _signals(raw_signals)
    common = {
        "schema_version",
        "tick",
        "participant_id",
        "position_m",
        "speed_mps",
        "heading_deg",
        "collision",
    }
    if point_schema == "scenarioforge.trajectory-point/v3":
        common.update({"brake", "signals"})
    evidence_state = {
        key: copy.deepcopy(item)
        for key, item in value.items()
        if key not in common
    }
    position_m = [float(position[0]), float(position[1])]
    recorded_heading = float(value["heading_deg"])
    heading = normalize_heading_deg(recorded_heading)
    projected = {
        "source_schema_version": point_schema,
        "tick": tick,
        "simulation_time_s": tick * sample_interval_s,
        "position_m": position_m,
        "render_position_m": [position_m[0], 0.0, -position_m[1]],
        "heading_deg": heading,
        "recorded_heading_deg": recorded_heading,
        "render_yaw_rad": math.radians(heading),
        "speed_mps": float(value["speed_mps"]),
        "collision": value["collision"],
        "evidence_state": evidence_state,
    }
    if brake is not None and signals is not None:
        projected["brake"] = brake
        projected["signals"] = signals
    return projected


def _signals(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list) or len(value) > 64:
        raise ReplayProjectionError("trajectory signals are invalid")
    projected: list[dict[str, str]] = []
    signal_ids: list[str] = []
    for signal in value:
        if not isinstance(signal, Mapping) or set(signal) != {"signal_id", "state"}:
            raise ReplayProjectionError("trajectory signal is invalid")
        signal_id = _safe_id(signal["signal_id"], "signal id")
        state = signal["state"]
        if state not in {"red", "yellow", "green", "off", "unknown"}:
            raise ReplayProjectionError("trajectory signal is invalid")
        signal_ids.append(signal_id)
        projected.append({"signal_id": signal_id, "state": str(state)})
    if len(signal_ids) != len(set(signal_ids)):
        raise ReplayProjectionError("trajectory signals are invalid")
    return projected


def _tracks(
    value: object,
    participants: list[dict[str, str]],
    terminal_tick: int,
    sample_interval_s: float,
) -> list[dict[str, object]]:
    if (
        not isinstance(value, list)
        or not value
        or len(value) > _MAX_TRAJECTORY_SAMPLES
    ):
        raise ReplayProjectionError("trajectory is invalid")
    participant_ids = {item["id"] for item in participants}
    by_id: dict[str, list[dict[str, object]]] = {
        item["id"]: [] for item in participants
    }
    for raw in value:
        participant_id = raw.get("participant_id") if isinstance(raw, Mapping) else None
        projected = _sample(
            raw,
            participant_ids,
            terminal_tick,
            sample_interval_s,
        )
        assert isinstance(participant_id, str)
        by_id[participant_id].append(projected)
    tracks: list[dict[str, object]] = []
    for participant in participants:
        samples = by_id[participant["id"]]
        ticks = [int(item["tick"]) for item in samples]
        if not samples or ticks != sorted(set(ticks)) or ticks[0] != 0:
            raise ReplayProjectionError("trajectory sample order is invalid")
        if any(
            item["source_schema_version"] == "scenarioforge.trajectory-point/v3"
            for item in samples
        ):
            _validate_heading_tangent(samples)
        tracks.append(
            {
                "participant_id": participant["id"],
                "role": participant["role"],
                "source_classification": "recorded-evidence",
                "source_ref": "$.trajectory",
                "samples": samples,
            }
        )
    return tracks


def _validate_heading_tangent(samples: Sequence[Mapping[str, object]]) -> None:
    tolerance = VISUAL_REPLAY_TOLERANCE_V1
    if len(samples) < 2:
        return
    for index, sample in enumerate(samples):
        adjacent = samples[index + 1] if index < len(samples) - 1 else samples[index - 1]
        start = sample if index < len(samples) - 1 else adjacent
        end = adjacent if index < len(samples) - 1 else sample
        start_position = start["position_m"]
        end_position = end["position_m"]
        assert isinstance(start_position, list) and isinstance(end_position, list)
        delta_x = float(end_position[0]) - float(start_position[0])
        delta_y = float(end_position[1]) - float(start_position[1])
        if math.hypot(delta_x, delta_y) < tolerance.minimum_tangent_displacement_m_per_tick:
            continue
        tangent = math.degrees(math.atan2(delta_y, delta_x))
        error = abs(
            shortest_heading_delta_deg(tangent, float(sample["heading_deg"]))
        )
        if error > tolerance.max_heading_tangent_error_deg + 1e-9:
            raise ReplayProjectionError(
                "trajectory heading differs from recorded motion by more than 10 degrees"
            )


def _verified_deceleration(
    samples: Sequence[Mapping[str, object]], start_tick: int, end_tick: int
) -> bool:
    speeds = [
        float(item["speed_mps"])
        for item in samples
        if start_tick <= int(item["tick"]) <= end_tick
    ]
    return any(current < previous - 1e-6 for previous, current in zip(speeds, speeds[1:]))


def _events(
    value: object,
    tracks: list[dict[str, object]],
    terminal_tick: int,
    sample_interval_s: float,
) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise ReplayProjectionError("events are invalid")
    tracks_by_id = {str(item["participant_id"]): item for item in tracks}
    projected: list[dict[str, object]] = []
    trigger_order: list[int] = []
    event_ids: list[str] = []
    for event in value:
        if not isinstance(event, Mapping):
            raise ReplayProjectionError("event is invalid")
        event_id = _safe_id(event.get("event_id"), "event id")
        participant_id = event.get("participant_id")
        trigger = event.get("trigger_tick")
        effect = event.get("effect_state_tick")
        duration = event.get("duration_ticks", 1)
        if (
            participant_id not in tracks_by_id
            or not isinstance(trigger, int)
            or isinstance(trigger, bool)
            or not isinstance(effect, int)
            or isinstance(effect, bool)
            or not isinstance(duration, int)
            or isinstance(duration, bool)
            or trigger < 0
            or effect < trigger
            or effect > terminal_tick
            or duration < 1
        ):
            raise ReplayProjectionError("event is invalid")
        action = event.get("action")
        if action is not None and (
            not isinstance(action, Mapping)
            or set(action) != {"steering", "throttle_brake"}
            or not all(_finite_number(item) for item in action.values())
        ):
            raise ReplayProjectionError("event action is invalid")
        projected_action = None if action is None else {
            "steering": float(action["steering"]),
            "throttle_brake": float(action["throttle_brake"]),
        }
        braking = bool(
            projected_action is not None
            and projected_action["throttle_brake"] < 0
        )
        end_tick = min(terminal_tick, max(effect, trigger + duration - 1))
        track_samples = tracks_by_id[str(participant_id)]["samples"]
        assert isinstance(track_samples, list)
        deceleration = braking and _verified_deceleration(
            track_samples, trigger, end_tick
        )
        trigger_order.append(trigger)
        event_ids.append(event_id)
        projected.append(
            {
                "event_id": event_id,
                "participant_id": str(participant_id),
                "trigger_tick": trigger,
                "effect_state_tick": effect,
                "end_tick": end_tick,
                "start_time_s": trigger * sample_interval_s,
                "effect_time_s": effect * sample_interval_s,
                "end_time_s": end_tick * sample_interval_s,
                "action": projected_action,
                "braking": braking,
                "verified_deceleration": deceleration,
                "source_classification": "recorded-evidence",
                "source_refs": ["$.events", "$.trajectory"],
            }
        )
    if trigger_order != sorted(trigger_order) or len(event_ids) != len(set(event_ids)):
        raise ReplayProjectionError("events are not ordered")
    return projected


def _visual_element(
    element_id: str,
    label: str,
    meaning: str,
    *,
    applicable: bool,
    source_classification: str,
    source_refs: list[str],
) -> dict[str, object]:
    return {
        "element_id": element_id,
        "label": label,
        "meaning": meaning,
        "status": "applicable" if applicable else "not-applicable",
        "source_classification": (
            source_classification if applicable else "not-declared"
        ),
        "source_refs": source_refs if applicable else [],
    }


def _visual_context(
    playback: Mapping[str, object],
    events: list[dict[str, object]],
    tracks: list[dict[str, object]],
) -> dict[str, object]:
    road = playback["road"]
    if not isinstance(road, Mapping):
        raise ReplayProjectionError("road projection is invalid")
    geometry = road.get("geometry")
    verified_geometry = isinstance(geometry, Mapping)
    geometry_source = "$.road.geometry" if verified_geometry else "$.road"
    lanes = geometry.get("lanes") if verified_geometry else None
    conflict_zones = geometry.get("conflict_zones") if verified_geometry else None
    has_lanes = bool(lanes) if verified_geometry else True
    has_conflicts = bool(conflict_zones) if verified_geometry else False
    has_braking = any(
        event["braking"] is True and event["verified_deceleration"] is True
        for event in events
    )
    has_pedestrians = any(track["role"] == "pedestrian" for track in tracks)
    has_signals = any(
        bool(sample.get("signals"))
        for track in tracks
        for sample in track["samples"]
        if isinstance(sample, Mapping)
    )
    elements = [
        _visual_element(
            "road-surface",
            "Road surface",
            "Verified drivable lane geometry",
            applicable=True,
            source_classification="recorded-evidence",
            source_refs=[geometry_source],
        ),
        _visual_element(
            "lane-boundaries",
            "Lane boundaries",
            "Verified left and right lane limits",
            applicable=has_lanes,
            source_classification="recorded-evidence",
            source_refs=[geometry_source],
        ),
        _visual_element(
            "lane-centrelines",
            "Lane centre lines",
            "Verified lane centre geometry",
            applicable=has_lanes,
            source_classification="recorded-evidence",
            source_refs=[geometry_source],
        ),
        _visual_element(
            "conflict-zones",
            "Conflict zones",
            "Verified shared road regions where participant paths conflict",
            applicable=has_conflicts,
            source_classification="recorded-evidence",
            source_refs=["$.road.geometry.conflict_zones"],
        ),
        _visual_element(
            "vehicles",
            "Vehicles",
            "Recorded participants at evidence-bound poses",
            applicable=True,
            source_classification="recorded-evidence",
            source_refs=["$.participants", "$.trajectory"],
        ),
        _visual_element(
            "brake-lights",
            "Brake lights",
            "Display state derived from a verified braking event and speed profile",
            applicable=has_braking,
            source_classification="display-derived",
            source_refs=["$.events", "$.trajectory"],
        ),
        _visual_element(
            "traffic-signals",
            "Traffic signals",
            "Signal state declared by immutable scenario or backend evidence",
            applicable=has_signals,
            source_classification="recorded-evidence",
            source_refs=["$.trajectory[*].signals"],
        ),
        _visual_element(
            "curbs-and-pedestrian-areas",
            "Curbs and pedestrian areas",
            "Declared roadside and pedestrian-only geometry",
            applicable=False,
            source_classification="recorded-evidence",
            source_refs=[],
        ),
        _visual_element(
            "pedestrians",
            "Pedestrians",
            "Recorded pedestrian participants",
            applicable=has_pedestrians,
            source_classification="recorded-evidence",
            source_refs=["$.participants", "$.trajectory"],
        ),
        _visual_element(
            "obstacles",
            "Obstacles",
            "Recorded static or dynamic obstacles",
            applicable=False,
            source_classification="recorded-evidence",
            source_refs=[],
        ),
    ]
    profile: dict[str, object] = {
        "schema_version": "scenarioforge.visual-context-profile/v1",
        "elements": elements,
    }
    profile["profile_digest"] = canonical_digest(profile)
    return profile


def _p1_signal_legend(tracks: Sequence[Mapping[str, object]]) -> list[dict[str, str]]:
    states: dict[str, str] = {}
    for track in tracks:
        samples = track["samples"]
        assert isinstance(samples, list)
        if not samples:
            continue
        signals = samples[0].get("signals", [])
        if not isinstance(signals, list):
            raise ReplayProjectionError("trajectory signals are invalid")
        for signal in signals:
            assert isinstance(signal, Mapping)
            signal_id = str(signal["signal_id"])
            state = str(signal["state"])
            if signal_id in states and states[signal_id] != state:
                raise ReplayProjectionError("trajectory signal state is ambiguous")
            states[signal_id] = state
    return [
        {
            "signal_id": signal_id,
            "state": state,
            "accessible_label": f"{signal_id} · {state}",
        }
        for signal_id, state in sorted(states.items())
    ]


def _p1_replay_projection(
    playback: Mapping[str, object],
    participants: list[dict[str, str]],
    tracks: list[dict[str, object]],
    events: list[dict[str, object]],
) -> dict[str, object] | None:
    traffic_contract = playback.get("traffic_contract")
    p1_sample = any(
        sample.get("source_schema_version") == "scenarioforge.trajectory-point/v3"
        for track in tracks
        for sample in track["samples"]
        if isinstance(sample, Mapping)
    )
    if traffic_contract is None and not p1_sample:
        return None
    if not isinstance(traffic_contract, Mapping):
        raise ReplayProjectionError("right-hand traffic contract is required")
    legend_samples = [
        {
            "tick": int(sample["tick"]),
            "participant_id": str(track["participant_id"]),
            "speed_mps": float(sample["speed_mps"]),
            "brake": float(sample.get("brake", 0.0)),
        }
        for track in tracks
        for sample in track["samples"]
        if isinstance(sample, Mapping)
    ]
    projected_events = [
        {
            "event_id": event["event_id"],
            "participant_id": event["participant_id"],
            "trigger_tick": event["trigger_tick"],
            "end_tick": event["end_tick"],
        }
        for event in events
    ]
    traffic_validation = validate_right_hand_traffic(traffic_contract)
    yellow_epsilon = traffic_validation["observed"][
        "yellow_line_footprint_epsilon_m"
    ]
    return {
        "schema_version": "scenarioforge.p1-replay/v1",
        "traffic_validation": traffic_validation,
        "participant_legend": build_participant_legend(
            participants, legend_samples, projected_events, tick=0
        ),
        "road_legend": [
            "Right-hand travel uses the legal right carriageway.",
            "Lane arrows show recorded travel direction.",
            "Intersection connectors bind turn entry to the receiving lane.",
            f"Yellow centre lines separate opposing carriageways; footprint epsilon {yellow_epsilon} m.",
            "Conflict zones are recorded road regions, not inferred collisions.",
            "Signals show recorded state at the selected replay tick.",
        ],
        "signal_legend": _p1_signal_legend(tracks),
    }


def project_replay_scene(playback: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(playback, Mapping):
        raise ReplayProjectionError("playback projection is invalid")
    schema_version = playback.get("schema_version")
    if schema_version not in _PLAYBACK_SCHEMAS:
        raise ReplayProjectionError("playback schema is invalid")
    scenario_id = _safe_id(playback.get("scenario_id"), "scenario id")
    run_id = _safe_id(playback.get("run_id"), "run id")
    attempt_id = _safe_id(playback.get("attempt_id"), "attempt id")
    logical_ref = _logical_ref(playback.get("logical_ref"))
    digest = _trajectory_digest(playback.get("trajectory_digest"))
    interval = playback.get("sample_interval_s")
    terminal_tick = playback.get("terminal_tick")
    if (
        not _finite_number(interval)
        or float(interval) <= 0
        or not isinstance(terminal_tick, int)
        or isinstance(terminal_tick, bool)
        or terminal_tick < 0
    ):
        raise ReplayProjectionError("timeline is invalid")
    sample_interval_s = float(interval)
    participants = _participants(playback.get("participants"))
    tracks = _tracks(
        playback.get("trajectory"),
        participants,
        terminal_tick,
        sample_interval_s,
    )
    events = _events(
        playback.get("events"),
        tracks,
        terminal_tick,
        sample_interval_s,
    )
    road = playback.get("road")
    if not isinstance(road, Mapping):
        raise ReplayProjectionError("road projection is invalid")
    coordinate_system = road.get(
        "coordinate_system", "right-handed-x-forward-y-left"
    )
    if coordinate_system != "right-handed-x-forward-y-left":
        raise ReplayProjectionError("coordinate system is invalid")
    ego_id = next(item["id"] for item in participants if item["role"] == "ego")
    geometry = road.get("geometry")
    has_conflict = bool(
        isinstance(geometry, Mapping) and geometry.get("conflict_zones")
    )
    tolerance = VISUAL_REPLAY_TOLERANCE_V1
    scene: dict[str, object] = {
        "schema_version": "scenarioforge.replay-scene/v1",
        "source_binding": {
            "classification": "recorded-evidence",
            "playback_schema_version": schema_version,
            "scenario_id": scenario_id,
            "run_id": run_id,
            "attempt_id": attempt_id,
            "logical_ref": logical_ref,
            "trajectory_digest": digest,
        },
        "coordinate_contract": copy.deepcopy(COORDINATE_CONTRACT_V1),
        "visual_tolerance": tolerance.to_dict(),
        "camera": {
            "schema_version": "scenarioforge.replay-camera/v1",
            "default_mode": "ego-follow",
            "available_modes": [
                "ego-follow",
                "overview",
                *(["conflict-focus"] if has_conflict else []),
            ],
            "ego_participant_id": ego_id,
            "rear_offset_m": tolerance.rear_offset_m,
            "height_offset_m": tolerance.height_offset_m,
            "look_ahead_m": tolerance.look_ahead_m,
            "damping_half_life_ms": tolerance.damping_half_life_ms,
            "stable_horizon_axis": "+y",
            "source_classification": "display-derived",
            "source_refs": ["$.participants", "$.trajectory"],
        },
        "visual_context": _visual_context(playback, events, tracks),
        "timeline": {
            "schema_version": "scenarioforge.replay-timeline/v1",
            "sample_interval_s": sample_interval_s,
            "start_time_s": 0.0,
            "end_time_s": terminal_tick * sample_interval_s,
            "terminal_tick": terminal_tick,
            "controls": {
                "play_pause": True,
                "speeds": [0.25, 0.5, 1.0, 2.0, 4.0],
                "seek": True,
                "event_navigation": True,
            },
        },
        "tracks": tracks,
        "events": events,
    }
    p1_replay = _p1_replay_projection(playback, participants, tracks, events)
    if p1_replay is not None:
        scene["camera"] = {
            **scene["camera"],
            "schema_version": "scenarioforge.replay-camera/v2",
            "default_mode": "follow",
            "available_modes": ["follow", "overview", "fixed", "free"],
        }
        scene["p1_replay"] = p1_replay
    scene["descriptor_digest"] = canonical_digest(scene)
    return scene


__all__ = ["project_replay_scene"]
