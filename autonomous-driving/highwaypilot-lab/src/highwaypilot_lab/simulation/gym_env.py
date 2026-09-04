"""Gymnasium-compatible construction-v0 wrapper over the sole simulation authority."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from highwaypilot_lab.config import DEFAULT_CONFIG, parse_config

from .authority import ACTIONS, ConstructionSimulation
from .observation import OBSERVATION_HIGH, OBSERVATION_LOW, observation_vector


class ConstructionGymEnv(gym.Env[np.ndarray, int]):
    """Standard Gymnasium lifecycle backed by ``ConstructionSimulation``."""

    metadata = {"render_modes": []}

    def __init__(
        self,
        config: Mapping[str, Any] | None = None,
        render_mode: str | None = None,
    ) -> None:
        super().__init__()
        if render_mode is not None:
            raise ValueError("construction-v0 does not provide a Gymnasium render mode")
        requested = copy.deepcopy(dict(config)) if config is not None else copy.deepcopy(DEFAULT_CONFIG)
        requested.setdefault("seed", 101)
        self._base_config = parse_config(requested)
        self._simulation: ConstructionSimulation | None = None
        self._terminal = False
        self.action_space = spaces.Discrete(len(ACTIONS), seed=self._base_config["seed"])
        self.observation_space = spaces.Box(
            low=OBSERVATION_LOW,
            high=OBSERVATION_HIGH,
            dtype=np.float32,
        )

    def _snapshot_result(self, snapshot: Mapping[str, Any]):
        observation = observation_vector(snapshot)
        info = {
            "authority_snapshot": snapshot,
            "config_digest": snapshot["config_digest"],
            "termination_reason": snapshot["status"]["termination_reason"],
        }
        return observation, info

    def reset(
        self,
        *,
        seed: int | None = None,
        options: dict[str, Any] | None = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        super().reset(seed=seed)
        if options not in (None, {}):
            raise ValueError("construction-v0 reset options are not supported")
        if self._simulation is not None:
            self._simulation.close()
        effective = copy.deepcopy(self._base_config)
        if seed is not None:
            effective["seed"] = seed
        effective = parse_config(effective)
        self.action_space.seed(effective["seed"])
        self._simulation = ConstructionSimulation(effective)
        self._terminal = False
        observation, info = self._snapshot_result(self._simulation.snapshot())
        return observation, info

    def step(
        self,
        action: int,
    ) -> tuple[np.ndarray, float, bool, bool, dict[str, Any]]:
        if self._simulation is None:
            raise RuntimeError("construction-v0 must be reset before step")
        if self._terminal:
            raise RuntimeError("construction-v0 is terminal; call reset before step")
        if isinstance(action, bool) or not self.action_space.contains(action):
            raise ValueError(f"invalid construction-v0 action: {action!r}")
        snapshot = self._simulation.step(int(action))
        terminated = bool(snapshot["status"]["terminated"])
        truncated = bool(snapshot["status"]["truncated"])
        self._terminal = terminated or truncated
        observation, info = self._snapshot_result(snapshot)
        return observation, float(snapshot["reward"]["total"]), terminated, truncated, info

    def close(self) -> None:
        if self._simulation is not None:
            self._simulation.close()
            self._simulation = None
        self._terminal = False


__all__ = ["ConstructionGymEnv"]
