from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from scenarioforge.core import (
    CompilationStatus,
    ScenarioCompiler,
    canonical_bytes,
    instantiate_scenario,
    load_scenario,
    strict_loads,
)
from scenarioforge.runtime import RunSupervisor
from scenarioforge.runtime.contracts import RunOutcome


ROOT = Path(__file__).resolve().parents[3]
COUNTERFACTUALS = (
    ROOT / "tests" / "fixtures" / "p0c" / "validation" / "counterfactuals.json"
)
INPUT_MEMBERS = [
    "assets.json",
    "compile_report.json",
    "execution_plan.json",
    "policy.json",
    "run_manifest.json",
    "run_request.json",
]


def _json(path: Path) -> Any:
    return strict_loads(path.read_bytes())


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _participant(source: dict[str, Any], participant_id: str) -> dict[str, Any]:
    return next(
        item for item in source["participants"] if item["id"] == participant_id
    )


def _apply_counterfactual(
    baseline: dict[str, Any],
    counterfactual: dict[str, Any],
) -> dict[str, Any]:
    variant = copy.deepcopy(baseline)
    mutation = counterfactual["mutation"]

    if mutation == "remove_lane_closure":
        variant["road"]["topology_kind"] = "straight"
        variant["road"]["lanes"] = [
            lane for lane in variant["road"]["lanes"] if lane["id"] != "closed-region"
        ]
        closing = next(
            lane for lane in variant["road"]["lanes"] if lane["id"] == "closing-lane"
        )
        closing["kind"] = "travel"
        closing["successor_lane_ids"] = ["open-lane"]
        variant["road"]["conflict_zones"] = []
        variant["constraints"]["failure_predicates"] = [
            predicate
            for predicate in variant["constraints"]["failure_predicates"]
            if predicate["kind"] != "closed_region_entry"
        ]
        for definition in variant["constraints"]["metric_definitions"]:
            definition["applies_to"]["topology_kinds"] = ["straight"]
        neutral = copy.deepcopy(variant["events"][0])
        neutral.update({"id": "closure-removed", "sequence": 0})
        neutral["trigger"]["tick"] = 0
        neutral["action"].update({"steering": 0.0, "throttle_brake": 0.2})
        variant["events"] = [neutral]
        variant["constraints"]["expected_events"] = ["closure-removed"]
    elif mutation == "spread_mainline_gap":
        _participant(variant, "ego")["spawn"]["longitudinal_m"] = 50.0
        _participant(variant, "front")["spawn"]["longitudinal_m"] = 150.0
    elif mutation == "cancel_lead_brake":
        remaining = copy.deepcopy(variant["events"][1])
        remaining["sequence"] = 0
        variant["events"] = [remaining]
        variant["constraints"]["expected_events"] = [remaining["id"]]
    elif mutation == "separate_cut_in_vehicle":
        _participant(variant, "cutter")["spawn"]["longitudinal_m"] = 150.0
        for event in variant["events"]:
            event["action"]["steering"] = 0.0
    elif mutation == "advance_oncoming_clearance":
        _participant(variant, "oncoming")["spawn"]["longitudinal_m"] = 30.0
    else:
        raise AssertionError(f"unknown frozen counterfactual mutation: {mutation}")
    return variant


def _run(
    source_path: Path,
    *,
    workspace: Path,
    run_id: str,
) -> tuple[Any, RunOutcome]:
    bundle = ScenarioCompiler().compile(
        instantiate_scenario(load_scenario(source_path))
    )
    assert bundle.report.overall_status is CompilationStatus.EXACT
    assert bundle.report.executable is True
    assert bundle.report.diagnostics == ()
    outcome = RunSupervisor(workspace=workspace, project_root=ROOT).run(
        bundle,
        run_id=run_id,
        attempt_id="attempt-0001",
        timeout_seconds=120,
    )
    assert isinstance(outcome, RunOutcome)
    assert outcome.worker_exited is True
    assert outcome.worker_exit_code == 0
    worker = _json(outcome.published_path / "output" / "worker_result.json")
    assert worker["backend"] == {
        "asset_version": "0.4.3",
        "distribution": "metadrive-simulator",
        "engine_class": "MultiAgentMetaDrive",
        "version": "0.4.3",
    }
    return bundle, outcome


def _observed_axes(outcome: RunOutcome) -> dict[str, Any]:
    published = outcome.published_path
    events = _json(published / "output" / "events.json")
    metrics = _json(published / "output" / "metrics.json")
    values = {item["metric"]: item["value"] for item in metrics["metric_values"]}
    return {
        "ordered_events": events,
        "risk_metrics": {
            key: values[key]
            for key in ("collision", "hard_braking", "minimum_ttc", "completion_time")
        },
        "outcome": {
            "scenario_outcome": metrics["scenario_outcome"],
            "termination_reason": metrics["termination_reason"],
        },
    }


def test_counterfactuals_are_frozen_for_all_five_presets() -> None:
    fixture = json.loads(COUNTERFACTUALS.read_text(encoding="utf-8"))

    assert fixture["schema_version"] == "scenarioforge.p0c-counterfactuals/v1"
    assert [item["preset_id"] for item in fixture["counterfactuals"]] == [
        "construction_merge",
        "highway_merge",
        "brake_lead",
        "dangerous_cut_in",
        "unprotected_left_turn",
    ]
    assert all(
        item["acceptable_changes"] == [
            "ordered_events",
            "risk_metrics",
            "outcome",
        ]
        for item in fixture["counterfactuals"]
    )
    assert [item["required_change"] for item in fixture["counterfactuals"]] == [
        "outcome",
        "risk_metrics",
        "ordered_events",
        "outcome",
        "risk_metrics",
    ]


@pytest.mark.parametrize(
    "counterfactual",
    json.loads(COUNTERFACTUALS.read_text(encoding="utf-8"))["counterfactuals"],
    ids=lambda item: item["preset_id"],
)
def test_removing_or_weakening_each_hazard_changes_real_execution_evidence(
    counterfactual: dict[str, Any],
    tmp_path: Path,
) -> None:
    preset_id = counterfactual["preset_id"]
    baseline_path = ROOT / "examples" / "p0c" / f"{preset_id}.json"
    baseline_source = json.loads(baseline_path.read_text(encoding="utf-8"))
    assert hashlib.sha256(canonical_bytes(baseline_source)).hexdigest() == (
        counterfactual["baseline_source_spec_digest"]
    )
    variant_source = _apply_counterfactual(baseline_source, counterfactual)
    variant_path = tmp_path / f"{preset_id}-counterfactual.json"
    variant_path.write_bytes(canonical_bytes(variant_source))

    baseline_bundle, baseline = _run(
        baseline_path,
        workspace=tmp_path / "baseline",
        run_id=f"run-counterfactual-baseline-{preset_id}",
    )
    baseline_actions = baseline.published_path / "output" / "actions.json"
    baseline_actions_digest = _digest(baseline_actions)
    variant_bundle, variant = _run(
        variant_path,
        workspace=tmp_path / "variant",
        run_id=f"run-counterfactual-variant-{preset_id}",
    )

    assert baseline_bundle.scenario_instance.digest != variant_bundle.scenario_instance.digest
    assert _observed_axes(baseline)["outcome"]["scenario_outcome"] == (
        counterfactual["baseline_outcome"]
    )
    baseline_axes = _observed_axes(baseline)
    variant_axes = _observed_axes(variant)
    changed = [axis for axis in counterfactual["acceptable_changes"] if baseline_axes[axis] != variant_axes[axis]]
    assert changed, (
        f"{preset_id} counterfactual did not change ordered events, risk metrics, "
        "or outcome"
    )
    assert counterfactual["required_change"] in changed

    assert sorted(path.name for path in variant.input_snapshot_path.iterdir()) == INPUT_MEMBERS
    assert not (variant.input_snapshot_path / "actions.json").exists()
    assert baseline_actions_digest not in repr(
        _json(variant.input_snapshot_path / "run_manifest.json")
    )
    variant_actions = _json(variant.published_path / "output" / "actions.json")
    assert variant_actions
    assert all(
        action["source"] in {"policy", "declared_route", "scenario_override"}
        for action in variant_actions
    )
