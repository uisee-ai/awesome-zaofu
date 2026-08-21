from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from scenarioforge.policies import trusted_policy_pair
from scenarioforge.repro import (
    P0MatrixSpec,
    PolicyRunSample,
    RegressionCase,
    RegressionContractError,
    RegressionThresholds,
    compare_policy_pair,
    compare_regression_matrix,
    regression_contract,
)


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_FIXTURE = (
    ROOT / "tests" / "fixtures" / "p0-continuation" / "regression-contract.json"
)
DIGESTS = tuple(f"{index:064x}" for index in range(1, 20))


def _baseline_config() -> dict[str, object]:
    return {
        "default_action": {"steering": 0.0, "throttle_brake": 0.0},
        "participant_actions": [
            {"participant_id": "ego", "steering": 0.0, "throttle_brake": 0.0},
            {"participant_id": "lead", "steering": 0.0, "throttle_brake": 0.0},
        ],
    }


def _case(*, preset_id: str = "brake_lead", seed: int = 7) -> RegressionCase:
    return RegressionCase(
        schema_version="scenarioforge.regression-case/v1",
        case_id=f"{preset_id}-seed-{seed}",
        preset_id=preset_id,
        seed=seed,
        world_instance_digest=DIGESTS[0],
        scenario_revision_digest=DIGESTS[1],
        assets_digest=DIGESTS[2],
        environment_digest=DIGESTS[3],
        resource_config_digest=DIGESTS[4],
        metric_definitions_digest=DIGESTS[5],
        tolerances_digest=DIGESTS[6],
        route_digest=DIGESTS[7],
        nominal_speed_digest=DIGESTS[8],
    )


def _metrics(
    *,
    min_ttc: float = 3.0,
    completion_time: float = 10.0,
    hard_braking: float = -1.0,
    threshold_met: bool = False,
) -> dict[str, object]:
    return {
        "minimum_ttc": {
            "definition_id": "scenarioforge.metric.minimum-ttc/v2",
            "unit": "s",
            "value": min_ttc,
            "threshold": {"operator": "lte", "value": 2.0},
            "threshold_met": threshold_met,
            "null_semantics": "no_closing_pair",
        },
        "completion_time": {
            "definition_id": "scenarioforge.metric.completion-time/v2",
            "unit": "s",
            "value": completion_time,
            "threshold": None,
            "threshold_met": None,
            "null_semantics": "execution_incomplete",
        },
        "hard_braking": {
            "definition_id": "scenarioforge.metric.hard-braking/v2",
            "unit": "m/s^2",
            "value": hard_braking,
            "threshold": {"operator": "lte", "value": -2.0},
            "threshold_met": False,
            "null_semantics": "threshold_pending_calibration",
        },
    }


def _samples(case: RegressionCase) -> tuple[PolicyRunSample, PolicyRunSample]:
    baseline_binding, candidate_binding = trusted_policy_pair(_baseline_config())
    common = {
        "schema_version": "scenarioforge.policy-run-sample/v1",
        "case_digest": case.digest,
        "world_instance_digest": case.world_instance_digest,
        "route_digest": case.route_digest,
        "nominal_speed_digest": case.nominal_speed_digest,
        "collision": False,
        "success": True,
        "scenario_outcome": "near_miss",
        "scenario_override_digest": DIGESTS[9],
        "run_result_digest": DIGESTS[10],
        "artifact_index_digest": DIGESTS[11],
    }
    baseline = PolicyRunSample(
        **common,
        run_id=f"{case.case_id}-baseline",
        attempt_id="attempt-0001",
        policy_binding=baseline_binding,
        metrics=_metrics(),
        earliest_brake_tick=10,
    )
    candidate = PolicyRunSample(
        **{
            **common,
            "run_result_digest": DIGESTS[12],
            "artifact_index_digest": DIGESTS[13],
        },
        run_id=f"{case.case_id}-candidate",
        attempt_id="attempt-0001",
        policy_binding=candidate_binding,
        metrics=_metrics(min_ttc=3.2, completion_time=10.5),
        earliest_brake_tick=8,
    )
    return baseline, candidate


def test_regression_contract_is_complete_and_matrix_is_exactly_five_by_two_by_three() -> None:
    golden = json.loads(CONTRACT_FIXTURE.read_text(encoding="utf-8"))

    assert regression_contract() == golden
    assert P0MatrixSpec.p0().to_dict() == golden["matrix"]
    assert P0MatrixSpec.p0().pair_count == 15
    assert P0MatrixSpec.p0().real_child_runs == 30
    assert P0MatrixSpec.p0().seeds == (7, 8, 9)
    assert P0MatrixSpec.p0().statistical_significance_claimed is False
    assert RegressionThresholds.p0().to_dict() == golden["thresholds"]


def test_one_strict_pair_reports_complete_samples_deltas_and_no_fabricated_pass() -> None:
    case = _case()
    baseline, candidate = _samples(case)

    report = compare_policy_pair(case, baseline, candidate)

    assert report.to_dict() == {
        "schema_version": "scenarioforge.paired-regression/v1",
        "case": case.to_dict(),
        "baseline": baseline.to_dict(),
        "candidate": candidate.to_dict(),
        "thresholds": RegressionThresholds.p0().to_dict(),
        "metric_deltas": {
            "minimum_ttc_s": 0.2,
            "completion_time_s": 0.5,
            "hard_braking_mps2": 0.0,
        },
        "violations": [],
        "passed": True,
    }


@pytest.mark.parametrize(
    ("mutation", "violation"),
    [
        ("collision", "new_collision"),
        ("success", "success_to_failure"),
        ("threshold", "threshold_transition:minimum_ttc"),
        ("ttc", "minimum_ttc_regression"),
        ("completion", "completion_time_regression"),
        ("braking", "hard_braking_regression"),
        ("route", "route_changed"),
        ("speed", "nominal_speed_changed"),
        ("priority", "scenario_priority_changed"),
        ("response", "defensive_response_not_earlier"),
    ],
)
def test_every_safety_or_pairing_regression_fails_closed(
    mutation: str,
    violation: str,
) -> None:
    case = _case()
    baseline, candidate = _samples(case)
    if mutation == "collision":
        candidate = replace(candidate, collision=True)
    elif mutation == "success":
        candidate = replace(candidate, success=False, scenario_outcome="collision_failure")
    elif mutation == "threshold":
        candidate = replace(candidate, metrics=_metrics(threshold_met=True))
    elif mutation == "ttc":
        candidate = replace(candidate, metrics=_metrics(min_ttc=2.9))
    elif mutation == "completion":
        candidate = replace(candidate, metrics=_metrics(completion_time=11.01))
    elif mutation == "braking":
        candidate = replace(candidate, metrics=_metrics(hard_braking=-1.06))
    elif mutation == "route":
        candidate = replace(candidate, route_digest=DIGESTS[14])
    elif mutation == "speed":
        candidate = replace(candidate, nominal_speed_digest=DIGESTS[15])
    elif mutation == "priority":
        candidate = replace(candidate, scenario_override_digest=DIGESTS[16])
    elif mutation == "response":
        candidate = replace(candidate, earliest_brake_tick=11)

    report = compare_policy_pair(case, baseline, candidate)

    assert violation in report.violations
    assert report.passed is False


def test_pair_rejects_a_stale_case_or_policy_order_before_comparison() -> None:
    case = _case()
    baseline, candidate = _samples(case)

    with pytest.raises(RegressionContractError):
        compare_policy_pair(case, replace(baseline, case_digest=DIGESTS[17]), candidate)
    with pytest.raises(RegressionContractError):
        compare_policy_pair(case, candidate, baseline)


def test_matrix_requires_all_fifteen_pairs_and_blocks_success_rate_decline() -> None:
    pairs = []
    for preset_id in P0MatrixSpec.p0().presets:
        for seed in P0MatrixSpec.p0().seeds:
            case = _case(preset_id=preset_id, seed=seed)
            pairs.append(compare_policy_pair(case, *_samples(case)))

    report = compare_regression_matrix(pairs)

    assert report.pair_count == 15
    assert report.real_child_runs == 30
    assert report.baseline_success_count == 15
    assert report.candidate_success_count == 15
    assert report.violations == ()
    assert report.statistical_significance_claimed is False
    assert report.passed is True

    with pytest.raises(RegressionContractError):
        compare_regression_matrix(pairs[:-1])

    degraded = list(pairs)
    degraded_case = degraded[0].case
    baseline, candidate = _samples(degraded_case)
    degraded[0] = compare_policy_pair(
        degraded_case,
        baseline,
        replace(candidate, success=False, scenario_outcome="collision_failure"),
    )
    failed = compare_regression_matrix(degraded)
    assert "success_rate_decline" in failed.violations
    assert failed.passed is False
