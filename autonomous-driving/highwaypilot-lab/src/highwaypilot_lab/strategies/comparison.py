"""Run the four v1 strategies against identical config and seed inputs."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from highwaypilot_lab.config import parse_config
from highwaypilot_lab.simulation import ConstructionSimulation

from .policy import ManualPolicy, OnnxLearningPolicy, QualifiedRulePolicy, RandomPolicy, Strategy


COMFORT_SCORE_LABEL = "舒适度得分（奖励分量）"


def _rounded(value: float) -> float:
    return round(float(value), 12)


def run_strategy_episode(
    effective_config: Mapping[str, Any],
    policy: Strategy,
    *,
    max_steps: int,
) -> dict[str, Any]:
    simulation = ConstructionSimulation(effective_config)
    policy.reset()
    initial = simulation.snapshot()
    current = initial
    decisions: list[dict[str, Any]] = []
    speeds = [float(initial["ego"]["speed_mps"])]
    total_reward = 0.0
    comfort_score = 0.0
    lane_changes = 0
    minimum_ttc: float | None = initial["safety"]["min_ttc_s"]
    try:
        for _ in range(max_steps):
            decision = policy.decide(current)
            before_lane = int(current["ego"]["lane_index"])
            current = simulation.step(decision.action)
            after_lane = int(current["ego"]["lane_index"])
            lane_changes += int(before_lane != after_lane)
            speeds.append(float(current["ego"]["speed_mps"]))
            total_reward += float(current["reward"]["total"])
            comfort_score += float(current["reward"]["components"]["comfort"])
            ttc = current["safety"]["min_ttc_s"]
            if ttc is not None:
                minimum_ttc = float(ttc) if minimum_ttc is None else min(minimum_ttc, float(ttc))
            decisions.append(
                {
                    "step": current["step"],
                    "decision": decision.to_dict(),
                    "frame": current,
                    "reward": current["reward"],
                    "status": current["status"],
                }
            )
            if current["status"]["terminated"] or current["status"]["truncated"]:
                break
    finally:
        simulation.close()
    reason = current["status"]["termination_reason"] or "step_limit"
    return {
        "schema_version": "strategy-episode/v1",
        "config_digest": initial["config_digest"],
        "seed": effective_config["seed"],
        "strategy": {
            "id": policy.strategy_id,
            "version": policy.strategy_version,
            "model_version": decisions[0]["decision"]["model_version"] if decisions else None,
        },
        "initial_snapshot": initial,
        "decisions": decisions,
        "result": reason,
        "final_snapshot": current,
        "metrics": {
            "episode_reward": _rounded(total_reward),
            "outcome": reason,
            "collision": reason == "collision",
            "success": reason == "merge_success",
            "timeout": reason in {"timeout", "step_limit"},
            "average_speed_mps": _rounded(sum(speeds) / len(speeds)),
            "completion_time_s": _rounded(current["time_s"]),
            "lane_change_count": lane_changes,
            "minimum_ttc_s": None if minimum_ttc is None else _rounded(minimum_ttc),
            "comfort_score": _rounded(comfort_score),
            "comfort_score_label": COMFORT_SCORE_LABEL,
        },
    }


def run_four_policy_comparison(
    config: Mapping[str, Any],
    *,
    manual_actions: Iterable[str],
    model_dir: str | Path,
    max_steps: int = 500,
) -> dict[str, Any]:
    if type(max_steps) is not int or max_steps <= 0:
        raise ValueError("max_steps must be a positive integer")
    effective = parse_config(config)
    policies: list[Strategy] = []
    manual = ManualPolicy(manual_actions)
    policies.append(manual)

    random_simulation = ConstructionSimulation(effective)
    random_generator = random_simulation.random_policy_generator()
    random_policy = RandomPolicy(random_generator)
    random_simulation.close()
    policies.extend(
        [
            random_policy,
            QualifiedRulePolicy(),
            OnnxLearningPolicy(model_dir),
        ]
    )
    episodes = [
        run_strategy_episode(effective, policy, max_steps=max_steps)
        for policy in policies
    ]
    return {
        "schema_version": "strategy-comparison/v1",
        "seed": effective["seed"],
        "config_digest": episodes[0]["config_digest"],
        "episodes": episodes,
        "aggregation": None,
        "aggregation_reason": "single episodes do not define rates, rankings or confidence intervals",
    }
