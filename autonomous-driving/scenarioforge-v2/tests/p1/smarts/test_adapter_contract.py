from __future__ import annotations

import ast
import math
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from scenarioforge.core import canonical_digest
from scenarioforge.runtime.contracts import Action
from scenarioforge.runtime.smarts_adapter import SmartsAdapter, SmartsAdapterError


@dataclass(frozen=True)
class _NativeCollision:
    collidee_id: str


def _events(*, collision: str | None = None, goal: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        collisions=() if collision is None else (_NativeCollision(collision),),
        off_road=False,
        off_route=False,
        on_shoulder=False,
        wrong_way=False,
        not_moving=False,
        reached_goal=goal,
        reached_max_episode_steps=False,
        agents_alive_done=False,
        interest_done=False,
    )


def _vehicle(
    vehicle_id: str,
    *,
    x: float,
    y: float,
    speed: float,
    lane_id: str,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=vehicle_id,
        position=(x, y, 0.0),
        heading=math.pi / 2,
        speed=speed,
        steering=0.05,
        yaw_rate=0.01,
        road_id="eastbound",
        lane_id=lane_id,
        lane_index=0,
        linear_acceleration=(0.1, 0.0, 0.0),
    )


def _native_observation(
    agent_id: str,
    *,
    x: float,
    speed: float,
    collision: str | None = None,
    goal: bool = False,
) -> SimpleNamespace:
    social = _vehicle("traffic-1", x=x + 8.0, y=-1.75, speed=7.0, lane_id="eastbound_0")
    return SimpleNamespace(
        dt=0.1,
        step_count=int(x),
        steps_completed=int(x),
        elapsed_sim_time=x / 10,
        events=_events(collision=collision, goal=goal),
        ego_vehicle_state=_vehicle(
            agent_id,
            x=x,
            y=1.75,
            speed=speed,
            lane_id="eastbound_1",
        ),
        under_this_agent_control=True,
        neighborhood_vehicle_states=(social,),
        distance_travelled=x,
        signals=(),
    )


class _FakeEnvironment:
    def __init__(self) -> None:
        self.closed = False
        self.received_actions: list[dict[str, tuple[float, float, float]]] = []

    def reset(self, *, seed: int) -> tuple[dict[str, Any], dict[str, Any]]:
        assert seed == 19
        return {
            "ego": _native_observation("ego", x=0.0, speed=8.0),
            "challenger": _native_observation("challenger", x=1.0, speed=9.0),
        }, {}

    def step(
        self,
        actions: dict[str, tuple[float, float, float]],
    ) -> tuple[dict[str, Any], dict[str, float], dict[str, bool], dict[str, bool], dict[str, Any]]:
        self.received_actions.append(actions)
        return (
            {
                "ego": _native_observation("ego", x=2.0, speed=7.5),
                "challenger": _native_observation(
                    "challenger", x=3.0, speed=8.5, collision="traffic-1"
                ),
            },
            {"ego": 0.75, "challenger": -1.25},
            {"ego": False, "challenger": True},
            {"ego": False, "challenger": False},
            {},
        )

    def close(self) -> None:
        self.closed = True


def _snapshot() -> dict[str, Any]:
    return {
        "schema_version": "scenarioforge.smarts-execution/v1",
        "seed": 19,
        "scenario_asset_id": "p1-smarts-corridor-v1",
        "fixed_timestep_s": 0.1,
        "max_episode_steps": 80,
        "participants": [
            {"id": "ego", "role": "ego", "controllable": True},
            {"id": "challenger", "role": "controlled", "controllable": True},
            {"id": "traffic-1", "role": "social_vehicle", "controllable": False},
        ],
    }


def _action(agent_id: str, throttle_brake: float, steering: float) -> Action:
    return Action(
        schema_version="scenarioforge.action/v1",
        agent_id=agent_id,
        tick=1,
        values={"throttle_brake": throttle_brake, "steering": steering},
    )


def test_module_has_no_eager_smarts_import_and_descriptor_is_content_bound() -> None:
    source_path = Path("src/scenarioforge/runtime/smarts_adapter.py")
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported_roots = {
        alias.name.split(".", 1)[0]
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert "smarts" not in imported_roots

    descriptor = SmartsAdapter.descriptor
    assert descriptor.to_dict() == {
        "schema_version": "scenarioforge.adapter-descriptor/v1",
        "adapter_id": "scenarioforge.smarts",
        "adapter_version": "2.0.1",
        "adapter_digest": canonical_digest(
            {"id": "scenarioforge.smarts", "version": "2.0.1"}
        ),
    }


def test_lifecycle_projects_multi_agent_and_social_vehicle_state_only_as_dtos() -> None:
    environment = _FakeEnvironment()
    adapter = SmartsAdapter(environment_factory=lambda _: environment)

    initial = adapter.start(_snapshot())
    assert [item.agent_id for item in initial] == ["ego", "challenger", "traffic-1"]
    assert [item.role for item in initial] == ["ego", "controlled", "social_vehicle"]
    assert initial[0].to_dict() == {
        "schema_version": "scenarioforge.observation/v1",
        "agent_id": "ego",
        "role": "ego",
        "tick": 0,
        "values": {
            "collision_ids": [],
            "distance_travelled_m": 0.0,
            "elapsed_sim_time_s": 0.0,
            "events": {
                "agents_alive_done": False,
                "interest_done": False,
                "not_moving": False,
                "off_road": False,
                "off_route": False,
                "on_shoulder": False,
                "reached_goal": False,
                "reached_max_episode_steps": False,
                "wrong_way": False,
            },
            "heading_deg": -180.0,
            "lane_id": "eastbound_1",
            "lane_index": 0,
            "position_m": [0.0, 1.75, 0.0],
            "road_id": "eastbound",
            "speed_mps": 8.0,
            "steering_rad": 0.05,
            "under_agent_control": True,
            "yaw_rate_radps": 0.01,
        },
    }

    step = adapter.step((_action("ego", 0.4, 0.1), _action("challenger", -0.5, -0.2)))
    assert step.tick == 1
    assert [item.agent_id for item in step.observations] == [
        "ego",
        "challenger",
        "traffic-1",
    ]
    assert [item.to_dict() for item in step.rewards] == [
        {
            "schema_version": "scenarioforge.reward/v1",
            "agent_id": "ego",
            "tick": 1,
            "value": 0.75,
            "components": {"smarts_reward": 0.75},
        },
        {
            "schema_version": "scenarioforge.reward/v1",
            "agent_id": "challenger",
            "tick": 1,
            "value": -1.25,
            "components": {"smarts_reward": -1.25},
        },
    ]
    assert [item.to_dict() for item in step.terminations] == [
        {
            "schema_version": "scenarioforge.termination/v1",
            "agent_id": "ego",
            "tick": 1,
            "terminated": False,
            "truncated": False,
            "reason": "running",
        },
        {
            "schema_version": "scenarioforge.termination/v1",
            "agent_id": "challenger",
            "tick": 1,
            "terminated": True,
            "truncated": False,
            "reason": "collision",
        },
    ]
    assert len(step.trajectory) == 3
    assert environment.received_actions == [
        {"ego": (0.4, 0.0, 0.1), "challenger": (0.0, 0.5, -0.2)}
    ]
    assert "_Native" not in repr(step.to_dict())

    adapter.close()
    adapter.close()
    assert environment.closed is True


def test_lifecycle_and_action_set_fail_closed() -> None:
    adapter = SmartsAdapter(environment_factory=lambda _: _FakeEnvironment())
    with pytest.raises(SmartsAdapterError, match="not started"):
        adapter.step((_action("ego", 0.0, 0.0),))

    adapter.start(_snapshot())
    with pytest.raises(SmartsAdapterError, match="already started"):
        adapter.start(_snapshot())
    with pytest.raises(SmartsAdapterError, match="exactly one action"):
        adapter.step((_action("ego", 0.0, 0.0),))
    with pytest.raises(SmartsAdapterError, match="tick 1"):
        adapter.step(
            (
                Action(
                    schema_version="scenarioforge.action/v1",
                    agent_id="ego",
                    tick=7,
                    values={"throttle_brake": 0.0, "steering": 0.0},
                ),
                _action("challenger", 0.0, 0.0),
            )
        )


def test_start_rejects_dynamic_paths_and_incomplete_participant_bindings() -> None:
    adapter = SmartsAdapter(environment_factory=lambda _: _FakeEnvironment())
    candidate = _snapshot()
    candidate["scenario_path"] = "/tmp/operator-controlled"
    with pytest.raises(SmartsAdapterError, match="unsupported execution field"):
        adapter.start(candidate)

    candidate = _snapshot()
    candidate["participants"] = [candidate["participants"][0]]
    with pytest.raises(SmartsAdapterError, match="controllable agents"):
        adapter.start(candidate)
