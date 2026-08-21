from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path

import pytest

from scenarioforge.core import ScenarioCompiler, instantiate_scenario, load_scenario
from scenarioforge.repro import (
    CounterfactualSpec,
    ReproducibilityRunner,
    SeedContract,
    ToleranceProfile,
    apply_counterfactual,
    assess_counterfactual,
    compare_trajectory_series,
    publish_comparison_report,
    resolve_seeded_instance,
)
from scenarioforge.runtime import RunSupervisor


ROOT = Path(__file__).resolve().parents[1]
HAPPY_EXAMPLE = ROOT / "examples" / "p0a" / "brake_lead.json"
STRESS_FIXTURE = ROOT / "tests" / "fixtures" / "p0a" / "repro" / "brake_lead_stress.json"
SEED_CONTRACT_FIXTURE = ROOT / "tests" / "fixtures" / "p0a" / "repro" / "seed_contract.json"
TOLERANCE_FIXTURE = ROOT / "tests" / "fixtures" / "p0a" / "repro" / "tolerance_profile.json"
COUNTERFACTUAL_DIR = ROOT / "examples" / "p0a" / "counterfactuals"


def _read(path: Path) -> dict[str, object] | list[object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_seed_resolution_and_real_counterfactuals_have_declared_effects(tmp_path: Path) -> None:
    stress_instance = instantiate_scenario(load_scenario(STRESS_FIXTURE))
    seed_payload = _read(SEED_CONTRACT_FIXTURE)
    assert isinstance(seed_payload, dict)
    seed_contract = SeedContract.from_dict(seed_payload)
    assert seed_contract.to_dict() == seed_payload

    first = resolve_seeded_instance(stress_instance, seed_contract, seed=7)
    repeated = resolve_seeded_instance(stress_instance, seed_contract, seed=7)
    different = resolve_seeded_instance(stress_instance, seed_contract, seed=8)
    assert first.to_dict() == repeated.to_dict()
    assert first.digest == repeated.digest
    assert first.seed == 7
    assert different.seed == 8
    assert any(
        first.parameters[field] != different.parameters[field]
        for field in ("initial_gap_m", "brake_tick")
    )
    assert next(item for item in first.participants if item["id"] == "lead")["initial"][
        "longitudinal_m"
    ] == pytest.approx(
        next(item for item in first.participants if item["id"] == "ego")["initial"][
            "longitudinal_m"
        ]
        + first.parameters["initial_gap_m"]
    )
    assert first.events[0]["trigger"]["tick"] == first.parameters["brake_tick"]

    cancel_payload = _read(COUNTERFACTUAL_DIR / "cancel_braking.json")
    gap_payload = _read(COUNTERFACTUAL_DIR / "increase_initial_gap.json")
    assert isinstance(cancel_payload, dict)
    assert isinstance(gap_payload, dict)
    cancel = CounterfactualSpec.from_dict(cancel_payload)
    increase_gap = CounterfactualSpec.from_dict(gap_payload)
    assert cancel.to_dict() == cancel_payload
    assert increase_gap.to_dict() == gap_payload

    cancelled_instance = apply_counterfactual(stress_instance, cancel)
    wider_instance = apply_counterfactual(stress_instance, increase_gap)
    assert cancelled_instance.events == ()
    assert "event.tick-brake" not in cancelled_instance.required_capabilities
    assert cancelled_instance.parameters["brake_intensity"] == 0.0
    assert wider_instance.parameters["initial_gap_m"] == 100.0
    assert next(item for item in wider_instance.participants if item["id"] == "lead")[
        "initial"
    ]["longitudinal_m"] == 105.0

    compiler = ScenarioCompiler()
    base_bundle = compiler.compile(stress_instance)
    cancel_bundle = compiler.compile(cancelled_instance)
    gap_bundle = compiler.compile(wider_instance)
    assert base_bundle.execution_plan is not None
    assert cancel_bundle.execution_plan is not None
    assert gap_bundle.execution_plan is not None

    supervisor = RunSupervisor(workspace=tmp_path / "counterfactual-runs", project_root=ROOT)
    base_run = supervisor.run(
        base_bundle,
        run_id="run-counterfactual-base",
        attempt_id="attempt-0001",
        timeout_seconds=120,
    )
    cancel_run = supervisor.run(
        cancel_bundle,
        run_id="run-counterfactual-cancel",
        attempt_id="attempt-0001",
        timeout_seconds=120,
    )
    gap_run = supervisor.run(
        gap_bundle,
        run_id="run-counterfactual-gap",
        attempt_id="attempt-0001",
        timeout_seconds=120,
    )
    base_outputs = {
        "events.json": _read(base_run.published_path / "output" / "events.json"),
        "metrics.json": _read(base_run.published_path / "output" / "metrics.json"),
    }
    cancel_outputs = {
        "events.json": _read(cancel_run.published_path / "output" / "events.json"),
        "metrics.json": _read(cancel_run.published_path / "output" / "metrics.json"),
    }
    gap_outputs = {
        "events.json": _read(gap_run.published_path / "output" / "events.json"),
        "metrics.json": _read(gap_run.published_path / "output" / "metrics.json"),
    }
    cancel_result = assess_counterfactual(base_outputs, cancel_outputs, cancel)
    gap_result = assess_counterfactual(base_outputs, gap_outputs, increase_gap)

    assert cancel_result.to_dict() == {
        "schema_version": "scenarioforge.counterfactual-result/v1",
        "counterfactual_id": "cancel-lead-brake",
        "kind": "cancel_braking",
        "expected_change": "key_event",
        "observed_change": True,
        "baseline": {
            "key_events": [
                {
                    "event_id": "lead-brake",
                    "type": "trigger_fired",
                    "participant_id": "lead",
                    "trigger_tick": 0,
                    "effect_state_tick": 1,
                },
                {
                    "event_id": "minimum-ttc-below-2s",
                    "type": "minimum_ttc_below_threshold",
                    "participant_id": "ego,lead",
                    "trigger_tick": 5,
                    "effect_state_tick": 5,
                }
            ]
        },
        "variant": {
            "key_events": [
                {
                    "event_id": "minimum-ttc-below-2s",
                    "type": "minimum_ttc_below_threshold",
                    "participant_id": "ego,lead",
                    "trigger_tick": 5,
                    "effect_state_tick": 5,
                }
            ]
        },
        "passed": True,
    }
    assert gap_result.to_dict() == {
        "schema_version": "scenarioforge.counterfactual-result/v1",
        "counterfactual_id": "increase-lead-gap",
        "kind": "increase_initial_gap",
        "expected_change": "key_event",
        "observed_change": True,
        "baseline": {
            "key_events": [
                {
                    "event_id": "lead-brake",
                    "type": "trigger_fired",
                    "participant_id": "lead",
                    "trigger_tick": 0,
                    "effect_state_tick": 1,
                },
                {
                    "event_id": "minimum-ttc-below-2s",
                    "type": "minimum_ttc_below_threshold",
                    "participant_id": "ego,lead",
                    "trigger_tick": 5,
                    "effect_state_tick": 5,
                },
            ]
        },
        "variant": {
            "key_events": [
                {
                    "event_id": "lead-brake",
                    "type": "trigger_fired",
                    "participant_id": "lead",
                    "trigger_tick": 0,
                    "effect_state_tick": 1,
                }
            ]
        },
        "passed": True,
    }


def test_trajectory_comparison_uses_circular_heading_and_null_ttc() -> None:
    tolerance_payload = _read(TOLERANCE_FIXTURE)
    assert isinstance(tolerance_payload, dict)
    assert ToleranceProfile.p0a().to_dict() == tolerance_payload
    trajectories = [
        [
            {
                "schema_version": "scenarioforge.trajectory-point/v1",
                "tick": 0,
                "participant_id": "ego",
                "position_m": [1.0, 2.0],
                "speed_mps": 10.0,
                "heading_deg": 179.96,
                "collision": False,
            }
        ],
        [
            {
                "schema_version": "scenarioforge.trajectory-point/v1",
                "tick": 0,
                "participant_id": "ego",
                "position_m": [1.005, 2.0],
                "speed_mps": 10.005,
                "heading_deg": -179.99,
                "collision": False,
            }
        ],
        [
            {
                "schema_version": "scenarioforge.trajectory-point/v1",
                "tick": 0,
                "participant_id": "ego",
                "position_m": [1.01, 2.0],
                "speed_mps": 9.995,
                "heading_deg": 179.99,
                "collision": False,
            }
        ],
    ]
    metrics = [
        {"min_ttc_s": None, "completed_steps": 10},
        {"min_ttc_s": None, "completed_steps": 11},
        {"min_ttc_s": None, "completed_steps": 10},
    ]
    comparison = compare_trajectory_series(trajectories, metrics, ToleranceProfile.p0a())
    assert comparison.to_dict() == {
        "schema_version": "scenarioforge.continuous-comparison/v1",
        "aligned_participant_ids": ["ego"],
        "aligned_ticks": [0],
        "max_deltas": {
            "position_m": 0.01,
            "speed_mps": 0.01,
            "heading_deg": 0.05,
            "min_ttc_s": 0.0,
            "completed_steps": 1,
        },
        "null_ttc_semantics": "all_null_equal",
        "violations": [],
        "passed": True,
    }

    mixed_metrics = [
        {"min_ttc_s": None, "completed_steps": 10},
        {"min_ttc_s": 1.0, "completed_steps": 10},
        {"min_ttc_s": None, "completed_steps": 10},
    ]
    mixed = compare_trajectory_series(trajectories, mixed_metrics, ToleranceProfile.p0a())
    assert mixed.passed is False
    assert mixed.null_ttc_semantics == "mixed_null_mismatch"
    assert {item["field"] for item in mixed.violations} == {"min_ttc_s"}


@pytest.fixture(scope="module")
def three_run_outcome(tmp_path_factory: pytest.TempPathFactory):
    bundle = ScenarioCompiler().compile(instantiate_scenario(load_scenario(HAPPY_EXAMPLE)))
    runner = ReproducibilityRunner(
        workspace=tmp_path_factory.mktemp("scenarioforge-repro"),
        project_root=ROOT,
    )
    return runner.run_three(
        bundle,
        comparison_id="comparison-happy-0001",
        run_id_prefix="run-repro-happy",
        timeout_seconds=120,
    )


def test_three_independent_workers_reexecute_policy_and_publish_comparison(
    three_run_outcome,
    tmp_path: Path,
) -> None:
    outcomes = three_run_outcome.runs
    report = three_run_outcome.report
    assert len(outcomes) == 3
    assert len({item.run_result.run_id for item in outcomes}) == 3
    assert len({item.worker_pid for item in outcomes}) == 3
    assert all(item.worker_exited and item.worker_exit_code == 0 for item in outcomes)

    for index, outcome in enumerate(outcomes, start=1):
        assert outcome.run_result.run_id == f"run-repro-happy-{index:04d}"
        assert outcome.run_result.attempt_id == "attempt-0001"
        assert outcome.run_result.status == "success"
        assert sorted(path.name for path in outcome.input_snapshot_path.iterdir()) == [
            "assets.json",
            "compile_report.json",
            "execution_plan.json",
            "policy.json",
            "run_manifest.json",
            "run_request.json",
        ]
        assert not (outcome.input_snapshot_path / "actions.json").exists()

    payload = report.to_dict()
    assert set(payload) == {
        "schema_version",
        "comparison_id",
        "run_references",
        "comparison_scope",
        "excluded_nonsemantic_fields",
        "policy_reexecution",
        "discrete",
        "continuous",
        "tolerances",
        "passed",
    }
    assert payload["schema_version"] == "scenarioforge.repro-comparison/v1"
    assert payload["comparison_id"] == "comparison-happy-0001"
    assert payload["passed"] is True
    assert payload["excluded_nonsemantic_fields"] == [
        "artifact_path",
        "attempt_id",
        "run_id",
        "wall_clock_timestamp",
    ]
    assert payload["tolerances"] == ToleranceProfile.p0a().to_dict()
    assert payload["comparison_scope"] == {
        "run_count": 3,
        "scenario_instance_digest": outcomes[0].bundle.scenario_instance.digest,
        "seed": 7,
        "execution_plan_digest": outcomes[0].bundle.execution_plan.digest,
        "policy": {
            "id": "scenarioforge.constant-lane",
            "version": "1.0.0",
        },
        "tolerances_version": "scenarioforge.p0a-tolerances/v1",
    }
    assert payload["policy_reexecution"] == {
        "action_generation": "worker_policy_per_tick",
        "historical_actions_used": False,
        "action_sequence_digests": [
            payload["policy_reexecution"]["action_sequence_digests"][0]
        ]
        * 3,
        "matched": True,
    }
    assert payload["discrete"]["passed"] is True
    assert payload["discrete"]["terminal_status"] == "success"
    assert payload["discrete"]["termination_reason"] == "horizon_completed"
    assert payload["discrete"]["collision"] is False
    assert payload["discrete"]["collision_participants"] == []
    assert payload["discrete"]["mismatches"] == []
    assert payload["continuous"]["passed"] is True
    assert payload["continuous"]["aligned_participant_ids"] == ["ego", "lead"]
    assert payload["continuous"]["aligned_ticks"] == list(range(7))
    assert payload["continuous"]["violations"] == []

    assert payload["run_references"] == [
        {
            "schema_version": "scenarioforge.immutable-run-reference/v1",
            "run_id": outcome.run_result.run_id,
            "scenario_instance_digest": outcome.bundle.scenario_instance.digest,
            "execution_plan_digest": outcome.bundle.execution_plan.digest,
            "run_result_digest": _digest(outcome.published_path / "run_result.json"),
            "artifact_index_digest": _digest(outcome.published_path / "artifact_index.json"),
        }
        for outcome in outcomes
    ]

    destination = tmp_path / "comparison.json"
    publish_comparison_report(report, destination)
    assert _read(destination) == payload
    assert stat.S_IMODE(destination.stat().st_mode) == 0o444
    with pytest.raises(FileExistsError):
        publish_comparison_report(report, destination)
