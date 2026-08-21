from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path

import pytest

from scenarioforge.replay import ReplayProjectionError, project_replay_scene

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "p1" / "traffic"
REPLAY_MODULE = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "scenarioforge"
    / "replay"
    / "replay_scene.js"
)


def _trajectory_point(
    tick: int,
    participant_id: str,
    role: str,
    position: list[float],
    heading: float,
    speed: float,
    brake: float,
) -> dict[str, object]:
    return {
        "schema_version": "scenarioforge.trajectory-point/v3",
        "tick": tick,
        "participant_id": participant_id,
        "position_m": position,
        "speed_mps": speed,
        "heading_deg": heading,
        "collision": False,
        "brake": brake,
        "signals": (
            [{"signal_id": "north-signal", "state": "green"}]
            if role != "pedestrian"
            else []
        ),
        "lane_id": "eastbound-in",
        "engine_lane_index": ["west", "intersection", 0],
        "lane_longitudinal_m": position[0] + 40.0,
        "route_id": f"{participant_id}-route",
        "route_destination_lane_id": "northbound-out",
        "route_destination_engine_lane_index": ["intersection", "north", 0],
        "route_destination_matches": True,
        "route_checkpoints": ["west", "intersection", "north"],
        "route_completed": tick == 1,
        "boundary_violation": False,
        "wrong_route": False,
    }


def _playback() -> dict[str, object]:
    traffic = json.loads(
        (FIXTURES / "right_hand_valid.json").read_text(encoding="utf-8")
    )
    roles = [
        ("ego", "ego", 0.0, 7.5, 0.4),
        ("challenger", "controlled", -0.5, 8.0, 0.0),
        ("traffic-1", "social_vehicle", -1.0, 6.25, 0.0),
        ("walker", "pedestrian", -1.5, 1.4, 0.0),
    ]
    trajectory = []
    for participant_id, role, y_position, speed, brake in roles:
        trajectory.extend(
            [
                _trajectory_point(
                    0,
                    participant_id,
                    role,
                    [-10.0, y_position],
                    0.0,
                    speed,
                    brake,
                ),
                _trajectory_point(
                    1,
                    participant_id,
                    role,
                    [-9.0, y_position],
                    0.0,
                    speed - 0.5 if brake > 0 else speed,
                    brake,
                ),
            ]
        )
    return {
        "schema_version": "scenarioforge.playback/v2",
        "scenario_id": "p1-replay",
        "run_id": "run-p1-replay",
        "attempt_id": "attempt-p1-replay",
        "execution_status": "completed",
        "scenario_outcome": "safe_pass",
        "termination_reason": "goal_reached",
        "logical_ref": "published/run-p1-replay/attempt-p1-replay/output/trajectory.json",
        "trajectory_digest": "b" * 64,
        "traffic_contract": traffic,
        "road": {
            "schema_version": "scenarioforge.topology/v2",
            "topology_kind": "intersection",
            "map_block_sequence": "X",
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
                    "id": "eastbound-in",
                    "road_id": "eastbound",
                    "engine_lane_index": {
                        "start_node": "west",
                        "end_node": "intersection",
                        "lane_index": 0,
                    },
                    "kind": "travel",
                    "length_m": 40.0,
                    "predecessor_lane_ids": [],
                    "successor_lane_ids": ["east-to-north-connector"],
                }
            ],
            "conflict_zones": [
                {
                    "id": "turn-conflict",
                    "lane_ids": ["eastbound-in"],
                    "start_m": 35.0,
                    "end_m": 40.0,
                }
            ],
            "geometry": {
                "schema_version": "scenarioforge.road-geometry/v1",
                "coordinate_system": "right-handed-x-forward-y-left",
                "source": "smarts-road-network",
                "lanes": [
                    {
                        "lane_id": "eastbound-in",
                        "kind": "travel",
                        "centerline_m": [[-40.0, -1.75], [0.0, -1.75]],
                        "left_boundary_m": [[-40.0, 0.0], [0.0, 0.0]],
                        "right_boundary_m": [[-40.0, -3.5], [0.0, -3.5]],
                    }
                ],
                "conflict_zones": [
                    {
                        "zone_id": "turn-conflict",
                        "start_m": 35.0,
                        "end_m": 40.0,
                        "lane_regions": [
                            {
                                "lane_id": "eastbound-in",
                                "left_boundary_m": [[-5.0, 0.0], [0.0, 0.0]],
                                "right_boundary_m": [[-5.0, -3.5], [0.0, -3.5]],
                            }
                        ],
                    }
                ],
            },
        },
        "participants": [
            {"id": participant_id, "role": role} for participant_id, role, *_ in roles
        ],
        "sample_interval_s": 0.1,
        "terminal_tick": 1,
        "events": [
            {
                "event_id": "ego-brakes",
                "participant_id": "ego",
                "trigger_tick": 0,
                "effect_state_tick": 1,
                "duration_ticks": 2,
                "action": {"steering": 0.0, "throttle_brake": -0.4},
            }
        ],
        "trajectory": trajectory,
    }


def test_p1_scene_preserves_normalized_samples_and_exposes_complete_semantics() -> None:
    playback = _playback()
    original = copy.deepcopy(playback)

    scene = project_replay_scene(playback)

    assert playback == original
    assert scene["p1_replay"] == {
        "schema_version": "scenarioforge.p1-replay/v1",
        "traffic_validation": scene["p1_replay"]["traffic_validation"],
        "participant_legend": scene["p1_replay"]["participant_legend"],
        "road_legend": [
            "Right-hand travel uses the legal right carriageway.",
            "Lane arrows show recorded travel direction.",
            "Intersection connectors bind turn entry to the receiving lane.",
            "Yellow centre lines separate opposing carriageways; footprint epsilon 0.02 m.",
            "Conflict zones are recorded road regions, not inferred collisions.",
            "Signals show recorded state at the selected replay tick.",
        ],
        "signal_legend": [
            {
                "signal_id": "north-signal",
                "state": "green",
                "accessible_label": "north-signal · green",
            }
        ],
    }
    assert scene["camera"]["available_modes"] == ["follow", "overview", "fixed", "free"]
    assert scene["camera"]["default_mode"] == "follow"
    assert [track["role"] for track in scene["tracks"]] == [
        "ego",
        "controlled_agent",
        "social_vehicle",
        "pedestrian",
    ]
    ego_sample = scene["tracks"][0]["samples"][0]
    assert ego_sample["position_m"] == [-10.0, 0.0]
    assert ego_sample["recorded_heading_deg"] == 0.0
    assert ego_sample["speed_mps"] == 7.5
    assert ego_sample["brake"] == 0.4
    assert ego_sample["signals"] == [{"signal_id": "north-signal", "state": "green"}]
    assert (
        scene["p1_replay"]["participant_legend"][0]["key_event_state"] == "ego-brakes"
    )
    elements = {
        item["element_id"]: item for item in scene["visual_context"]["elements"]
    }
    assert elements["traffic-signals"]["status"] == "applicable"
    assert elements["conflict-zones"]["status"] == "applicable"
    assert elements["pedestrians"]["status"] == "applicable"


def test_p1_scene_rejects_heading_that_disagrees_with_recorded_motion() -> None:
    playback = _playback()
    playback["trajectory"][0]["heading_deg"] = 180.0

    with pytest.raises(ReplayProjectionError, match="trajectory heading differs"):
        project_replay_scene(playback)


def test_p1_scene_rejects_invalid_signal_and_brake_samples() -> None:
    playback = _playback()
    playback["trajectory"][0]["signals"] = [
        {"signal_id": "north-signal", "state": "purple"}
    ]
    with pytest.raises(ReplayProjectionError, match="trajectory signal"):
        project_replay_scene(playback)

    playback = _playback()
    playback["trajectory"][0]["brake"] = 1.1
    with pytest.raises(ReplayProjectionError, match="trajectory sample"):
        project_replay_scene(playback)


def test_browser_projection_accepts_strictly_ordered_late_participant_only() -> None:
    playback = _playback()
    playback["terminal_tick"] = 11
    playback["participants"] = [
        {
            **participant,
            "role": "ego" if participant["role"] == "ego" else "social",
        }
        for participant in playback["participants"]
    ]
    walker_samples = [
        point for point in playback["trajectory"] if point["participant_id"] == "walker"
    ]
    walker_samples[0]["tick"] = 10
    walker_samples[1]["tick"] = 11
    script = f"""
      import {{projectReplayScene}} from {json.dumps(REPLAY_MODULE.as_uri())};
      const playback = {json.dumps(playback)};
      const scene = projectReplayScene(playback);
      const unordered = structuredClone(playback);
      const walker = unordered.trajectory.filter((point) => point.participant_id === "walker");
      const others = unordered.trajectory.filter((point) => point.participant_id !== "walker");
      unordered.trajectory = [...others, ...walker.reverse()];
      let unorderedError = null;
      try {{
        projectReplayScene(unordered);
      }} catch (error) {{
        unorderedError = String(error instanceof Error ? error.message : error);
      }}
      console.log(JSON.stringify({{
        walkerTicks: scene.tracks.find((track) => track.participantId === "walker").samples.map((sample) => sample.tick),
        unorderedError,
      }}));
    """

    completed = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(completed.stdout) == {
        "walkerTicks": [10, 11],
        "unorderedError": "trajectory sample order is invalid",
    }
