from __future__ import annotations

import importlib.metadata

import pytest

from scenarioforge.runtime.contracts import Action
from scenarioforge.runtime.smarts_adapter import SmartsAdapter
from scenarioforge.runtime.smarts_worker import (
    SmartsEnvironment,
    SmartsWorkerError,
    canonical_smarts_execution,
)


def test_real_smarts_lifecycle_crosses_the_adapter_only_as_versioned_dtos() -> None:
    execution = canonical_smarts_execution(
        "competitive_lane_change",
        max_episode_steps=4,
    )
    environment = SmartsEnvironment.from_execution_snapshot(execution)
    adapter = SmartsAdapter(environment_factory=lambda _: environment)

    initial = adapter.start(execution)
    controllable = [
        participant["id"]
        for participant in execution["participants"]
        if participant["controllable"]
    ]
    assert importlib.metadata.version("smarts") == "2.0.1"
    assert environment.engine_info == {
        "distribution": "smarts",
        "version": "2.0.1",
        "engine_class": "SMARTS",
    }
    assert {item.agent_id for item in initial}.issuperset(controllable)
    assert {item.schema_version for item in initial} == {
        "scenarioforge.observation/v1"
    }
    assert all(type(item).__module__.startswith("scenarioforge.") for item in initial)

    step = adapter.step(
        tuple(
            Action(
                schema_version="scenarioforge.action/v1",
                agent_id=agent_id,
                tick=1,
                values={"throttle_brake": 0.0, "steering": 0.0},
            )
            for agent_id in controllable
        )
    )
    assert step.schema_version == "scenarioforge.adapter-step/v1"
    assert {item.schema_version for item in step.rewards} == {
        "scenarioforge.reward/v1"
    }
    assert {item.schema_version for item in step.terminations} == {
        "scenarioforge.termination/v1"
    }
    assert {item.schema_version for item in step.trajectory} == {
        "scenarioforge.trajectory-sample/v1"
    }
    assert "smarts.core" not in repr(step.to_dict())

    adapter.close()
    assert environment.closed is True


def test_real_worker_rejects_asset_participant_and_event_binding_drift() -> None:
    execution = canonical_smarts_execution("highway_merge", max_episode_steps=2)

    drifted = {**execution, "scenario_asset_digest": "0" * 64}
    with pytest.raises(SmartsWorkerError, match="asset digest mismatch"):
        SmartsEnvironment.from_execution_snapshot(drifted)

    drifted = {**execution, "participants": execution["participants"][:-1]}
    with pytest.raises(SmartsWorkerError, match="participant binding"):
        SmartsEnvironment.from_execution_snapshot(drifted)

    drifted = {**execution, "events": []}
    with pytest.raises(SmartsWorkerError, match="event binding"):
        SmartsEnvironment.from_execution_snapshot(drifted)
