from __future__ import annotations

import json
from pathlib import Path

import pytest

import highwaypilot_lab.strategies.evaluation as evaluation


ROOT = Path(__file__).parents[2]


def normal_config() -> dict:
    return json.loads((ROOT / "configs/presets/normal-v1.json").read_text(encoding="utf-8"))


def test_paired_evaluation_uses_each_distinct_seed_once_per_strategy(monkeypatch) -> None:
    calls: list[tuple[int, str]] = []
    outcomes = {
        (101, "random"): "collision",
        (101, "qualified_rule"): "merge_success",
        (102, "random"): "merge_success",
        (102, "qualified_rule"): "merge_success",
    }

    def fake_episode(config, strategy_id, **_kwargs):
        seed = config["seed"]
        calls.append((seed, strategy_id))
        result = outcomes[(seed, strategy_id)]
        return {
            "config_digest": f"digest-{seed}",
            "strategy": {"id": strategy_id, "version": "v1", "model_version": None},
            "result": result,
            "metrics": {
                "episode_reward": float(seed),
                "average_speed_mps": 20.0,
                "comfort_score": 0.5,
                "completion_time_s": 10.0,
            },
        }

    monkeypatch.setattr(evaluation, "run_evaluation_episode", fake_episode)
    result = evaluation.run_paired_strategy_evaluation(
        normal_config(),
        seeds=[101, 102],
        strategy_ids=["random", "qualified_rule"],
        model_dir=ROOT / "models/construction-dqn-v1",
    )

    assert calls == [
        (101, "random"),
        (101, "qualified_rule"),
        (102, "random"),
        (102, "qualified_rule"),
    ]
    random = result["strategies"][0]
    qualified = result["strategies"][1]
    assert random["rates"]["success"] == {
        "value": 0.5,
        "numerator": 1,
        "denominator": 2,
        "ci95": pytest.approx([0.094531205734, 0.905468794266]),
    }
    assert random["rates"]["collision"]["numerator"] == 1
    assert qualified["rates"]["success"]["value"] == 1.0
    assert qualified["rates"]["collision"]["value"] == 0.0


@pytest.mark.parametrize("seeds", [[101, 101], []])
def test_paired_evaluation_rejects_non_distinct_or_empty_seeds(seeds: list[int]) -> None:
    with pytest.raises(ValueError, match="distinct"):
        evaluation.run_paired_strategy_evaluation(
            normal_config(),
            seeds=seeds,
            strategy_ids=["qualified_rule"],
            model_dir=ROOT / "models/construction-dqn-v1",
        )


def test_manual_evaluation_requires_a_real_recorded_action_sequence() -> None:
    with pytest.raises(ValueError, match="recorded manual_actions"):
        evaluation.run_paired_strategy_evaluation(
            normal_config(),
            seeds=[101, 102],
            strategy_ids=["manual"],
            model_dir=ROOT / "models/construction-dqn-v1",
        )
