"""Public package entry point and Gymnasium environment registration."""

from __future__ import annotations

from gymnasium.envs.registration import register, registry


GYM_ENV_ID = "construction-v0"


def _register_gym_environment() -> None:
    if GYM_ENV_ID not in registry:
        register(
            id=GYM_ENV_ID,
            entry_point="highwaypilot_lab.simulation.gym_env:ConstructionGymEnv",
        )


_register_gym_environment()

__all__ = ["GYM_ENV_ID"]
