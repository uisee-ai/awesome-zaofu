from __future__ import annotations

import copy

import pytest


@pytest.fixture
def scenario_payload() -> dict[str, object]:
    return {
        "schema_version": "scenarioforge.scenario-spec.v1",
        "name": "canonical-demo",
        "map": {
            "block_sequence": "S",
            "lane_count": 2,
            "lane_width": 3.5,
        },
        "actors": [
            {"id": "ego", "role": "ego"},
            {"id": "npc-1", "role": "traffic"},
        ],
        "environment": {"traffic_density": 0.1},
        "tags": ["demo"],
    }


@pytest.fixture
def run_request_payload() -> dict[str, object]:
    return {
        "schema_version": "scenarioforge.run-request.v1",
        "scenario_digest": "0" * 64,
        "seeds": [17, 23],
        "profile": "default",
        "limits": {
            "workers": 1,
            "aggregate_cpu_threads": 2,
            "max_steps": 40,
            "max_simulated_seconds": 30.0,
            "case_wall_seconds": 60.0,
            "bundle_wall_seconds": 600.0,
            "bundle_disk_bytes": 1_073_741_824,
        },
    }


@pytest.fixture
def copied():
    return copy.deepcopy
