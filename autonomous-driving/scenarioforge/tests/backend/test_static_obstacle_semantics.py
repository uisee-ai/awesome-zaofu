from __future__ import annotations

import json
from copy import deepcopy

from scenarioforge.compiler import compile_scenario
from scenarioforge.spec import RunRequest, canonical_scenario, load_scenario


def test_static_obstacle_is_present_in_the_runtime_plan(
    scenario_payload: dict[str, object], run_request_payload: dict[str, object]
) -> None:
    payload = deepcopy(scenario_payload)
    payload["static_obstacles"] = [
        {"id": "barrier", "kind": "barrier", "lane": 1, "longitudinal": 30.0, "length": 2.0}
    ]
    scenario = load_scenario(json.dumps(payload), "application/json")
    request_payload = deepcopy(run_request_payload)
    request_payload["scenario_digest"] = canonical_scenario(scenario).digest

    compiled = compile_scenario(scenario, RunRequest.model_validate(request_payload))

    assert compiled.cases[0].runtime_plan["static_obstacles"] == [
        {"id": "barrier", "kind": "barrier", "lane": 1, "longitudinal": 30.0, "length": 2.0}
    ]
