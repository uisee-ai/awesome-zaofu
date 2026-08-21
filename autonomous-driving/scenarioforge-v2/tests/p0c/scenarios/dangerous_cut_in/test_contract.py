from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from scenarioforge.core import (
    CompilationStatus,
    ScenarioCompiler,
    canonical_bytes,
    instantiate_scenario,
    load_scenario,
)
from scenarioforge.runtime.policy import resolve_tick_actions


ROOT = Path(__file__).resolve().parents[4]
SCENARIO = ROOT / "examples" / "p0c" / "dangerous_cut_in.json"
PROTOTYPE = ROOT / "tests" / "fixtures" / "p0c" / "contracts" / "prototype_v2.json"
CALIBRATION = (
    ROOT
    / "tests"
    / "fixtures"
    / "p0c"
    / "calibration"
    / "frozen-contracts.json"
)
EXPECTED_DIGEST = "c68e393488498d4eb4e64afb5900dbd9a204ec2df7b44d974ce4299237146afd"


def _deep_update(target: dict[str, Any], patch: dict[str, Any]) -> None:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_update(target[key], value)
        else:
            target[key] = copy.deepcopy(value)


def _expected_contract() -> tuple[dict[str, Any], dict[str, Any]]:
    expected = json.loads(PROTOTYPE.read_text(encoding="utf-8"))
    calibration = json.loads(CALIBRATION.read_text(encoding="utf-8"))
    preset = next(
        item
        for item in calibration["presets"]
        if item["preset_id"] == "dangerous_cut_in"
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
    return expected, preset


def test_example_is_the_complete_frozen_dangerous_cut_in_contract() -> None:
    observed = json.loads(SCENARIO.read_text(encoding="utf-8"))
    expected, preset = _expected_contract()

    assert {
        "preset_id": preset["preset_id"],
        "candidate_id": preset["candidate_id"],
        "candidate_count": preset["candidate_count"],
        "fixture_digest": preset["fixture_digest"],
    } == {
        "preset_id": "dangerous_cut_in",
        "candidate_id": "dangerous-cut-in-c2",
        "candidate_count": 2,
        "fixture_digest": EXPECTED_DIGEST,
    }
    assert observed == expected
    assert hashlib.sha256(canonical_bytes(observed)).hexdigest() == EXPECTED_DIGEST


def test_contract_compiles_exactly_with_complete_evidence_and_tick_contracts() -> None:
    source = json.loads(SCENARIO.read_text(encoding="utf-8"))
    scenario = instantiate_scenario(load_scenario(SCENARIO))
    bundle = ScenarioCompiler().compile(scenario)

    assert bundle.report.overall_status is CompilationStatus.EXACT
    assert bundle.report.diagnostics == ()
    assert bundle.execution_plan is not None
    plan = bundle.execution_plan.to_dict()
    assert plan["simulation"]["topology"] == source["road"]
    assert plan["participants"] == source["participants"]
    assert plan["events"] == source["events"]
    assert plan["constraints"] == source["constraints"]
    assert plan["policy"] == source["policy"]
    assert plan["tick_contract"] == {
        "schema_version": "scenarioforge.tick-contract/v2",
        "state_indexing": "S_N_at_tick_start",
        "trigger_evaluation": "S_N_and_tick_N",
        "action_application": "S_N_to_S_N_plus_1",
        "event_effect_offset": 1,
        "priority_order": ["scenario_override", "policy"],
        "participant_order": ["ego", "cutter"],
        "same_tick_events": "preserve_sequence_order",
    }
    assert plan["artifact_contract"] == {
        "schema_version": "scenarioforge.artifact-contract/v2",
        "required": [
            "actions.json",
            "events.json",
            "metrics.json",
            "trajectory.json",
            "worker_result.json",
        ],
        "fully_verified_required": True,
        "max_file_bytes": 10_485_760,
    }


def test_frozen_cut_in_overrides_replace_only_cutter_actions() -> None:
    scenario = instantiate_scenario(load_scenario(SCENARIO))
    plan_model = ScenarioCompiler().compile(scenario).execution_plan
    assert plan_model is not None
    plan = plan_model.to_dict()

    before, before_records, before_events = resolve_tick_actions(plan, 4)
    cut_in, cut_in_records, cut_in_events = resolve_tick_actions(plan, 5)
    final_cut_in, final_records, final_events = resolve_tick_actions(plan, 11)

    assert before == {"ego": [0.0, 0.2], "cutter": [-0.1, -0.5]}
    assert [item["source"] for item in before_records] == ["policy", "policy"]
    assert before_events == []
    assert cut_in == {"ego": [0.0, 0.2], "cutter": [-1.0, 0.0]}
    assert [item["source"] for item in cut_in_records] == [
        "policy",
        "scenario_override",
    ]
    assert cut_in_events == [
        {
            "schema_version": "scenarioforge.event/v2",
            "event_id": "dangerous-cut-in-started",
            "sequence": 0,
            "type": "trigger_fired",
            "participant_id": "cutter",
            "trigger_tick": 5,
            "effect_state_tick": 6,
            "priority_contract": "scenarioforge.trigger-priority/v2",
            "action": {"steering": -1.0, "throttle_brake": 0.0},
        }
    ]
    assert final_cut_in == {"ego": [0.0, 0.2], "cutter": [-1.0, 0.0]}
    assert [item["source"] for item in final_records] == [
        "policy",
        "scenario_override",
    ]
    assert final_events == [
        {
            "schema_version": "scenarioforge.event/v2",
            "event_id": "dangerous-cut-in-control-7",
            "sequence": 6,
            "type": "trigger_fired",
            "participant_id": "cutter",
            "trigger_tick": 11,
            "effect_state_tick": 12,
            "priority_contract": "scenarioforge.trigger-priority/v2",
            "action": {"steering": -1.0, "throttle_brake": 0.0},
        }
    ]
