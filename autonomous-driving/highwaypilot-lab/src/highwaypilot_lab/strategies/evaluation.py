"""Paired multi-seed strategy evaluation and mechanically derived rates."""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from highwaypilot_lab.config import UINT32_MAX, parse_config
from highwaypilot_lab.simulation import ConstructionSimulation

from .comparison import run_strategy_episode
from .policy import ManualPolicy, OnnxLearningPolicy, QualifiedRulePolicy, RandomPolicy, Strategy


AUTONOMOUS_STRATEGIES = ("random", "qualified_rule", "construction_dqn_onnx")
SUPPORTED_STRATEGIES = ("manual", *AUTONOMOUS_STRATEGIES)


class EvaluationCancelled(RuntimeError):
    """Raised only at an Episode boundary after an explicit cancellation."""


def _rounded(value: float) -> float:
    return round(float(value), 12)


def _wilson_interval(successes: int, total: int, z: float = 1.959963984540054) -> list[float]:
    if total <= 0:
        raise ValueError("rate denominator must be positive")
    proportion = successes / total
    denominator = 1.0 + z * z / total
    centre = (proportion + z * z / (2.0 * total)) / denominator
    radius = z * math.sqrt(
        proportion * (1.0 - proportion) / total + z * z / (4.0 * total * total)
    ) / denominator
    return [_rounded(max(0.0, centre - radius)), _rounded(min(1.0, centre + radius))]


def _rate(count: int, total: int) -> dict[str, Any]:
    return {
        "value": _rounded(count / total),
        "numerator": count,
        "denominator": total,
        "ci95": _wilson_interval(count, total),
    }


def _mean(episodes: Sequence[Mapping[str, Any]], metric: str) -> float:
    return _rounded(sum(float(item["metrics"][metric]) for item in episodes) / len(episodes))


def _strategy(
    strategy_id: str,
    effective_config: Mapping[str, Any],
    *,
    manual_actions: Sequence[str] | None,
    model_dir: str | Path,
) -> Strategy:
    if strategy_id == "manual":
        if not manual_actions:
            raise ValueError("manual strategy requires a non-empty recorded action sequence")
        return ManualPolicy(manual_actions)
    if strategy_id == "random":
        owner = ConstructionSimulation(effective_config)
        try:
            generator = owner.random_policy_generator()
            return RandomPolicy(generator)
        finally:
            owner.close()
    if strategy_id == "qualified_rule":
        return QualifiedRulePolicy()
    if strategy_id == "construction_dqn_onnx":
        return OnnxLearningPolicy(model_dir)
    raise ValueError(f"unsupported strategy: {strategy_id}")


def run_evaluation_episode(
    config: Mapping[str, Any],
    strategy_id: str,
    *,
    manual_actions: Sequence[str] | None,
    model_dir: str | Path,
    max_steps: int,
) -> dict[str, Any]:
    effective = parse_config(config)
    policy = _strategy(
        strategy_id,
        effective,
        manual_actions=manual_actions,
        model_dir=model_dir,
    )
    return run_strategy_episode(effective, policy, max_steps=max_steps)


def run_paired_strategy_evaluation(
    config: Mapping[str, Any],
    *,
    seeds: Iterable[int],
    strategy_ids: Sequence[str] = AUTONOMOUS_STRATEGIES,
    manual_actions: Sequence[str] | None = None,
    model_dir: str | Path,
    max_steps: int = 500,
    progress: Callable[[int, int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Evaluate every strategy on the exact same ordered set of distinct Seeds."""

    base = parse_config(config)
    seed_values = list(seeds)
    if not seed_values or len(seed_values) != len(set(seed_values)):
        raise ValueError("evaluation seeds must be a non-empty distinct sequence")
    if any(type(seed) is not int or not 0 <= seed <= UINT32_MAX for seed in seed_values):
        raise ValueError(f"evaluation seeds must be integers between 0 and {UINT32_MAX}")
    selected = list(strategy_ids)
    if not selected or len(selected) != len(set(selected)):
        raise ValueError("strategies must be a non-empty distinct sequence")
    if any(strategy_id not in SUPPORTED_STRATEGIES for strategy_id in selected):
        raise ValueError("evaluation contains an unsupported strategy")
    if "manual" in selected and not manual_actions:
        raise ValueError("manual strategy requires recorded manual_actions")
    if type(max_steps) is not int or max_steps <= 0:
        raise ValueError("max_steps must be a positive integer")

    total = len(seed_values) * len(selected)
    completed = 0
    episodes: list[dict[str, Any]] = []
    for seed in seed_values:
        paired_config = dict(base)
        paired_config["seed"] = seed
        effective = parse_config(paired_config)
        for strategy_id in selected:
            if cancelled is not None and cancelled():
                raise EvaluationCancelled("evaluation cancelled at an Episode boundary")
            episode = run_evaluation_episode(
                effective,
                strategy_id,
                manual_actions=manual_actions,
                model_dir=model_dir,
                max_steps=max_steps,
            )
            episodes.append(
                {
                    "episode_id": f"{strategy_id}-{seed}",
                    "seed": seed,
                    "config_digest": episode["config_digest"],
                    "strategy": episode["strategy"],
                    "result": episode["result"],
                    "metrics": episode["metrics"],
                }
            )
            completed += 1
            if progress is not None:
                progress(completed, total)

    aggregates: list[dict[str, Any]] = []
    for strategy_id in selected:
        owned = [item for item in episodes if item["strategy"]["id"] == strategy_id]
        outcomes = {
            reason: sum(item["result"] == reason for item in owned)
            for reason in ("merge_success", "collision", "timeout", "offroad", "step_limit")
        }
        outcomes["other_failure"] = sum(item["result"] not in outcomes for item in owned)
        timeout_count = outcomes["timeout"] + outcomes["step_limit"]
        aggregates.append(
            {
                "strategy": owned[0]["strategy"],
                "episode_count": len(owned),
                "outcomes": outcomes,
                "rates": {
                    "success": _rate(outcomes["merge_success"], len(owned)),
                    "collision": _rate(outcomes["collision"], len(owned)),
                    "timeout": _rate(timeout_count, len(owned)),
                    "offroad": _rate(outcomes["offroad"], len(owned)),
                },
                "means": {
                    "episode_reward": _mean(owned, "episode_reward"),
                    "average_speed_mps": _mean(owned, "average_speed_mps"),
                    "comfort_score": _mean(owned, "comfort_score"),
                    "completion_time_s": _mean(owned, "completion_time_s"),
                },
            }
        )
    return {
        "schema_version": "strategy-evaluation/v1",
        "seeds": seed_values,
        "episodes_per_strategy": len(seed_values),
        "strategy_order": selected,
        "total_episodes": total,
        "episodes": episodes,
        "strategies": aggregates,
    }
