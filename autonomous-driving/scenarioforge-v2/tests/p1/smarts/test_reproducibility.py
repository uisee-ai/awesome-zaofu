from __future__ import annotations

from pathlib import Path

from scenarioforge.repro.p1_comparison import (
    compare_three_smarts_runs,
    load_smarts_tolerance_profile,
)
from scenarioforge.runtime.smarts_worker import run_canonical_smarts_scenario


def test_three_independent_real_smarts_runs_satisfy_the_locked_p1_profile() -> None:
    runs = [
        run_canonical_smarts_scenario(
            "highway_merge",
            run_id=f"real-repro-{index}",
            max_episode_steps=12,
        )
        for index in range(1, 4)
    ]

    report = compare_three_smarts_runs(
        runs,
        load_smarts_tolerance_profile(
            Path("tests/fixtures/p1/smarts-tolerance-profile.json")
        ),
    )
    assert report["passed"] is True, report
    assert report["discrete"] == {
        "events_match": True,
        "terminal_state_match": True,
        "passed": True,
    }
    assert report["continuous"]["max_deltas"] == {
        "position_abs_m": 0.0,
        "speed_abs_mps": 0.0,
        "heading_abs_deg": 0.0,
        "min_ttc_abs_s": 0.0,
        "completed_steps": 0,
    }
