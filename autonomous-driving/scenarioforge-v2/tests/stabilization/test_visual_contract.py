from __future__ import annotations

import copy
import json
import math
import subprocess
from pathlib import Path

import pytest

from scenarioforge.core import canonical_digest
from scenarioforge.replay import (
    VISUAL_REPLAY_TOLERANCE_V1,
    ReplayProjectionError,
    interpolate_pose,
    project_replay_scene,
    shortest_heading_delta_deg,
)
from scenarioforge.web.evidence import PublishedEvidenceReader


ROOT = Path(__file__).resolve().parents[2]
REPLAY_MODULE = ROOT / "src" / "scenarioforge" / "replay" / "replay_scene.js"


def _playback() -> dict[str, object]:
    return {
        "schema_version": "scenarioforge.playback/v2",
        "scenario_id": "brake_lead",
        "run_id": "run-visual-contract",
        "attempt_id": "attempt-0001",
        "execution_status": "completed",
        "scenario_outcome": "near_miss",
        "termination_reason": "success_predicates_satisfied",
        "logical_ref": (
            "published/run-visual-contract/attempt-0001/output/trajectory.json"
        ),
        "trajectory_digest": "a" * 64,
        "road": {
            "schema_version": "scenarioforge.topology/v2",
            "topology_kind": "straight",
            "map_block_sequence": "S",
            "lane_width_m": 3.5,
            "coordinate_system": "right-handed-x-forward-y-left",
            "units": {
                "distance": "m",
                "speed": "m/s",
                "heading": "deg",
                "time": "tick",
            },
            "lanes": [
                {
                    "id": "ego-lane",
                    "road_id": "mainline",
                    "engine_lane_index": {
                        "start_node": ">>",
                        "end_node": ">>>",
                        "lane_index": 0,
                    },
                    "kind": "travel",
                    "length_m": 120.0,
                    "predecessor_lane_ids": [],
                    "successor_lane_ids": [],
                }
            ],
            "conflict_zones": [],
            "geometry": {
                "schema_version": "scenarioforge.road-geometry/v1",
                "coordinate_system": "right-handed-x-forward-y-left",
                "source": "metadrive-road-network",
                "lanes": [
                    {
                        "lane_id": "ego-lane",
                        "kind": "travel",
                        "centerline_m": [[0.0, 0.0], [40.0, 0.0]],
                        "left_boundary_m": [[0.0, 1.75], [40.0, 1.75]],
                        "right_boundary_m": [[0.0, -1.75], [40.0, -1.75]],
                    }
                ],
                "conflict_zones": [],
            },
        },
        "participants": [
            {"id": "ego", "role": "ego"},
            {"id": "lead", "role": "social"},
        ],
        "sample_interval_s": 0.1,
        "terminal_tick": 2,
        "events": [
            {
                "event_id": "lead-hard-brake",
                "sequence": 0,
                "type": "trigger_fired",
                "participant_id": "lead",
                "trigger_tick": 0,
                "effect_state_tick": 1,
                "duration_ticks": 3,
                "action": {"steering": 0.0, "throttle_brake": -1.0},
            }
        ],
        "trajectory": [
            {
                "schema_version": "scenarioforge.trajectory-point/v2",
                "tick": tick,
                "participant_id": participant_id,
                "position_m": position,
                "speed_mps": speed,
                "heading_deg": heading,
                "collision": False,
                "lane_id": "ego-lane",
                "engine_lane_index": [">>", ">>>", 0],
                "lane_longitudinal_m": position[0],
                "route_id": f"{participant_id}-route",
                "route_destination_lane_id": "ego-lane",
                "route_destination_engine_lane_index": [">>", ">>>", 0],
                "route_destination_matches": True,
                "route_checkpoints": [">>", ">>>"],
                "route_completed": tick == 2,
                "boundary_violation": False,
                "wrong_route": False,
            }
            for tick, participant_id, position, speed, heading in (
                (0, "ego", [0.0, 0.0], 10.0, 179.0),
                (0, "lead", [10.0, 0.0], 10.0, 0.0),
                (1, "ego", [-1.0, 0.02], 9.0, -179.0),
                (1, "lead", [10.8, 0.0], 8.0, 0.0),
                (2, "ego", [-2.0, 0.04], 8.0, -177.0),
                (2, "lead", [11.4, 0.0], 6.0, 0.0),
            )
        ],
    }


def test_visual_replay_tolerance_v1_is_the_exact_frozen_profile() -> None:
    assert VISUAL_REPLAY_TOLERANCE_V1.to_dict() == {
        "schema_version": "scenarioforge.visual-replay-tolerance/v1",
        "follow_camera": {
            "rear_offset_m": 8.0,
            "height_offset_m": 4.0,
            "look_ahead_m": 12.0,
            "damping_half_life_ms": 150.0,
            "settle_time_s": 0.5,
            "max_follow_error_m": 2.0,
            "max_look_direction_error_deg": 5.0,
        },
        "pose": {
            "minimum_tangent_displacement_m_per_tick": 0.25,
            "max_heading_tangent_error_deg": 10.0,
            "heading_interpolation": "shortest-wrapped-arc",
            "local_forward_axis": "+x",
        },
        "performance": {"max_frame_time_p95_ms": 33.0},
    }


def test_projection_is_exact_digest_bound_and_does_not_mutate_playback() -> None:
    playback = _playback()
    original = copy.deepcopy(playback)

    scene = project_replay_scene(playback)

    assert playback == original
    assert set(scene) == {
        "schema_version",
        "descriptor_digest",
        "source_binding",
        "coordinate_contract",
        "visual_tolerance",
        "camera",
        "visual_context",
        "timeline",
        "tracks",
        "events",
    }
    unsigned = dict(scene)
    descriptor_digest = unsigned.pop("descriptor_digest")
    assert descriptor_digest == canonical_digest(unsigned)
    assert scene["source_binding"] == {
        "classification": "recorded-evidence",
        "playback_schema_version": "scenarioforge.playback/v2",
        "scenario_id": "brake_lead",
        "run_id": "run-visual-contract",
        "attempt_id": "attempt-0001",
        "logical_ref": (
            "published/run-visual-contract/attempt-0001/output/trajectory.json"
        ),
        "trajectory_digest": "a" * 64,
    }
    assert scene["coordinate_contract"] == {
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
    assert scene["camera"] == {
        "schema_version": "scenarioforge.replay-camera/v1",
        "default_mode": "ego-follow",
        "available_modes": ["ego-follow", "overview"],
        "ego_participant_id": "ego",
        "rear_offset_m": 8.0,
        "height_offset_m": 4.0,
        "look_ahead_m": 12.0,
        "damping_half_life_ms": 150.0,
        "stable_horizon_axis": "+y",
        "source_classification": "display-derived",
        "source_refs": ["$.participants", "$.trajectory"],
    }
    assert scene["timeline"] == {
        "schema_version": "scenarioforge.replay-timeline/v1",
        "sample_interval_s": 0.1,
        "start_time_s": 0.0,
        "end_time_s": 0.2,
        "terminal_tick": 2,
        "controls": {
            "play_pause": True,
            "speeds": [0.25, 0.5, 1.0, 2.0, 4.0],
            "seek": True,
            "event_navigation": True,
        },
    }
    assert [track["participant_id"] for track in scene["tracks"]] == [
        "ego",
        "lead",
    ]
    assert [sample["tick"] for sample in scene["tracks"][0]["samples"]] == [
        0,
        1,
        2,
    ]
    assert scene["tracks"][0]["samples"][1]["render_position_m"] == [
        -1.0,
        0.0,
        -0.02,
    ]
    assert scene["tracks"][0]["samples"][0]["source_schema_version"] == (
        "scenarioforge.trajectory-point/v2"
    )
    assert scene["tracks"][0]["samples"][0]["recorded_heading_deg"] == 179.0
    assert scene["tracks"][0]["samples"][1]["evidence_state"] == {
        "lane_id": "ego-lane",
        "engine_lane_index": [">>", ">>>", 0],
        "lane_longitudinal_m": -1.0,
        "route_id": "ego-route",
        "route_destination_lane_id": "ego-lane",
        "route_destination_engine_lane_index": [">>", ">>>", 0],
        "route_destination_matches": True,
        "route_checkpoints": [">>", ">>>"],
        "route_completed": False,
        "boundary_violation": False,
        "wrong_route": False,
    }
    assert scene["events"] == [
        {
            "event_id": "lead-hard-brake",
            "participant_id": "lead",
            "trigger_tick": 0,
            "effect_state_tick": 1,
            "end_tick": 2,
            "start_time_s": 0.0,
            "effect_time_s": 0.1,
            "end_time_s": 0.2,
            "action": {"steering": 0.0, "throttle_brake": -1.0},
            "braking": True,
            "verified_deceleration": True,
            "source_classification": "recorded-evidence",
            "source_refs": ["$.events", "$.trajectory"],
        }
    ]


def test_visual_context_lists_every_supported_or_not_applicable_semantic() -> None:
    scene = project_replay_scene(_playback())
    context = scene["visual_context"]
    unsigned_context = dict(context)
    context_digest = unsigned_context.pop("profile_digest")

    assert context_digest == canonical_digest(unsigned_context)
    assert [item["element_id"] for item in context["elements"]] == [
        "road-surface",
        "lane-boundaries",
        "lane-centrelines",
        "conflict-zones",
        "vehicles",
        "brake-lights",
        "traffic-signals",
        "curbs-and-pedestrian-areas",
        "pedestrians",
        "obstacles",
    ]
    by_id = {item["element_id"]: item for item in context["elements"]}
    assert by_id["road-surface"] == {
        "element_id": "road-surface",
        "label": "Road surface",
        "meaning": "Verified drivable lane geometry",
        "status": "applicable",
        "source_classification": "recorded-evidence",
        "source_refs": ["$.road.geometry"],
    }
    assert by_id["brake-lights"] == {
        "element_id": "brake-lights",
        "label": "Brake lights",
        "meaning": "Display state derived from a verified braking event and speed profile",
        "status": "applicable",
        "source_classification": "display-derived",
        "source_refs": ["$.events", "$.trajectory"],
    }
    for semantic in (
        "conflict-zones",
        "traffic-signals",
        "curbs-and-pedestrian-areas",
        "pedestrians",
        "obstacles",
    ):
        assert by_id[semantic]["status"] == "not-applicable"
        assert by_id[semantic]["source_classification"] == "not-declared"
        assert by_id[semantic]["source_refs"] == []


def test_position_and_heading_interpolate_by_time_over_the_shortest_arc() -> None:
    scene = project_replay_scene(_playback())
    ego_samples = scene["tracks"][0]["samples"]

    pose = interpolate_pose(ego_samples, 0.05)

    assert pose == {
        "simulation_time_s": pytest.approx(0.05),
        "lower_tick": 0,
        "upper_tick": 1,
        "alpha": pytest.approx(0.5),
        "position_m": pytest.approx([-0.5, 0.01]),
        "render_position_m": pytest.approx([-0.5, 0.0, -0.01]),
        "heading_deg": pytest.approx(-180.0),
        "render_yaw_rad": pytest.approx(-math.pi),
        "speed_mps": pytest.approx(9.5),
        "collision": False,
        "local_forward": pytest.approx([-1.0, 0.0], abs=1e-12),
        "trajectory_tangent_deg": pytest.approx(178.8542371618),
        "heading_tangent_error_deg": pytest.approx(1.1457628382),
        "source_classification": "display-derived",
        "source_ticks": [0, 1],
    }
    assert shortest_heading_delta_deg(179.0, -179.0) == pytest.approx(2.0)
    assert shortest_heading_delta_deg(-179.0, 179.0) == pytest.approx(-2.0)


def test_browser_module_matches_the_frozen_tolerance_and_pose_contract() -> None:
    script = f"""
      import {{
        VISUAL_REPLAY_TOLERANCE_V1,
        interpolatePose,
        resolveTimelineInput,
        shortestHeadingDeltaDeg,
        timelineTickForTime,
      }} from {json.dumps(REPLAY_MODULE.as_uri())};
      const samples = [
        {{tick: 0, simulation_time_s: 0, position_m: [0, 0], heading_deg: 179, speed_mps: 10, collision: false}},
        {{tick: 1, simulation_time_s: 0.1, position_m: [-1, 0.02], heading_deg: -179, speed_mps: 9, collision: false}},
      ];
      console.log(JSON.stringify({{
        tolerance: VISUAL_REPLAY_TOLERANCE_V1,
        delta: shortestHeadingDeltaDeg(179, -179),
        pose: interpolatePose(samples, 0.05),
        timeline: {{
          midpointTick: timelineTickForTime(4.3, 0.1, 86),
          trustedMidpoint: resolveTimelineInput(43, 0.1, 86, true),
          legacyTerminal: resolveTimelineInput(86, 0.1, 86, false),
          visualFractional: resolveTimelineInput(0.05, 0.1, 86, false),
        }},
      }}));
    """

    completed = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)

    assert result["tolerance"] == {
        "schemaVersion": "scenarioforge.visual-replay-tolerance/v1",
        "followCamera": {
            "rearOffsetM": 8,
            "heightOffsetM": 4,
            "lookAheadM": 12,
            "dampingHalfLifeMs": 150,
            "settleTimeS": 0.5,
            "maxFollowErrorM": 2,
            "maxLookDirectionErrorDeg": 5,
        },
        "pose": {
            "minimumTangentDisplacementMPerTick": 0.25,
            "maxHeadingTangentErrorDeg": 10,
            "headingInterpolation": "shortest-wrapped-arc",
            "localForwardAxis": "+x",
        },
        "performance": {"maxFrameTimeP95Ms": 33},
    }
    assert result["delta"] == pytest.approx(2.0)
    assert result["pose"]["positionM"] == pytest.approx([-0.5, 0.01])
    assert result["pose"]["headingDeg"] == pytest.approx(-180.0)
    assert result["pose"]["headingTangentErrorDeg"] == pytest.approx(
        1.1457628382
    )
    assert result["timeline"] == {
        "midpointTick": pytest.approx(43.0),
        "trustedMidpoint": {"unit": "ticks", "value": pytest.approx(43.0)},
        "legacyTerminal": {"unit": "ticks", "value": pytest.approx(86.0)},
        "visualFractional": {
            "unit": "seconds",
            "value": pytest.approx(0.05),
        },
    }


class _PlaybackReader(PublishedEvidenceReader):
    def __init__(self, playback: dict[str, object]) -> None:
        self.value = playback

    def playback(self, run_id: str, attempt_id: str) -> dict[str, object]:
        assert (run_id, attempt_id) == ("run-visual-contract", "attempt-0001")
        return self.value


def test_evidence_reader_creates_a_separate_replay_scene_projection() -> None:
    playback = _playback()
    original = copy.deepcopy(playback)

    projection = _PlaybackReader(playback).replay_scene(
        "run-visual-contract", "attempt-0001"
    )

    assert projection["schema_version"] == "scenarioforge.replay-scene/v1"
    assert playback == original
    assert projection is not playback


@pytest.mark.parametrize(
    "mutate, message",
    [
        (
            lambda payload: payload.update(trajectory_digest="0" * 64),
            "trajectory digest",
        ),
        (
            lambda payload: payload.update(logical_ref="../../host/secret"),
            "logical ref",
        ),
        (
            lambda payload: payload.update(participants=[{"id": "lead", "role": "social"}]),
            "unique ego",
        ),
        (
            lambda payload: payload["trajectory"][0].update(speed_mps=float("nan")),
            "trajectory sample",
        ),
    ],
)
def test_projection_rejects_unbound_or_unsafe_evidence(mutate, message: str) -> None:
    playback = _playback()
    mutate(playback)

    with pytest.raises(ReplayProjectionError, match=message):
        project_replay_scene(playback)
