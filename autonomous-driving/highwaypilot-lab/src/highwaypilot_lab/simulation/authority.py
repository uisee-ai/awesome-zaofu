"""Stable public authority wrapper around the upstream environment."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from highwaypilot_lab.config import parse_config, parse_config_json
from highwaypilot_lab.rng import RNGStreams

from .environment import ACTION_INDEXES, ACTIONS, ConstructionEnv


class SimulationError(RuntimeError):
    """A fail-closed simulation lifecycle or action error."""


class ConstructionSimulation:
    """Own one complete config, RNG stream set, and authoritative env run."""

    def __init__(self, effective_config: Mapping[str, Any]) -> None:
        self.effective_config = parse_config(effective_config)
        self.streams = RNGStreams(self.effective_config)
        self.env_seed = self.streams.take_env_seed()
        self._env = ConstructionEnv(self.effective_config, self.streams, self.env_seed)

    @classmethod
    def from_config(
        cls,
        config: Mapping[str, Any] | str | bytes,
        *,
        api_seed: object | None = None,
    ) -> "ConstructionSimulation":
        effective = (
            parse_config_json(config, api_seed=api_seed)
            if isinstance(config, (str, bytes))
            else parse_config(config, api_seed=api_seed)
        )
        return cls(effective)

    def snapshot(self) -> dict[str, Any]:
        return self._env.authoritative_snapshot()

    def step(self, action: int | str) -> dict[str, Any]:
        if self._env._last_terminated or self._env._last_truncated:
            raise SimulationError("simulation is terminal")
        if isinstance(action, bool):
            raise SimulationError("action must be an integer index or canonical label")
        if isinstance(action, str):
            try:
                action_index = ACTION_INDEXES[action]
            except KeyError as error:
                raise SimulationError(f"unknown action: {action}") from error
        elif isinstance(action, int) and action in ACTIONS:
            action_index = action
        else:
            raise SimulationError(f"unknown action: {action}")
        self._env.step(action_index)
        return self.snapshot()

    def random_policy_generator(self):
        """Return only the random-policy-owned stream for TASK-HPL-005 consumers."""

        return self.streams.generator("random_policy")

    def close(self) -> None:
        self._env.close()
