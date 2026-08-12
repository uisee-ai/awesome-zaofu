from __future__ import annotations

import json
from copy import deepcopy

from scenarioforge.compiler import compile_scenario
from scenarioforge.runtime.worker import _activate_runtime_plan, _advance_runtime_plan
from scenarioforge.spec import RunRequest, canonical_scenario, load_scenario


def test_lead_event_and_obstacle_have_executable_runtime_plan(
    scenario_payload: dict[str, object], run_request_payload: dict[str, object]
) -> None:
    payload = deepcopy(scenario_payload)
    payload["actors"] = [
        {"id": "ego", "role": "ego", "behavior": "follow_lead"},
        {
            "id": "lead", "role": "traffic",
            "initial_state": {"lane": 0, "longitudinal": 24.0, "speed": 12.0},
        },
    ]
    payload["event_triggers"] = [
        {
            "id": "brake",
            "kind": "at_time",
            "seconds": 2.0,
            "action": "yield",
            "target_actor_id": "lead",
        }
    ]
    payload["static_obstacles"] = [
        {"id": "barrier", "kind": "barrier", "lane": 1, "longitudinal": 35.0, "length": 2.0}
    ]
    scenario = load_scenario(json.dumps(payload), "application/json")
    request_payload = deepcopy(run_request_payload)
    request_payload["scenario_digest"] = canonical_scenario(scenario).digest

    compiled = compile_scenario(scenario, RunRequest.model_validate(request_payload))

    assert compiled.cases[0].runtime_plan == {
        "schema_version": "scenarioforge.runtime-plan.v1",
        "actors": [actor.model_dump(mode="json") for actor in scenario.actors],
        "event_triggers": [trigger.model_dump(mode="json") for trigger in scenario.event_triggers],
        "static_obstacles": [obstacle.model_dump(mode="json") for obstacle in scenario.static_obstacles],
        "safety": None,
    }


class _FakeRuntime:
    def __init__(self) -> None:
        self.spawned_actors: list[str] = []
        self.spawned_obstacles: list[str] = []
        self.stopped_actors: list[str] = []

    def spawn_actor(self, actor: dict[str, object]) -> None:
        self.spawned_actors.append(str(actor["id"]))

    def spawn_obstacle(self, obstacle: dict[str, object]) -> None:
        self.spawned_obstacles.append(str(obstacle["id"]))

    def stop_actor(self, actor_id: str) -> None:
        self.stopped_actors.append(actor_id)


def test_runtime_worker_consumes_lead_obstacle_and_brake_trigger(
    scenario_payload: dict[str, object], run_request_payload: dict[str, object]
) -> None:
    payload = deepcopy(scenario_payload)
    payload["actors"] = [
        {"id": "ego", "role": "ego", "behavior": "follow_lead"},
        {
            "id": "lead",
            "role": "traffic",
            "initial_state": {"lane": 0, "longitudinal": 24.0, "speed": 12.0},
        },
    ]
    payload["event_triggers"] = [
        {
            "id": "brake",
            "kind": "at_time",
            "seconds": 2.0,
            "action": "yield",
            "target_actor_id": "lead",
        }
    ]
    payload["static_obstacles"] = [
        {"id": "barrier", "kind": "barrier", "lane": 1, "longitudinal": 35.0, "length": 2.0}
    ]
    scenario = load_scenario(json.dumps(payload), "application/json")
    request_payload = deepcopy(run_request_payload)
    request_payload["scenario_digest"] = canonical_scenario(scenario).digest
    runtime_plan = compile_scenario(scenario, RunRequest.model_validate(request_payload)).cases[0].runtime_plan
    runtime = _FakeRuntime()

    state = _activate_runtime_plan(runtime, runtime_plan)
    receipts = _advance_runtime_plan(runtime, state, simulated_seconds=2.0)

    assert runtime.spawned_actors == ["ego", "lead"]
    assert runtime.spawned_obstacles == ["barrier"]
    assert runtime.stopped_actors == ["lead"]
    assert receipts == [
        {
            "trigger_id": "brake",
            "target_actor_id": "lead",
            "action": "yield",
            "status": "triggered",
            "result": "stopped",
        }
    ]
