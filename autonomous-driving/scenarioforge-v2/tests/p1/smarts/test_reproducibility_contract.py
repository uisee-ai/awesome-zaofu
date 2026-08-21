from __future__ import annotations

from pathlib import Path

import pytest

from scenarioforge.core import strict_loads
from scenarioforge.repro.p1_comparison import (
    P1ComparisonError,
    compare_three_smarts_runs,
    load_smarts_tolerance_profile,
)


PROFILE_PATH = Path("tests/fixtures/p1/smarts-tolerance-profile.json")


def _run(run_id: str, *, x: float = 1.0, terminal: str = "goal") -> dict:
    return {
        "schema_version": "scenarioforge.smarts-run-evidence/v1",
        "scenario_id": "highway_merge",
        "run_id": run_id,
        "execution_snapshot_digest": "a" * 64,
        "backend": {"id": "scenarioforge.smarts", "version": "2.0.1"},
        "scenario_digest": "b" * 64,
        "policy_digest": "c" * 64,
        "seed": 29,
        "parameters_digest": "d" * 64,
        "fixed_timestep_s": 0.1,
        "participants": [
            {"id": "ego", "role": "ego", "controllable": True},
            {"id": "traffic", "role": "social_vehicle", "controllable": False},
        ],
        "events": [
            {
                "event_id": "merge-complete",
                "agent_id": "ego",
                "tick": 2,
            }
        ],
        "terminal_state": {"status": terminal, "reason": terminal},
        "metrics": {"min_ttc_s": 2.5, "completed_steps": 2},
        "trajectory": [
            {
                "agent_id": "ego",
                "tick": 0,
                "position_m": [0.0, 0.0, 0.0],
                "speed_mps": 8.0,
                "heading_deg": 359.8,
            },
            {
                "agent_id": "ego",
                "tick": 1,
                "position_m": [x, 0.0, 0.0],
                "speed_mps": 8.0,
                "heading_deg": 0.2,
            },
        ],
        "road_geometry": {
            "schema_version": "scenarioforge.smarts-road-geometry/v1",
            "source": "scenarioforge.smarts/2.0.1:road-map",
            "topology_kind": "merge",
            "traffic_rule": "right-hand-traffic",
            "lanes": [
                {
                    "lane_id": "merge-in_0",
                    "road_id": "merge-in",
                    "kind": "road",
                    "centerline_m": [[0.0, 0.0], [10.0, 0.0]],
                    "left_boundary_m": [[0.0, 1.6], [10.0, 1.6]],
                    "right_boundary_m": [[0.0, -1.6], [10.0, -1.6]],
                }
            ],
            "conflict_zones": [],
        },
    }


def test_versioned_smarts_profile_freezes_p1_limits_and_metadrive_non_regression() -> None:
    raw = strict_loads(PROFILE_PATH.read_bytes())
    assert raw == {
        "schema_version": "scenarioforge.smarts-tolerance-profile/v1",
        "profile_id": "scenarioforge.smarts-2.0.1-linux-x86_64/v1",
        "run_count": 3,
        "position_abs_m": 0.01,
        "speed_abs_mps": 0.01,
        "heading_abs_deg": 1.0,
        "min_ttc_abs_s": 0.01,
        "completed_steps": 1,
        "metadrive_profile_ref": "scenarioforge.p0c-metadrive-0.4.3/v1",
    }
    assert load_smarts_tolerance_profile(PROFILE_PATH).to_dict() == raw


def test_three_run_comparison_matches_discrete_state_and_circular_heading() -> None:
    report = compare_three_smarts_runs(
        [_run("run-1"), _run("run-2", x=1.005), _run("run-3", x=0.995)],
        load_smarts_tolerance_profile(PROFILE_PATH),
    )
    assert report == {
        "schema_version": "scenarioforge.smarts-reproducibility-report/v1",
        "profile_id": "scenarioforge.smarts-2.0.1-linux-x86_64/v1",
        "run_ids": ["run-1", "run-2", "run-3"],
        "discrete": {
            "events_match": True,
            "terminal_state_match": True,
            "passed": True,
        },
        "continuous": {
            "aligned_agent_ids": ["ego"],
            "aligned_ticks": [0, 1],
            "max_deltas": {
                "position_abs_m": 0.01,
                "speed_abs_mps": 0.0,
                "heading_abs_deg": 0.0,
                "min_ttc_abs_s": 0.0,
                "completed_steps": 0,
            },
            "violations": [],
            "passed": True,
        },
        "passed": True,
    }


def test_comparison_accepts_complete_canonical_run_evidence_and_rejects_field_drift() -> None:
    runs = [_run("run-1"), _run("run-2"), _run("run-3")]

    assert set(runs[0]) == {
        "schema_version",
        "scenario_id",
        "run_id",
        "execution_snapshot_digest",
        "backend",
        "scenario_digest",
        "policy_digest",
        "seed",
        "parameters_digest",
        "fixed_timestep_s",
        "participants",
        "events",
        "terminal_state",
        "metrics",
        "trajectory",
        "road_geometry",
    }
    assert compare_three_smarts_runs(
        runs, load_smarts_tolerance_profile(PROFILE_PATH)
    )["passed"] is True

    missing = _run("run-3")
    missing.pop("road_geometry")
    with pytest.raises(P1ComparisonError, match="incomplete or unknown"):
        compare_three_smarts_runs(
            [_run("run-1"), _run("run-2"), missing],
            load_smarts_tolerance_profile(PROFILE_PATH),
        )

    unknown = _run("run-3")
    unknown["legacy_scenario"] = "highway_merge"
    with pytest.raises(P1ComparisonError, match="incomplete or unknown"):
        compare_three_smarts_runs(
            [_run("run-1"), _run("run-2"), unknown],
            load_smarts_tolerance_profile(PROFILE_PATH),
        )


@pytest.mark.parametrize(
    ("runs", "message"),
    [
        ([_run("run-1"), _run("run-2")], "exactly three"),
        ([_run("same"), _run("same"), _run("run-3")], "independent run IDs"),
        ([_run("run-1"), _run("run-2"), _run("run-3", terminal="collision")], ""),
    ],
)
def test_comparison_rejects_invalid_scope_or_reports_discrete_mismatch(
    runs: list[dict], message: str
) -> None:
    profile = load_smarts_tolerance_profile(PROFILE_PATH)
    if message:
        with pytest.raises(P1ComparisonError, match=message):
            compare_three_smarts_runs(runs, profile)
    else:
        report = compare_three_smarts_runs(runs, profile)
        assert report["discrete"] == {
            "events_match": True,
            "terminal_state_match": False,
            "passed": False,
        }
        assert report["passed"] is False


def test_comparison_fails_closed_on_scope_drift_alignment_and_tolerance_violation() -> None:
    profile = load_smarts_tolerance_profile(PROFILE_PATH)
    drifted = _run("run-3")
    drifted["seed"] = 30
    with pytest.raises(P1ComparisonError, match="locked comparison scope"):
        compare_three_smarts_runs([_run("run-1"), _run("run-2"), drifted], profile)

    for field, replacement in (
        ("scenario_id", "competitive_lane_change"),
        ("fixed_timestep_s", 0.2),
        ("participants", []),
        ("road_geometry", {"schema_version": "different"}),
    ):
        drifted = _run("run-3")
        drifted[field] = replacement
        with pytest.raises(P1ComparisonError, match="locked comparison scope"):
            compare_three_smarts_runs(
                [_run("run-1"), _run("run-2"), drifted], profile
            )

    misaligned = _run("run-3")
    misaligned["trajectory"].pop()
    report = compare_three_smarts_runs(
        [_run("run-1"), _run("run-2"), misaligned], profile
    )
    assert report["continuous"]["violations"] == [
        {
            "field": "trajectory_alignment",
            "run_index": 3,
            "missing": [["ego", 1]],
            "unexpected": [],
        }
    ]
    assert report["passed"] is False

    report = compare_three_smarts_runs(
        [_run("run-1"), _run("run-2"), _run("run-3", x=1.011)], profile
    )
    assert report["continuous"]["violations"] == [
        {
            "field": "position_abs_m",
            "maximum_delta": 0.011,
            "tolerance": 0.01,
        }
    ]
    assert report["passed"] is False
