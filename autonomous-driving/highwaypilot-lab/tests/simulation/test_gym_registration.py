from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import gymnasium as gym
import numpy as np
import pytest
from gymnasium.utils.env_checker import check_env

import highwaypilot_lab
from highwaypilot_lab.simulation import ConstructionSimulation


ROOT = Path(__file__).resolve().parents[2]


def load_normal() -> dict[str, object]:
    return json.loads((ROOT / "configs/presets/normal-v1.json").read_text(encoding="utf-8"))


def test_construction_v0_is_registered_and_passes_the_gym_checker() -> None:
    assert highwaypilot_lab.GYM_ENV_ID == "construction-v0"
    assert "construction-v0" in gym.registry
    env = gym.make("construction-v0", config=load_normal())
    try:
        check_env(env.unwrapped, skip_render_check=True)
    finally:
        env.close()


def test_gym_and_direct_authority_return_the_same_trajectory() -> None:
    config = load_normal()
    env = gym.make("construction-v0", config=config)
    direct = ConstructionSimulation.from_config(config)
    try:
        observation, info = env.reset(seed=int(config["seed"]))
        assert observation.shape == (10,)
        assert observation.dtype == np.float32
        assert info["authority_snapshot"] == direct.snapshot()
        for action in [1, 3, 0, 1, 4]:
            _, reward, terminated, truncated, info = env.step(action)
            snapshot = direct.step(action)
            assert info["authority_snapshot"] == snapshot
            assert reward == snapshot["reward"]["total"]
            assert terminated == snapshot["status"]["terminated"]
            assert truncated == snapshot["status"]["truncated"]
            if terminated or truncated:
                break
    finally:
        env.close()
        direct.close()


def test_repeated_reset_with_the_same_seed_is_reproducible() -> None:
    env = gym.make("construction-v0", config=load_normal())
    try:
        first_observation, first_info = env.reset(seed=912)
        first_step = env.step(1)
        second_observation, second_info = env.reset(seed=912)
        second_step = env.step(1)
        np.testing.assert_array_equal(first_observation, second_observation)
        assert first_info == second_info
        np.testing.assert_array_equal(first_step[0], second_step[0])
        assert first_step[1:] == second_step[1:]
    finally:
        env.close()


def test_terminal_gym_environment_requires_reset_before_another_step() -> None:
    config = load_normal()
    config["ego"]["initial_position_m"] = 220.0
    config["ego"]["initial_speed_mps"] = 24.0
    config["traffic"]["vehicles_count"] = 0
    env = gym.make("construction-v0", config=config)
    try:
        env.reset()
        for _ in range(50):
            _, _, terminated, truncated, _ = env.step(1)
            if terminated or truncated:
                break
        assert terminated or truncated
        with pytest.raises(RuntimeError, match="terminal"):
            env.step(1)
    finally:
        env.close()


def test_registration_works_in_a_clean_subprocess() -> None:
    script = """
import gymnasium as gym
assert 'construction-v0' not in gym.registry
import highwaypilot_lab
assert 'construction-v0' in gym.registry
env = gym.make('construction-v0')
observation, info = env.reset(seed=101)
assert observation.shape == (10,)
assert info['authority_snapshot']['authority'] == 'python'
env.close()
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "src")
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
