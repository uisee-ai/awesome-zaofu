from __future__ import annotations

import json
from pathlib import Path

from scenarioforge.bundle import load_bundle_json
from scenarioforge.compiler import compile_scenario
from scenarioforge.runtime import run_bundle
from scenarioforge.spec import RunRequest, canonical_scenario, load_scenario


def test_sealed_bundle_captures_canonical_actor_and_versioned_safety_evidence(
    tmp_path: Path,
    scenario_payload: dict[str, object],
    run_request_payload: dict[str, object],
) -> None:
    scenario_payload["actors"] = [
        {
            "id": "ego",
            "role": "ego",
            "initial_state": {"lane": 0, "longitudinal": 0.0, "speed": 10.0},
        },
        {
            "id": "lead",
            "role": "traffic",
            "initial_state": {"lane": 0, "longitudinal": 10.0, "speed": 0.0},
        },
    ]
    scenario_payload["event_triggers"] = [
        {
            "id": "brake",
            "kind": "at_time",
            "seconds": 0.0,
            "action": "yield",
            "target_actor_id": "lead",
        }
    ]
    scenario_payload["safety"] = {
        "max_speed": 20.0,
        "minimum_headway": 2.0,
        "collision_free": True,
    }
    scenario = load_scenario(json.dumps(scenario_payload), "application/json")
    request_data = {**run_request_payload, "limits": {**run_request_payload["limits"]}}
    request_data["scenario_digest"] = canonical_scenario(scenario).digest
    request_data["seeds"] = [17]
    compiled = compile_scenario(scenario, RunRequest.model_validate(request_data))

    outcome = run_bundle(compiled, tmp_path, run_id="safety-evidence", fault_plan={0: "success"})

    trace = load_bundle_json(outcome.bundle_path, "traces/case-000.json")
    first_tick = trace[0]
    assert {actor["actor_id"] for actor in first_tick["actors"]} == {"ego", "lead"}
    assert all(
        {"actor_id", "position", "speed_mps", "heading", "state"} <= actor.keys()
        for actor in first_tick["actors"]
    )
    assert first_tick["event_receipts"] == [
        {
            "trigger_id": "brake",
            "target_actor_id": "lead",
            "action": "yield",
            "status": "not_triggered",
            "result": "not_triggered",
        }
    ]

    safety = load_bundle_json(outcome.bundle_path, "safety_evidence.json")
    assert safety["schema_version"] == "scenarioforge.safety-evidence.v1"
    assert safety["metric_definitions"]["minimum_ttc_seconds"] == {
        "formula_version": "v1",
        "formula": "min(longitudinal_gap_m / positive_closing_speed_mps)",
        "unit": "s",
        "missing_value": None,
    }
    case = safety["cases"][0]
    assert case["metrics"] == {
        "minimum_ttc_seconds": 1.0,
        "minimum_headway_seconds": 1.0,
        "event_to_response_latency_seconds": None,
        "collision": False,
        "off_road": False,
        "route_progress": 0.25,
    }
    assert case["safety_constraints"] == scenario_payload["safety"]
    assert case["safety_verdict"] == "fail"
    assert case["violations"] == ["minimum_headway"]
