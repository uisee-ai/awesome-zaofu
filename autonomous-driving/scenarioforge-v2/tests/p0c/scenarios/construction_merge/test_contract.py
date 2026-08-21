from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from scenarioforge.core import (
    CompilationStatus,
    ScenarioCompiler,
    instantiate_scenario,
    load_scenario,
)
from scenarioforge.runtime.adapter import MetaDriveAdapter


ROOT = Path(__file__).resolve().parents[4]
SCENARIO = ROOT / "examples" / "p0c" / "construction_merge.json"
PROTOTYPE = ROOT / "tests" / "fixtures" / "p0c" / "contracts" / "prototype_v2.json"
CALIBRATION = (
    ROOT / "tests" / "fixtures" / "p0c" / "calibration" / "frozen-contracts.json"
)
EXPECTED_DIGEST = "1d273fd601a77dc6b6af2281d45f9a25955781181b8cf1405464bc05fc06623a"


def _deep_update(target: dict[str, Any], patch: dict[str, Any]) -> None:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_update(target[key], value)
        else:
            target[key] = copy.deepcopy(value)


def _expected_contract() -> dict[str, Any]:
    prototype = json.loads(PROTOTYPE.read_text(encoding="utf-8"))
    calibration = json.loads(CALIBRATION.read_text(encoding="utf-8"))
    preset = next(
        item
        for item in calibration["presets"]
        if item["preset_id"] == "construction_merge"
    )
    expected = copy.deepcopy(prototype)
    _deep_update(expected, preset["scenario_patch"])

    participant_ids = [item["id"] for item in expected["participants"]]
    for definition in expected["constraints"]["metric_definitions"]:
        scope = preset["metric_contract"][definition["metric"]]
        definition["applies_to"]["participant_ids"] = (
            participant_ids
            if scope["participant_ids"] == "all"
            else scope["participant_ids"]
        )
        definition["applies_to"]["topology_kinds"] = ["lane_closure"]
        definition["threshold"] = scope["threshold"]

    closing_lane = expected["road"]["lanes"][0]
    closing_lane["successor_lane_ids"] = ["open-lane", "closed-region"]
    expected["road"]["lanes"].append(
        {
            "id": "closed-region",
            "road_id": "construction-corridor",
            "engine_lane_index": {
                "start_node": ">>>",
                "end_node": "1S0_0_",
                "lane_index": 0,
            },
            "kind": "closed",
            "length_m": 65.695,
            "predecessor_lane_ids": ["closing-lane"],
            "successor_lane_ids": [],
        }
    )
    expected["constraints"]["failure_predicates"].insert(
        2,
        {
            "id": "closed-region-entered",
            "kind": "closed_region_entry",
            "participant_ids": ["ego"],
            "lane_ids": ["closed-region"],
        },
    )
    expected["participants"][0]["route"]["goal"]["longitudinal_m"] = 110.0
    return expected


def test_example_is_the_exact_calibrated_construction_contract() -> None:
    source = json.loads(SCENARIO.read_text(encoding="utf-8"))

    assert source == _expected_contract()
    assert load_scenario(SCENARIO).canonical_digest == EXPECTED_DIGEST


def test_contract_compiles_exact_and_binds_every_terminal_condition() -> None:
    bundle = ScenarioCompiler().compile(instantiate_scenario(load_scenario(SCENARIO)))

    assert bundle.report.overall_status is CompilationStatus.EXACT
    assert bundle.report.diagnostics == ()
    assert bundle.execution_plan is not None
    plan = bundle.execution_plan.to_dict()
    assert plan["simulation"]["topology"]["lanes"][-1] == {
        "id": "closed-region",
        "road_id": "construction-corridor",
        "engine_lane_index": {
            "start_node": ">>>",
            "end_node": "1S0_0_",
            "lane_index": 0,
        },
        "kind": "closed",
        "length_m": 65.695,
        "predecessor_lane_ids": ["closing-lane"],
        "successor_lane_ids": [],
    }
    assert plan["participants"][0]["spawn"]["lane_id"] == "closing-lane"
    assert plan["participants"][0]["route"]["lane_ids"] == [
        "closing-lane",
        "open-lane",
    ]
    assert plan["participants"][0]["route"]["goal"] == {
        "lane_id": "open-lane",
        "longitudinal_m": 110.0,
    }
    assert plan["constraints"]["target_outcome"] == "safe_pass"
    assert [item["kind"] for item in plan["constraints"]["success_predicates"]] == [
        "merge_completed"
    ]
    assert [item["kind"] for item in plan["constraints"]["failure_predicates"]] == [
        "collision",
        "boundary_violation",
        "closed_region_entry",
        "timeout",
    ]


@pytest.mark.parametrize(
    ("failure_id", "point_patch", "at_horizon"),
    [
        ("collision-observed", {"collision": True}, False),
        ("ego-boundary-violation", {"boundary_violation": True}, False),
        ("closed-region-entered", {"lane_id": "closed-region"}, False),
        ("merge-timeout", {}, True),
    ],
)
def test_each_declared_hazard_produces_a_failure_predicate(
    failure_id: str,
    point_patch: dict[str, object],
    at_horizon: bool,
) -> None:
    bundle = ScenarioCompiler().compile(instantiate_scenario(load_scenario(SCENARIO)))
    assert bundle.execution_plan is not None
    adapter = MetaDriveAdapter(bundle.execution_plan.to_dict())
    point: dict[str, object] = {
        "tick": 1,
        "participant_id": "ego",
        "lane_id": "closing-lane",
        "collision": False,
        "boundary_violation": False,
        "route_completed": False,
    }
    point.update(point_patch)

    results = adapter._predicate_results(
        [point],
        at_horizon=at_horizon,
        execution_complete=True,
    )

    satisfied = [item["predicate_id"] for item in results["failure"] if item["satisfied"]]
    assert satisfied == [failure_id]
