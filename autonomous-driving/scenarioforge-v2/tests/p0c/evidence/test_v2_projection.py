from __future__ import annotations

from pathlib import Path

import pytest

from scenarioforge.web.evidence import PublishedEvidenceReader


def test_v2_terminal_projects_bound_axes_and_explainable_metrics(
    v2_publication: Path,
) -> None:
    terminal = PublishedEvidenceReader(publish_root=v2_publication.parents[1]).terminal(
        "run-v2-evidence", "attempt-0001"
    )

    assert set(terminal) == {
        "schema_version",
        "scenario_id",
        "run_id",
        "attempt_id",
        "execution_status",
        "scenario_outcome",
        "termination_reason",
        "terminal",
        "failure_stage",
        "playable",
        "playback_reason",
        "seed",
        "policy",
        "digests",
        "logical_ref",
        "evidence",
        "metrics",
        "metric_projections",
        "participants",
        "events",
    }
    assert terminal["schema_version"] == "scenarioforge.terminal-evidence/v2"
    assert {
        key: terminal[key]
        for key in (
            "execution_status",
            "scenario_outcome",
            "termination_reason",
        )
    } == {
        "execution_status": "completed",
        "scenario_outcome": "collision_failure",
        "termination_reason": "collision",
    }
    assert terminal["playable"] is True
    assert "status" not in terminal
    assert "reason" not in terminal
    assert terminal["metrics"] == {
        "collision": True,
        "collision_participants": ["cutter", "ego"],
        "min_ttc_s": pytest.approx(0.5),
        "minimum_acceleration_mps2": pytest.approx(-7.0),
        "completion_time_s": None,
        "terminal_tick": 12,
    }
    assert terminal["participants"] == [
        {"id": "ego", "role": "ego"},
        {"id": "cutter", "role": "social"},
    ]
    assert [item["ref"].split("/", 3)[-1] for item in terminal["evidence"]] == [
        "input/assets.json",
        "input/compile_report.json",
        "input/execution_plan.json",
        "input/policy.json",
        "input/run_manifest.json",
        "input/run_request.json",
        "output/actions.json",
        "output/events.json",
        "output/metrics.json",
        "output/trajectory.json",
        "output/worker_result.json",
    ]
    assert all(
        set(item) == {"ref", "status", "size_bytes", "digest", "validation"}
        and item["status"] == "present"
        and item["validation"] == "verified"
        for item in terminal["evidence"]
    )

    assert [item["metric"] for item in terminal["metric_projections"]] == [
        "collision",
        "hard_braking",
        "minimum_ttc",
        "completion_time",
        "termination_reason",
    ]
    assert all(
        set(item)
        == {
            "definition_id",
            "metric",
            "unit",
            "participant_ids",
            "topology_kinds",
            "value",
            "threshold",
            "threshold_met",
            "null_semantics",
            "explanation",
            "raw_evidence_value",
            "evidence_field",
        }
        for item in terminal["metric_projections"]
    )
    projections = {item["metric"]: item for item in terminal["metric_projections"]}
    assert projections["collision"] == {
        "definition_id": "scenarioforge.metric.collision/v2",
        "metric": "collision",
        "unit": "boolean",
        "participant_ids": ["ego", "cutter"],
        "topology_kinds": ["corridor_merge"],
        "value": True,
        "threshold": None,
        "threshold_met": None,
        "null_semantics": "not_applicable",
        "explanation": "Whether a collision occurred for the applicable participants.",
        "raw_evidence_value": True,
        "evidence_field": "collision",
    }
    assert projections["hard_braking"]["value"] == pytest.approx(-7.0)
    assert projections["hard_braking"]["raw_evidence_value"] == pytest.approx(-7.0)
    assert projections["minimum_ttc"]["value"] == pytest.approx(0.5)
    assert projections["completion_time"]["value"] is None
    assert projections["termination_reason"]["value"] == "collision"
    assert all(item["explanation"] for item in projections.values())
    assert terminal["events"] == [
        {
            "event_id": (
                "dangerous-cut-in-started"
                if sequence == 0
                else f"dangerous-cut-in-control-{sequence + 1}"
            ),
            "sequence": sequence,
            "type": "trigger_fired",
            "participant_id": "cutter",
            "trigger_tick": sequence + 5,
            "effect_state_tick": sequence + 6,
            "duration_ticks": 1,
            "action": {"steering": -1.0, "throttle_brake": 0.0},
        }
        for sequence in range(7)
    ]


def test_v2_playback_returns_complete_validated_trajectory_and_events(
    v2_publication: Path,
) -> None:
    playback = PublishedEvidenceReader(publish_root=v2_publication.parents[1]).playback(
        "run-v2-evidence", "attempt-0001"
    )

    assert set(playback) == {
        "schema_version",
        "scenario_id",
        "run_id",
        "attempt_id",
        "execution_status",
        "scenario_outcome",
        "termination_reason",
        "logical_ref",
        "trajectory_digest",
        "road",
        "participants",
        "sample_interval_s",
        "terminal_tick",
        "events",
        "trajectory",
    }
    assert playback["schema_version"] == "scenarioforge.playback/v2"
    assert playback["execution_status"] == "completed"
    assert playback["scenario_outcome"] == "collision_failure"
    assert playback["termination_reason"] == "collision"
    assert playback["scenario_id"] == "dangerous_cut_in"
    assert playback["terminal_tick"] == 12
    assert len(playback["trajectory"]) == 26
    assert [item["sequence"] for item in playback["events"]] == list(range(7))
    road = dict(playback["road"])
    geometry = road.pop("geometry")
    assert road == {
        "schema_version": "scenarioforge.topology/v2",
        "topology_kind": "corridor_merge",
        "map_block_sequence": "S",
        "lane_width_m": pytest.approx(3.5),
        "coordinate_system": "right-handed-x-forward-y-left",
        "units": {"distance": "m", "speed": "m/s", "heading": "deg", "time": "tick"},
        "lanes": [
            {
                "id": "adjacent-lane",
                "road_id": "mainline",
                "engine_lane_index": {
                    "start_node": ">>",
                    "end_node": ">>>",
                    "lane_index": 0,
                },
                "kind": "travel",
                "length_m": pytest.approx(220.0),
                "predecessor_lane_ids": [],
                "successor_lane_ids": ["ego-lane"],
            },
            {
                "id": "ego-lane",
                "road_id": "mainline",
                "engine_lane_index": {
                    "start_node": ">>",
                    "end_node": ">>>",
                    "lane_index": 1,
                },
                "kind": "merge",
                "length_m": pytest.approx(220.0),
                "predecessor_lane_ids": ["adjacent-lane"],
                "successor_lane_ids": [],
            },
        ],
        "conflict_zones": [
            {
                "id": "cut-in-conflict",
                "lane_ids": ["adjacent-lane", "ego-lane"],
                "start_m": pytest.approx(35.0),
                "end_m": pytest.approx(80.0),
            }
        ],
    }
    assert geometry["schema_version"] == "scenarioforge.road-geometry/v1"
    assert geometry["source"] == "metadrive-road-network"
    assert [lane["lane_id"] for lane in geometry["lanes"]] == [
        "adjacent-lane",
        "ego-lane",
    ]
    assert [zone["zone_id"] for zone in geometry["conflict_zones"]] == [
        "cut-in-conflict"
    ]
    trajectory = playback["trajectory"]
    assert [item["tick"] for item in trajectory] == [
        tick for tick in range(13) for _ in range(2)
    ]
    assert [item["participant_id"] for item in trajectory] == [
        participant for _ in range(13) for participant in ("ego", "cutter")
    ]
    assert all(
        set(item)
        == {
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
        }
        for item in trajectory
    )
    assert trajectory[0] == {
        "schema_version": "scenarioforge.trajectory-point/v2",
        "tick": 0,
        "participant_id": "ego",
        "position_m": [20.0, 3.5],
        "speed_mps": 21.0,
        "heading_deg": 0.0,
        "collision": False,
        "lane_id": "ego-lane",
        "engine_lane_index": [">>", ">>>", 1],
        "lane_longitudinal_m": 20.0,
        "route_id": "ego-mainline",
        "route_destination_lane_id": "ego-lane",
        "route_destination_engine_lane_index": [">>", ">>>", 1],
        "route_destination_matches": True,
        "route_checkpoints": [">>", ">>>"],
        "route_completed": False,
        "boundary_violation": False,
        "wrong_route": False,
    }
    assert trajectory[-1]["collision"] is True
    assert trajectory[-1]["tick"] == 12
    assert trajectory[-1]["participant_id"] == "cutter"
