from __future__ import annotations

from dataclasses import dataclass

import pytest

from scenarioforge.runtime.adapter import AdapterRegistry, AdapterRegistryError
from scenarioforge.runtime.contracts import (
    Action,
    AdapterDescriptor,
    AdapterStep,
    Observation,
    Reward,
    Termination,
    TrajectorySample,
)


@dataclass
class _BackendObject:
    value: str


class _RegisteredAdapter:
    descriptor = AdapterDescriptor(
        schema_version="scenarioforge.adapter-descriptor/v1",
        adapter_id="scenarioforge.smarts",
        adapter_version="2.0.1",
        adapter_digest="a" * 64,
    )


def test_backend_neutral_step_contract_has_complete_stable_json_shape() -> None:
    observation = Observation(
        schema_version="scenarioforge.observation/v1",
        agent_id="ego",
        role="ego",
        tick=7,
        values={"lane_id": "edge-1_0", "speed_mps": 8.5},
    )
    action = Action(
        schema_version="scenarioforge.action/v1",
        agent_id="ego",
        tick=7,
        values={"acceleration_mps2": -2.0, "steering": 0.0},
    )
    reward = Reward(
        schema_version="scenarioforge.reward/v1",
        agent_id="ego",
        tick=7,
        value=-0.25,
        components={"progress": 0.75, "collision": -1.0},
    )
    termination = Termination(
        schema_version="scenarioforge.termination/v1",
        agent_id="ego",
        tick=7,
        terminated=False,
        truncated=False,
        reason="running",
    )
    sample = TrajectorySample(
        schema_version="scenarioforge.trajectory-sample/v1",
        agent_id="ego",
        role="ego",
        tick=7,
        position_m=(1.0, 2.0, 0.0),
        heading_deg=90.0,
        speed_mps=8.5,
        values={"lane_id": "edge-1_0"},
    )
    step = AdapterStep(
        schema_version="scenarioforge.adapter-step/v1",
        tick=7,
        observations=(observation,),
        actions=(action,),
        rewards=(reward,),
        terminations=(termination,),
        trajectory=(sample,),
    )

    assert step.to_dict() == {
        "schema_version": "scenarioforge.adapter-step/v1",
        "tick": 7,
        "observations": [
            {
                "schema_version": "scenarioforge.observation/v1",
                "agent_id": "ego",
                "role": "ego",
                "tick": 7,
                "values": {"lane_id": "edge-1_0", "speed_mps": 8.5},
            }
        ],
        "actions": [
            {
                "schema_version": "scenarioforge.action/v1",
                "agent_id": "ego",
                "tick": 7,
                "values": {"acceleration_mps2": -2.0, "steering": 0.0},
            }
        ],
        "rewards": [
            {
                "schema_version": "scenarioforge.reward/v1",
                "agent_id": "ego",
                "tick": 7,
                "value": -0.25,
                "components": {"collision": -1.0, "progress": 0.75},
            }
        ],
        "terminations": [
            {
                "schema_version": "scenarioforge.termination/v1",
                "agent_id": "ego",
                "tick": 7,
                "terminated": False,
                "truncated": False,
                "reason": "running",
            }
        ],
        "trajectory": [
            {
                "schema_version": "scenarioforge.trajectory-sample/v1",
                "agent_id": "ego",
                "role": "ego",
                "tick": 7,
                "position_m": [1.0, 2.0, 0.0],
                "heading_deg": 90.0,
                "speed_mps": 8.5,
                "values": {"lane_id": "edge-1_0"},
            }
        ],
    }


def test_domain_contract_rejects_backend_native_values() -> None:
    with pytest.raises(TypeError, match="not a JSON value"):
        Observation(
            schema_version="scenarioforge.observation/v1",
            agent_id="ego",
            role="ego",
            tick=0,
            values={"backend": _BackendObject("native")},
        )


def test_adapter_registry_resolves_only_pre_registered_ids() -> None:
    registry = AdapterRegistry()
    descriptor = _RegisteredAdapter.descriptor
    registry.register(descriptor, _RegisteredAdapter)

    assert registry.descriptor("scenarioforge.smarts") == descriptor
    assert isinstance(registry.create("scenarioforge.smarts"), _RegisteredAdapter)
    assert registry.ids() == ("scenarioforge.smarts",)

    for rejected in (
        "scenarioforge.runtime.smarts_adapter:SmartsAdapter",
        "../../adapter.py",
        "file:///tmp/adapter.py",
        "smarts; rm -rf /",
    ):
        with pytest.raises(AdapterRegistryError, match="not registered|invalid"):
            registry.create(rejected)
