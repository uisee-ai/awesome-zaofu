from __future__ import annotations

import copy
import hashlib
import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from scenarioforge.core import (
    ScenarioCompiler,
    canonical_bytes,
    instantiate_scenario,
    load_scenario,
)


ROOT = Path(__file__).resolve().parents[3]
PROTOTYPE = ROOT / "tests" / "fixtures" / "p0c" / "contracts" / "prototype_v2.json"
FROZEN = (
    ROOT
    / "tests"
    / "fixtures"
    / "p0c"
    / "calibration"
    / "frozen-contracts.json"
)
EXPECTED_PRESETS = (
    "construction_merge",
    "highway_merge",
    "brake_lead",
    "dangerous_cut_in",
    "unprotected_left_turn",
)
METRICS = {
    "collision",
    "hard_braking",
    "minimum_ttc",
    "completion_time",
    "termination_reason",
}


def _deep_update(target: dict[str, Any], patch: dict[str, Any]) -> None:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_update(target[key], value)
        else:
            target[key] = copy.deepcopy(value)


def _render_scenario(
    prototype: dict[str, Any], preset: dict[str, Any]
) -> dict[str, Any]:
    scenario = copy.deepcopy(prototype)
    _deep_update(scenario, preset["scenario_patch"])
    participants = [str(item["id"]) for item in scenario["participants"]]
    topology_kind = str(scenario["road"]["topology_kind"])
    metric_contract = preset["metric_contract"]
    for definition in scenario["constraints"]["metric_definitions"]:
        metric = str(definition["metric"])
        scope = metric_contract[metric]
        definition["applies_to"]["participant_ids"] = (
            participants if scope["participant_ids"] == "all" else scope["participant_ids"]
        )
        definition["applies_to"]["topology_kinds"] = [topology_kind]
        definition["threshold"] = scope["threshold"]
    return scenario


def _run_real_metadrive(
    scenario_data: dict[str, Any], runtime_path: Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    scenario_path = runtime_path / "scenario.json"
    scenario_path.write_bytes(canonical_bytes(scenario_data))
    scenario = instantiate_scenario(load_scenario(scenario_path))
    bundle = ScenarioCompiler().compile(scenario)
    assert bundle.report.executable is True, bundle.report.to_dict()
    assert bundle.execution_plan is not None

    plan = bundle.execution_plan.to_dict()
    plan_path = runtime_path / "execution-plan.json"
    artifacts_path = runtime_path / "artifacts.json"
    plan_path.write_bytes(canonical_bytes(plan))
    child_environment = dict(os.environ)
    inherited_python_path = child_environment.get("PYTHONPATH", "")
    child_environment["PYTHONPATH"] = str(ROOT / "src") + (
        os.pathsep + inherited_python_path if inherited_python_path else ""
    )
    child_environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json,sys; from pathlib import Path; "
                "from scenarioforge.core import canonical_bytes; "
                "from scenarioforge.runtime.adapter import MetaDriveAdapter; "
                "plan=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8')); "
                "Path(sys.argv[2]).write_bytes(canonical_bytes(MetaDriveAdapter(plan).run()))"
            ),
            str(plan_path),
            str(artifacts_path),
        ],
        cwd=ROOT,
        env=child_environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr
    return plan, json.loads(artifacts_path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def frozen_contract() -> tuple[dict[str, Any], dict[str, Any]]:
    frozen = json.loads(FROZEN.read_text(encoding="utf-8"))
    prototype = json.loads(PROTOTYPE.read_text(encoding="utf-8"))
    return frozen, prototype


@pytest.fixture(scope="module")
def real_runs(
    frozen_contract: tuple[dict[str, Any], dict[str, Any]],
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, list[tuple[dict[str, Any], dict[str, Any]]]]:
    frozen, prototype = frozen_contract
    results: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {}
    for preset in frozen["presets"]:
        preset_id = str(preset["preset_id"])
        scenario = _render_scenario(prototype, preset)
        results[preset_id] = [
            _run_real_metadrive(
                scenario,
                tmp_path_factory.mktemp(f"{preset_id}-run-{run_index}"),
            )
            for run_index in range(1, int(frozen["reproduction_runs"]) + 1)
        ]
    return results


def test_frozen_contract_is_exact_bounded_and_complete(
    frozen_contract: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    frozen, prototype = frozen_contract
    assert frozen["schema_version"] == "scenarioforge.calibration-freeze/v1"
    assert frozen["prototype_ref"] == (
        "tests/fixtures/p0c/contracts/prototype_v2.json"
    )
    assert frozen["prototype_digest"] == hashlib.sha256(
        canonical_bytes(prototype)
    ).hexdigest()
    assert frozen["environment"] == {
        "os": "Linux",
        "architecture": "x86_64",
        "python": "3.11.15",
        "simulator_distribution": "metadrive-simulator",
        "simulator_version": "0.4.3",
        "asset_version": "0.4.3",
        "headless": True,
        "gpu_required": False,
    }
    assert platform.system() == frozen["environment"]["os"]
    assert platform.machine() == frozen["environment"]["architecture"]
    assert tuple(item["preset_id"] for item in frozen["presets"]) == EXPECTED_PRESETS
    assert frozen["candidate_limit"] == 5
    assert frozen["reproduction_runs"] == 3

    for preset in frozen["presets"]:
        assert 1 <= preset["candidate_count"] <= frozen["candidate_limit"]
        scenario = _render_scenario(prototype, preset)
        assert preset["fixture_digest"] == hashlib.sha256(
            canonical_bytes(scenario)
        ).hexdigest()
        assert scenario["scenario_id"] == preset["preset_id"]
        assert isinstance(scenario["seed"], int)
        assert 10.0 <= scenario["constraints"]["duration_s"] <= 20.0
        assert scenario["constraints"]["target_outcome"] == preset["expected"][
            "scenario_outcome"
        ]
        assert [item["sequence"] for item in scenario["events"]] == list(
            range(len(scenario["events"]))
        )
        assert scenario["constraints"]["expected_events"] == [
            item["id"] for item in scenario["events"]
        ]
        assert scenario["constraints"]["success_predicates"]
        assert scenario["constraints"]["failure_predicates"]
        assert scenario["policy"]["id"] == "scenarioforge.deterministic-control"
        assert scenario["policy"]["version"] == "2.0.0"
        assert {item["metric"] for item in scenario["constraints"]["metric_definitions"]} == METRICS
        assert all(
            item["applies_to"]["topology_kinds"]
            for item in scenario["constraints"]["metric_definitions"]
        )


def test_left_turn_freeze_requires_a_completed_yield_and_route(
    frozen_contract: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    frozen, _ = frozen_contract
    preset = next(
        item
        for item in frozen["presets"]
        if item["preset_id"] == "unprotected_left_turn"
    )
    success = preset["expected"]["predicate_results"]["success"]
    failure = preset["expected"]["predicate_results"]["failure"]

    assert preset["expected"]["termination_reason"] == (
        "success_predicates_satisfied"
    )
    assert success == [
        {
            "predicate_id": "yield-completed",
            "kind": "yield_completed",
            "satisfied": True,
        }
    ]
    assert next(
        item for item in failure if item["predicate_id"] == "turn-timeout"
    )["satisfied"] is False
    assert preset["expected"]["metric_ranges"]["completion_time"] is not None


def test_three_real_headless_runs_match_frozen_outcomes_events_and_tolerances(
    frozen_contract: tuple[dict[str, Any], dict[str, Any]],
    real_runs: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]],
) -> None:
    frozen, prototype = frozen_contract
    by_id = {item["preset_id"]: item for item in frozen["presets"]}
    for preset_id in EXPECTED_PRESETS:
        preset = by_id[preset_id]
        scenario = _render_scenario(prototype, preset)
        reference_trajectory: list[dict[str, Any]] | None = None
        for plan, artifacts in real_runs[preset_id]:
            metrics = artifacts["metrics.json"]
            events = artifacts["events.json"]
            trajectory = artifacts["trajectory.json"]
            assert plan["simulation"]["headless"] is True
            assert plan["backend"]["version"] == "0.4.3"
            assert metrics["execution_status"] == "completed"
            assert metrics["scenario_outcome"] == preset["expected"]["scenario_outcome"]
            assert metrics["target_outcome_match"] is True
            assert metrics["termination_reason"] == preset["expected"][
                "termination_reason"
            ]
            assert [item["event_id"] for item in events] == scenario["constraints"][
                "expected_events"
            ]
            assert metrics["predicate_results"] == preset["expected"][
                "predicate_results"
            ]
            values = {item["metric"]: item["value"] for item in metrics["metric_values"]}
            for metric, bounds in preset["expected"]["metric_ranges"].items():
                value = values[metric]
                if bounds is None:
                    assert value is None
                else:
                    assert bounds["minimum"] <= value <= bounds["maximum"]

            initial = {
                point["participant_id"]: point
                for point in trajectory
                if point["tick"] == 0
            }
            for participant in scenario["participants"]:
                point = initial[participant["id"]]
                assert point["lane_id"] == participant["spawn"]["lane_id"]
                assert abs(
                    (point["heading_deg"] - participant["spawn"]["heading_deg"] + 180.0)
                    % 360.0
                    - 180.0
                ) <= frozen["trajectory_tolerance"]["heading_abs_deg"]

            if reference_trajectory is None:
                reference_trajectory = trajectory
            else:
                assert len(trajectory) == len(reference_trajectory)
                for reference, observed in zip(reference_trajectory, trajectory):
                    assert observed["tick"] == reference["tick"]
                    assert observed["participant_id"] == reference["participant_id"]
                    assert observed["lane_id"] == reference["lane_id"]
                    for expected, actual in zip(
                        reference["position_m"], observed["position_m"]
                    ):
                        assert abs(actual - expected) <= frozen["trajectory_tolerance"][
                            "position_abs_m"
                        ]
                    assert abs(observed["speed_mps"] - reference["speed_mps"]) <= frozen[
                        "trajectory_tolerance"
                    ]["speed_abs_mps"]


def test_left_turn_yields_before_conflict_traversal_and_completes_route(
    real_runs: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]],
) -> None:
    for _, artifacts in real_runs["unprotected_left_turn"]:
        trajectory = artifacts["trajectory.json"]
        ego_points = [
            point for point in trajectory if point["participant_id"] == "ego"
        ]
        oncoming_points = [
            point
            for point in trajectory
            if point["participant_id"] == "oncoming"
        ]
        ego_lane_ids = list(
            dict.fromkeys(point["lane_id"] for point in ego_points)
        )
        oncoming_conflict_ticks = [
            point["tick"]
            for point in oncoming_points
            if point["lane_id"] == "oncoming-through"
        ]
        ego_conflict_ticks = [
            point["tick"]
            for point in ego_points
            if point["lane_id"] == "ego-left-turn"
        ]
        yield_action = next(
            action
            for action in artifacts["actions.json"]
            if action["participant_id"] == "ego" and action["tick"] == 20
        )

        assert yield_action["source"] == "scenario_override"
        assert yield_action["final_action"]["throttle_brake"] == -1.0
        assert [
            action["tick"]
            for action in artifacts["actions.json"]
            if action["participant_id"] == "ego"
            and action["source"] == "scenario_override"
            and action["final_action"]["throttle_brake"] == -1.0
        ] == list(range(20, 39))
        assert max(
            point["speed_mps"]
            for point in ego_points
            if 28 <= point["tick"] <= 39
        ) < 0.5
        assert oncoming_conflict_ticks
        assert ego_conflict_ticks
        assert max(oncoming_conflict_ticks) < min(ego_conflict_ticks)
        assert ego_lane_ids == ["ego-inbound", "ego-left-turn", "ego-exit"]
        assert ego_points[-1]["lane_id"] == "ego-exit"
        assert ego_points[-1]["route_completed"] is True
        assert artifacts["metrics.json"]["scenario_outcome"] == "near_miss"
