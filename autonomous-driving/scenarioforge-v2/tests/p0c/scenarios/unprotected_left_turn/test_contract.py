from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from scenarioforge.core import (
    ScenarioCompiler,
    canonical_bytes,
    instantiate_scenario,
    load_scenario,
)


ROOT = Path(__file__).resolve().parents[4]
SCENARIO = ROOT / "examples" / "p0c" / "unprotected_left_turn.json"
PROTOTYPE = ROOT / "tests" / "fixtures" / "p0c" / "contracts" / "prototype_v2.json"
FROZEN = (
    ROOT
    / "tests"
    / "fixtures"
    / "p0c"
    / "calibration"
    / "frozen-contracts.json"
)
FIXTURE_DIGEST = "a59adabbfe77306eab858dd38c83e774435e268c15e8f5c779d8c569bc3d0841"


def _deep_update(target: dict[str, Any], patch: dict[str, Any]) -> None:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_update(target[key], value)
        else:
            target[key] = copy.deepcopy(value)


def _frozen_scenario() -> tuple[dict[str, Any], dict[str, Any]]:
    frozen = json.loads(FROZEN.read_text(encoding="utf-8"))
    prototype = json.loads(PROTOTYPE.read_text(encoding="utf-8"))
    preset = next(
        item
        for item in frozen["presets"]
        if item["preset_id"] == "unprotected_left_turn"
    )
    _deep_update(prototype, preset["scenario_patch"])
    participant_ids = [item["id"] for item in prototype["participants"]]
    topology_kind = prototype["road"]["topology_kind"]
    for definition in prototype["constraints"]["metric_definitions"]:
        scope = preset["metric_contract"][definition["metric"]]
        definition["applies_to"]["participant_ids"] = (
            participant_ids
            if scope["participant_ids"] == "all"
            else scope["participant_ids"]
        )
        definition["applies_to"]["topology_kinds"] = [topology_kind]
        definition["threshold"] = scope["threshold"]
    return prototype, preset


def test_example_is_the_exact_frozen_left_turn_candidate() -> None:
    scenario = json.loads(SCENARIO.read_text(encoding="utf-8"))
    frozen_scenario, preset = _frozen_scenario()

    assert scenario == frozen_scenario
    assert hashlib.sha256(canonical_bytes(scenario)).hexdigest() == FIXTURE_DIGEST
    assert preset["fixture_digest"] == FIXTURE_DIGEST


def test_contract_encodes_the_unprotected_left_turn_near_miss() -> None:
    scenario = json.loads(SCENARIO.read_text(encoding="utf-8"))

    assert scenario["schema_version"] == "scenarioforge.scenario/v2"
    assert scenario["scenario_id"] == "unprotected_left_turn"
    assert scenario["road"]["topology_kind"] == "intersection"
    assert scenario["road"]["conflict_zones"] == [
        {
            "id": "left-turn-conflict",
            "lane_ids": ["ego-left-turn", "oncoming-through"],
            "start_m": 0.0,
            "end_m": 20.0,
        }
    ]
    assert {
        participant["id"]: participant["route"]["lane_ids"]
        for participant in scenario["participants"]
    } == {
        "ego": ["ego-inbound", "ego-left-turn", "ego-exit"],
        "oncoming": [
            "oncoming-inbound",
            "oncoming-through",
            "oncoming-exit",
        ],
    }
    assert [event["id"] for event in scenario["events"]] == [
        "yield-started",
        "left-turn-committed",
    ]
    assert [event["sequence"] for event in scenario["events"]] == [0, 1]
    assert scenario["events"][0]["trigger"]["tick"] == 20
    assert scenario["events"][0]["duration_ticks"] == 19
    assert scenario["events"][1]["trigger"]["tick"] == 39
    assert scenario["constraints"]["max_steps"] == 180
    assert scenario["constraints"]["duration_s"] == 18.0
    assert scenario["constraints"]["expected_events"] == [
        "yield-started",
        "left-turn-committed",
    ]
    assert scenario["constraints"]["target_outcome"] == "near_miss"
    assert scenario["constraints"]["success_predicates"] == [
        {
            "id": "yield-completed",
            "kind": "yield_completed",
            "participant_ids": ["ego"],
            "lane_ids": ["ego-exit"],
        }
    ]
    assert {
        predicate["kind"]
        for predicate in scenario["constraints"]["failure_predicates"]
    } == {"collision", "boundary_violation", "wrong_lane", "timeout"}
    assert scenario["policy"]["id"] == "scenarioforge.deterministic-control"
    assert scenario["policy"]["version"] == "2.0.0"


def test_example_compiles_to_an_executable_metadrive_plan() -> None:
    instance = instantiate_scenario(load_scenario(SCENARIO))
    bundle = ScenarioCompiler().compile(instance)

    assert bundle.report.executable is True, bundle.report.to_dict()
    assert bundle.execution_plan is not None
    plan = bundle.execution_plan.to_dict()
    assert plan["backend"] == {
        "id": "metadrive",
        "version": "0.4.3",
        "adapter": {
            "id": "scenarioforge.metadrive",
            "version": "2.0.0",
        },
    }
    assert plan["simulation"]["headless"] is True
    assert plan["constraints"]["target_outcome"] == "near_miss"
