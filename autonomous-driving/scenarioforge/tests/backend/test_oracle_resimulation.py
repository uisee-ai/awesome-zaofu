from __future__ import annotations

import json
from pathlib import Path

import pytest

from scenarioforge.bundle import seal_bundle, verify_bundle
from scenarioforge.compiler import compile_scenario
from scenarioforge.oracle import (
    CalibrationError,
    calibrate_tolerance,
    compare_bundles,
    resimulate,
    verify_exact_replay,
)
from scenarioforge.runtime import run_bundle
from scenarioforge.spec import RunRequest, canonical_scenario, load_scenario


REAL_REPLAY_BUNDLE = Path("evidence/runtime/metadrive-smoke/bundle")


def _compiled(
    scenario_payload: dict[str, object], run_request_payload: dict[str, object]
):
    scenario = load_scenario(json.dumps(scenario_payload), "application/json")
    request_data = {**run_request_payload, "limits": {**run_request_payload["limits"]}}
    request_data["scenario_digest"] = canonical_scenario(scenario).digest
    request_data["seeds"] = [17]
    request = RunRequest.model_validate(request_data)
    return scenario, request, compile_scenario(scenario, request)


def _metric_bundle(
    root: Path,
    *,
    bundle_id: str,
    compiled,
    simulated_seconds: float,
    route_progress: float,
    steps: int = 10,
    verdict: str = "pass",
    effective_config_digest: str | None = None,
    safety_metrics: dict[str, object] | None = None,
    safety_verdict: str = "pass",
) -> Path:
    record = {
        "schema_version": "scenarioforge.run-record.v1",
        "case_index": 0,
        "seed": 17,
        "status": "completed",
        "scenario_verdict": verdict,
        "termination_reason": "max_steps",
        "steps": steps,
        "simulated_seconds": simulated_seconds,
        "collision": False,
        "off_road": False,
        "route_progress": route_progress,
        "wall_seconds": 1.0,
        "cpu_seconds": 0.5,
        "peak_rss_bytes": 100_000,
        "worker_pid": 1000,
        "worker_instance_id": "pid-1000",
        "retry_count": 0,
        "backend": "metadrive-simulator",
        "backend_version": "0.4.3",
        "effective_config_digest": effective_config_digest
        or compiled.cases[0].effective_config_digest,
    }
    files = {
        "compiled_bundle.json": json.dumps(compiled.model_dump(mode="json")).encode(),
        "run_records.json": json.dumps([record]).encode(),
        "traces/case-000.json": b"[]",
        "metrics.json": b"{}",
        "provenance.json": b'{"backend":"metadrive-simulator","backend_version":"0.4.3"}',
    }
    if safety_metrics is not None:
        files["safety_evidence.json"] = json.dumps(
            {
                "schema_version": "scenarioforge.safety-evidence.v1",
                "metric_definitions": {
                    "minimum_ttc_seconds": {
                        "formula_version": "v1",
                        "formula": "min(gap / closing_speed)",
                        "unit": "s",
                        "missing_value": None,
                    }
                },
                "cases": [
                    {
                        "case_index": 0,
                        "metrics": safety_metrics,
                        "safety_constraints": {"collision_free": True},
                        "safety_verdict": safety_verdict,
                        "violations": [] if safety_verdict == "pass" else ["collision"],
                    }
                ],
            }
        ).encode()
    return seal_bundle(
        root,
        bundle_id=bundle_id,
        status="completed",
        scenario_digest=compiled.scenario_digest,
        files=files,
    ).path


def test_five_verified_runs_create_a_versioned_calibrated_profile(
    tmp_path: Path,
    scenario_payload: dict[str, object],
    run_request_payload: dict[str, object],
) -> None:
    _, _, compiled = _compiled(scenario_payload, run_request_payload)
    bundles = [
        _metric_bundle(
            tmp_path,
            bundle_id=f"calibration-{index}",
            compiled=compiled,
            simulated_seconds=value,
            route_progress=progress,
        )
        for index, (value, progress) in enumerate(
            [(1.00, 0.20), (1.01, 0.21), (0.99, 0.19), (1.00, 0.20), (1.00, 0.20)]
        )
    ]

    profile = calibrate_tolerance(bundles)

    assert profile.model_dump(mode="json") == {
        "schema_version": "scenarioforge.tolerance-profile.v1",
        "profile_version": 1,
        "backend": "metadrive-simulator",
        "backend_version": "0.4.3",
        "scenario_digest": compiled.scenario_digest,
        "effective_config_digest": compiled.cases[0].effective_config_digest,
        "ordered_seeds": [17],
        "calibration_runs": 5,
        "numeric_tolerances": {"route_progress": 0.02, "simulated_seconds": 0.02},
        "sample_bundle_digests": list(profile.sample_bundle_digests),
        "profile_digest": profile.profile_digest,
    }
    assert len(profile.sample_bundle_digests) == 5
    assert len(set(profile.sample_bundle_digests)) == 5

    with pytest.raises(CalibrationError, match="exactly five"):
        calibrate_tolerance(bundles[:4])


def test_compatible_results_use_exact_discrete_and_calibrated_numeric_comparison(
    tmp_path: Path,
    scenario_payload: dict[str, object],
    run_request_payload: dict[str, object],
) -> None:
    _, _, compiled = _compiled(scenario_payload, run_request_payload)
    calibration = [
        _metric_bundle(
            tmp_path,
            bundle_id=f"profile-{index}",
            compiled=compiled,
            simulated_seconds=seconds,
            route_progress=progress,
        )
        for index, (seconds, progress) in enumerate(
            [(1.00, 0.20), (1.01, 0.21), (0.99, 0.19), (1.00, 0.20), (1.00, 0.20)]
        )
    ]
    profile = calibrate_tolerance(calibration)
    baseline = _metric_bundle(
        tmp_path,
        bundle_id="baseline",
        compiled=compiled,
        simulated_seconds=1.0,
        route_progress=0.2,
    )
    passing = _metric_bundle(
        tmp_path,
        bundle_id="passing",
        compiled=compiled,
        simulated_seconds=1.015,
        route_progress=0.215,
    )
    numeric_regression = _metric_bundle(
        tmp_path,
        bundle_id="numeric-regression",
        compiled=compiled,
        simulated_seconds=1.03,
        route_progress=0.23,
    )
    exact_regression = _metric_bundle(
        tmp_path,
        bundle_id="exact-regression",
        compiled=compiled,
        simulated_seconds=1.0,
        route_progress=0.2,
        steps=11,
    )

    pass_report = compare_bundles(baseline, passing, profile)
    numeric_report = compare_bundles(baseline, numeric_regression, profile)
    exact_report = compare_bundles(baseline, exact_regression, profile)

    assert pass_report.status == "pass"
    assert pass_report.exact_differences == ()
    assert pass_report.numeric_differences == ()
    assert numeric_report.status == "regression"
    assert [difference.field for difference in numeric_report.numeric_differences] == [
        "cases/0/route_progress",
        "cases/0/simulated_seconds",
    ]
    assert exact_report.status == "regression"
    assert exact_report.exact_differences[0].field == "cases/0/steps"


def test_incompatible_keys_return_only_incompatible(
    tmp_path: Path,
    scenario_payload: dict[str, object],
    run_request_payload: dict[str, object],
) -> None:
    _, _, compiled = _compiled(scenario_payload, run_request_payload)
    calibration = [
        _metric_bundle(
            tmp_path,
            bundle_id=f"incompatible-profile-{index}",
            compiled=compiled,
            simulated_seconds=1.0,
            route_progress=0.2,
        )
        for index in range(5)
    ]
    profile = calibrate_tolerance(calibration)
    baseline = _metric_bundle(
        tmp_path,
        bundle_id="compatible-baseline",
        compiled=compiled,
        simulated_seconds=1.0,
        route_progress=0.2,
    )
    incompatible = _metric_bundle(
        tmp_path,
        bundle_id="incompatible-candidate",
        compiled=compiled,
        simulated_seconds=10.0,
        route_progress=1.0,
        steps=999,
        verdict="fail",
        effective_config_digest="f" * 64,
    )

    report = compare_bundles(baseline, incompatible, profile)

    assert report.status == "incompatible"
    assert report.incompatibilities == (
        "effective_config_digest",
        "profile.effective_config_digest",
    )
    assert report.exact_differences == ()
    assert report.numeric_differences == ()


def test_compare_attributes_safety_regression_to_sealed_metrics(
    tmp_path: Path,
    scenario_payload: dict[str, object],
    run_request_payload: dict[str, object],
) -> None:
    _, _, compiled = _compiled(scenario_payload, run_request_payload)
    safe_metrics = {
        "minimum_ttc_seconds": 2.0,
        "minimum_headway_seconds": 2.0,
        "event_to_response_latency_seconds": 0.0,
        "collision": False,
        "off_road": False,
        "route_progress": 0.2,
    }
    calibration = [
        _metric_bundle(
            tmp_path,
            bundle_id=f"safety-profile-{index}",
            compiled=compiled,
            simulated_seconds=1.0,
            route_progress=0.2,
            safety_metrics=safe_metrics,
        )
        for index in range(5)
    ]
    profile = calibrate_tolerance(calibration)
    baseline = _metric_bundle(
        tmp_path,
        bundle_id="safety-baseline",
        compiled=compiled,
        simulated_seconds=1.0,
        route_progress=0.2,
        safety_metrics=safe_metrics,
    )
    candidate = _metric_bundle(
        tmp_path,
        bundle_id="safety-candidate",
        compiled=compiled,
        simulated_seconds=1.0,
        route_progress=0.2,
        safety_metrics={**safe_metrics, "collision": True, "minimum_ttc_seconds": 0.1},
        safety_verdict="fail",
    )

    report = compare_bundles(baseline, candidate, profile)

    assert report.status == "regression"
    assert [difference.field for difference in report.exact_differences] == [
        "cases/0/safety/collision",
        "cases/0/safety/safety_verdict",
    ]
    assert report.numeric_differences[0].field == "cases/0/safety/minimum_ttc_seconds"


def test_resimulation_creates_a_new_sealed_bundle_and_compares_it(
    tmp_path: Path,
    scenario_payload: dict[str, object],
    run_request_payload: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario, request, compiled = _compiled(scenario_payload, run_request_payload)
    calibration_outcomes = [
        run_bundle(
            compiled,
            tmp_path,
            run_id=f"resim-profile-{index}",
            fault_plan={0: "success"},
        )
        for index in range(5)
    ]
    profile = calibrate_tolerance([outcome.bundle_path for outcome in calibration_outcomes])
    baseline = calibration_outcomes[0].bundle_path

    def run_fixture(compiled_bundle, output_root, *, run_id=None):
        return run_bundle(
            compiled_bundle,
            output_root,
            run_id=run_id,
            fault_plan={0: "success"},
        )

    monkeypatch.setattr("scenarioforge.oracle.oracle.run_bundle", run_fixture)
    result = resimulate(baseline, scenario, request, tmp_path, profile)

    assert result.outcome.bundle_path != baseline
    assert result.outcome.status == "completed"
    assert result.report.status == "pass"
    assert verify_bundle(result.outcome.bundle_path).bundle_id == result.outcome.run_id


def test_exact_replay_verification_is_read_only_and_never_resimulates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline_manifest = (REAL_REPLAY_BUNDLE / "manifest.json").read_bytes()
    baseline_digest = (REAL_REPLAY_BUNDLE / "bundle.sha256").read_bytes()

    def must_not_run(*args: object, **kwargs: object) -> None:
        raise AssertionError("exact replay verification must not execute a simulation")

    monkeypatch.setattr("scenarioforge.oracle.oracle.run_bundle", must_not_run)
    verification = verify_exact_replay(REAL_REPLAY_BUNDLE)

    assert verification.status == "pass"
    assert verification.bundle_id == "bundle"
    assert verification.manifest_digest == baseline_digest.decode("ascii").split()[0]
    assert verification.replay.execution.metadrive_calls == 0
    assert (REAL_REPLAY_BUNDLE / "manifest.json").read_bytes() == baseline_manifest
    assert (REAL_REPLAY_BUNDLE / "bundle.sha256").read_bytes() == baseline_digest
