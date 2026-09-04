from __future__ import annotations

import json
from pathlib import Path

from highwaypilot_lab.strategies import run_four_policy_comparison


ROOT = Path(__file__).resolve().parents[2]


def test_four_policy_comparison_is_traceable_and_never_fabricates_rates() -> None:
    config = json.loads((ROOT / "configs/presets/normal-v1.json").read_text())
    result = run_four_policy_comparison(
        config,
        manual_actions=["SLOWER"] * 60,
        model_dir=ROOT / "models/construction-dqn-v1",
        max_steps=60,
    )

    assert result["schema_version"] == "strategy-comparison/v1"
    assert result["seed"] == config["seed"]
    assert [episode["strategy"]["id"] for episode in result["episodes"]] == [
        "manual",
        "random",
        "qualified_rule",
        "construction_dqn_onnx",
    ]
    assert len({episode["config_digest"] for episode in result["episodes"]}) == 1
    for episode in result["episodes"]:
        assert episode["initial_snapshot"]["step"] == 0
        assert episode["decisions"]
        assert episode["metrics"]["comfort_score_label"] == "舒适度得分（奖励分量）"
        assert episode["metrics"]["collision"] is (episode["result"] == "collision")
        assert episode["metrics"]["success"] is (episode["result"] == "merge_success")
        assert episode["metrics"]["timeout"] is (episode["result"] in {"timeout", "step_limit"})
        assert all("frame" in decision for decision in episode["decisions"])
        assert "success_rate" not in episode["metrics"]
        assert "collision_rate" not in episode["metrics"]
        assert "ranking" not in episode["metrics"]
        assert episode["result"] in {"collision", "merge_success", "missed_merge", "offroad", "timeout", "step_limit"}


def test_same_config_seed_comparison_is_reproducible() -> None:
    config = json.loads((ROOT / "configs/presets/normal-v1.json").read_text())
    kwargs = {
        "manual_actions": ["SLOWER"] * 12,
        "model_dir": ROOT / "models/construction-dqn-v1",
        "max_steps": 12,
    }

    assert run_four_policy_comparison(config, **kwargs) == run_four_policy_comparison(
        config, **kwargs
    )
