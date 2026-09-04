from __future__ import annotations

import copy

import numpy as np
import pytest

from highwaypilot_lab.strategies import (
    ACTIONS,
    ManualPolicy,
    PolicyError,
    QualifiedRulePolicy,
    RandomPolicy,
)


def snapshot(
    *,
    ego_x: float = 250.0,
    ego_lane: int = 1,
    target_lane: int = 0,
    min_ttc_s: float | None = 8.0,
    vehicles: list[dict] | None = None,
) -> dict:
    return {
        "schema_version": "simulation-snapshot/v1",
        "step": 4,
        "construction": {
            "zone_start_m": 300.0,
            "zone_end_m": 410.0,
            "closed_lane_index": 1,
            "target_lane_index": target_lane,
            "authoritative_merge_action": "LANE_LEFT",
        },
        "ego": {
            "position_m": {"x": ego_x, "y": 4.0},
            "speed_mps": 22.0,
            "lane_index": ego_lane,
            "target_lane_index": ego_lane,
            "crashed": False,
        },
        "vehicles": vehicles or [],
        "reward": {
            "total": 0.25,
            "components": {
                "collision": 0.0,
                "speed": 0.8,
                "lane_change": 0.0,
                "merge_success": 0.0,
                "ttc": 0.0,
                "comfort": 0.1,
            },
        },
        "safety": {"min_ttc_s": min_ttc_s, "collision": False},
        "status": {"terminated": False, "truncated": False, "termination_reason": None},
        "available_actions": list(ACTIONS),
        "last_action": "IDLE",
    }


def test_manual_policy_records_only_canonical_user_actions() -> None:
    policy = ManualPolicy(["FASTER", "LANE_LEFT"])

    first = policy.decide(snapshot())
    second = policy.decide(snapshot())

    assert (first.action, second.action) == ("FASTER", "LANE_LEFT")
    assert policy.action_history == ("FASTER", "LANE_LEFT")
    assert first.strategy_id == "manual"
    with pytest.raises(PolicyError, match="manual action sequence exhausted"):
        policy.decide(snapshot())


def test_random_policy_reset_replays_its_owned_rng_stream() -> None:
    policy = RandomPolicy(np.random.default_rng(731))
    original = [policy.decide(snapshot()).action for _ in range(8)]

    policy.reset()
    replayed = [policy.decide(snapshot()).action for _ in range(8)]

    assert replayed == original
    assert set(replayed) <= set(ACTIONS)


def test_qualified_rule_waits_slows_merges_and_recovers() -> None:
    policy = QualifiedRulePolicy()
    blocked = snapshot(
        ego_x=275.0,
        vehicles=[
            {
                "vehicle_id": "target-ahead",
                "position_m": {"x": 282.0, "y": 0.0},
                "speed_mps": 12.0,
                "lane_index": 0,
            }
        ],
    )
    safe = snapshot(ego_x=275.0)

    waiting = policy.decide(blocked)
    merging = policy.decide(safe)
    recovering = policy.decide(safe)

    assert waiting.action == "SLOWER"
    assert waiting.explanation["target_lane_occupied"] is True
    assert merging.action == "LANE_LEFT"
    assert merging.explanation["front_gap_m"] is None
    assert recovering.action == "SLOWER"
    assert recovering.reason == "merge_retry_recovery"

    merge_in_progress = snapshot(ego_x=285.0)
    merge_in_progress["ego"]["target_lane_index"] = 0
    policy.reset()
    holding = policy.decide(merge_in_progress)
    assert holding.action == "IDLE"
    assert holding.reason == "merge_in_progress"

    low_ttc_with_safe_escape = copy.deepcopy(safe)
    low_ttc_with_safe_escape["safety"]["min_ttc_s"] = 1.5
    policy.reset()
    escaping = policy.decide(low_ttc_with_safe_escape)
    assert escaping.action == "LANE_LEFT"
    assert escaping.reason == "safe_merge_window"

    low_ttc_blocked = copy.deepcopy(blocked)
    low_ttc_blocked["safety"]["min_ttc_s"] = 1.5
    policy.reset()
    braking = policy.decide(low_ttc_blocked)
    assert braking.action == "SLOWER"
    assert braking.reason == "low_ttc_recovery"

    target_lane_low_ttc = snapshot(ego_lane=0, target_lane=0, min_ttc_s=1.5)
    policy.reset()
    target_lane_braking = policy.decide(target_lane_low_ttc)
    assert target_lane_braking.action == "SLOWER"
    assert target_lane_braking.reason == "target_lane_low_ttc_recovery"
