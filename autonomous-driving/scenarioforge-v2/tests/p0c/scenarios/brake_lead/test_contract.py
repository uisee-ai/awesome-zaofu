from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from scenarioforge.core import (
    CompilationStatus,
    ScenarioCompiler,
    instantiate_scenario,
    load_scenario,
)
from scenarioforge.runtime.policy import resolve_tick_actions


ROOT = Path(__file__).resolve().parents[4]
SCENARIO = ROOT / "examples" / "p0c" / "brake_lead.json"
PROTOTYPE = ROOT / "tests" / "fixtures" / "p0c" / "contracts" / "prototype_v2.json"
CALIBRATION = (
    ROOT / "tests" / "fixtures" / "p0c" / "calibration" / "frozen-contracts.json"
)
HISTORICAL_V1 = ROOT / "examples" / "p0a" / "brake_lead.json"
EXPECTED_DIGEST = "776f0ae0d9d43bbda156811bdc55b26538fb7d1527db3fc2790ac6d0229f195a"


def _deep_update(target: dict[str, Any], patch: dict[str, Any]) -> None:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_update(target[key], value)
        else:
            target[key] = copy.deepcopy(value)


def _expected_contract() -> dict[str, Any]:
    expected = json.loads(PROTOTYPE.read_text(encoding="utf-8"))
    calibration = json.loads(CALIBRATION.read_text(encoding="utf-8"))
    preset = next(
        item for item in calibration["presets"] if item["preset_id"] == "brake_lead"
    )
    _deep_update(expected, preset["scenario_patch"])

    participant_ids = [item["id"] for item in expected["participants"]]
    topology_kind = expected["road"]["topology_kind"]
    for definition in expected["constraints"]["metric_definitions"]:
        scope = preset["metric_contract"][definition["metric"]]
        definition["applies_to"]["participant_ids"] = (
            participant_ids
            if scope["participant_ids"] == "all"
            else scope["participant_ids"]
        )
        definition["applies_to"]["topology_kinds"] = [topology_kind]
        definition["threshold"] = scope["threshold"]
    return expected


def _compiled_plan() -> dict[str, Any]:
    bundle = ScenarioCompiler().compile(instantiate_scenario(load_scenario(SCENARIO)))
    assert bundle.report.overall_status is CompilationStatus.EXACT
    assert bundle.report.diagnostics == ()
    assert bundle.execution_plan is not None
    return bundle.execution_plan.to_dict()


def test_example_is_the_exact_frozen_brake_lead_contract() -> None:
    source = json.loads(SCENARIO.read_text(encoding="utf-8"))

    assert source == _expected_contract()
    assert load_scenario(SCENARIO).canonical_digest == EXPECTED_DIGEST


def test_contract_binds_lead_brake_and_ego_avoidance_at_frozen_ticks() -> None:
    plan = _compiled_plan()

    assert [item["id"] for item in plan["participants"]] == ["ego", "lead"]
    assert [item["spawn"]["speed_mps"] for item in plan["participants"]] == [
        22.0,
        22.0,
    ]
    assert [item["spawn"]["longitudinal_m"] for item in plan["participants"]] == [
        10.0,
        38.0,
    ]
    assert [item["route"]["lane_ids"] for item in plan["participants"]] == [
        ["following-lane"],
        ["following-lane"],
    ]
    assert plan["constraints"]["target_outcome"] == "near_miss"
    assert plan["constraints"]["expected_events"] == [
        "lead-hard-brake",
        "ego-avoidance-brake",
    ]
    assert [item["duration_ticks"] for item in plan["events"]] == [6, 6]

    lead_actions, lead_records, lead_events = resolve_tick_actions(plan, 35)
    ego_actions, ego_records, ego_events = resolve_tick_actions(plan, 40)
    assert lead_actions == {"ego": [0.0, 0.0], "lead": [0.0, -1.0]}
    assert ego_actions == {"ego": [0.0, -0.7], "lead": [0.0, -1.0]}
    assert [item["source"] for item in lead_records] == [
        "policy",
        "scenario_override",
    ]
    assert [item["source"] for item in ego_records] == [
        "scenario_override",
        "scenario_override",
    ]
    assert [(item["event_id"], item["trigger_tick"], item["effect_state_tick"])
            for item in lead_events + ego_events] == [
        ("lead-hard-brake", 35, 36),
        ("ego-avoidance-brake", 40, 41),
    ]
    assert resolve_tick_actions(plan, 39)[0]["lead"] == [0.0, -1.0]
    assert resolve_tick_actions(plan, 45)[0]["ego"] == [0.0, -0.7]
    assert resolve_tick_actions(plan, 46)[0] == {
        "ego": [0.0, 0.0],
        "lead": [0.0, 0.0],
    }
    metric_definitions = {
        item["metric"]: item for item in plan["constraints"]["metric_definitions"]
    }
    assert metric_definitions["hard_braking"]["threshold"] == {
        "operator": "lte",
        "value": -1.0,
    }
    assert metric_definitions["minimum_ttc"]["threshold"] == {
        "operator": "lte",
        "value": 4.0,
    }


def test_historical_v1_brake_fixture_remains_byte_stable() -> None:
    assert hashlib.sha256(HISTORICAL_V1.read_bytes()).hexdigest() == (
        "7ae9e59862227c9423efa6f499d40406e22177f4978a4eaa5c7947577988b961"
    )
    assert load_scenario(HISTORICAL_V1).canonical_digest == (
        "628e8a458de35889fc1fe80e93aa69abd9a43ae25db438cbb56eb5efa4170498"
    )
