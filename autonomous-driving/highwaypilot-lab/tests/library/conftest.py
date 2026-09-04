from __future__ import annotations

import copy

import pytest


@pytest.fixture
def replay_document() -> dict:
    return {
        "schema_version": "highwaypilot-replay/v1",
        "episode_id": "episode-001",
        "initial_frame": {"vehicles": [], "time": 0.0},
        "actions": [
            {
                "index": 0,
                "action": "IDLE",
                "frame": {"vehicles": [], "time": 0.1},
                "reward": {"lane": 0.4, "speed": 0.6},
            }
        ],
        "strategy": {"kind": "manual", "name": "human"},
        "seed": 42,
        "effective_config": {"duration": 40, "lanes_count": 4},
        "rng_contract": {"algorithm": "numpy-pcg64", "seed": 42},
        "versions": {
            "application": "0.1.0",
            "highway_env": "1.10.2",
            "gymnasium": "1.0.0",
            "python": "3.11.9",
            "git": "deadbeef",
            "platform": "linux-x86_64",
        },
        "reward_decomposition": {"lane": 0.4, "speed": 0.6},
        "result": "completed",
        "termination_reason": "duration_reached",
        "ownership": {
            "project_id": "project-a",
            "temporary_session_id": "session-a",
            "created_at": "2026-08-25T01:00:00Z",
        },
    }


@pytest.fixture
def replay_copy(replay_document):
    return lambda: copy.deepcopy(replay_document)
