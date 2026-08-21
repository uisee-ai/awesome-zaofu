from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from scenarioforge.core import (
    ScenarioCompiler,
    canonical_digest,
    instantiate_scenario,
    load_scenario,
)
from scenarioforge.policies import trusted_policy_pair, validate_bound_policy_execution
from scenarioforge.repro import build_regression_case, bind_regression_policy


ROOT = Path(__file__).resolve().parents[2]


def test_regression_case_freezes_every_shared_axis_and_binding_is_the_only_plan_delta() -> None:
    instance = instantiate_scenario(load_scenario(ROOT / "examples" / "p0c" / "brake_lead.json"))
    instance = replace(instance, seed=7)
    bundle = ScenarioCompiler().compile(instance)
    assert bundle.execution_plan is not None
    fingerprint = {
        "schema_version": "scenarioforge.environment-fingerprint/v1",
        "os": "Linux",
        "architecture": "x86_64",
        "python": {"implementation": "CPython", "version": "3.11.15"},
        "simulator": {
            "distribution": "metadrive-simulator",
            "version": "0.4.3",
            "asset_version": "0.4.3",
            "asset_digest": "a" * 64,
        },
        "rendering": {"headless": True, "gpu_required": False},
        "dependency_lock": {"format": "uv.lock", "digest": "b" * 64},
    }
    case = build_regression_case(
        bundle,
        preset_id="brake_lead",
        environment_fingerprint=fingerprint,
    )
    baseline_binding, candidate_binding = trusted_policy_pair(
        bundle.execution_plan.policy["config"]
    )
    baseline_bundle = bind_regression_policy(bundle, baseline_binding)
    candidate_bundle = bind_regression_policy(bundle, candidate_binding)

    assert case.case_id == "brake_lead-seed-7"
    assert case.seed == 7
    assert case.scenario_revision_digest == instance.source_spec_digest
    assert case.assets_digest != case.environment_digest
    assert baseline_bundle.scenario_instance is bundle.scenario_instance
    assert candidate_bundle.scenario_instance is bundle.scenario_instance
    assert baseline_bundle.report is bundle.report
    assert candidate_bundle.report is bundle.report
    assert baseline_bundle.scenario_instance.digest == candidate_bundle.scenario_instance.digest

    baseline_plan = baseline_bundle.execution_plan.to_dict()
    candidate_plan = candidate_bundle.execution_plan.to_dict()
    baseline_policy, observed_baseline = validate_bound_policy_execution(
        baseline_plan.pop("policy")
    )
    candidate_policy, observed_candidate = validate_bound_policy_execution(
        candidate_plan.pop("policy")
    )
    assert baseline_plan == candidate_plan
    assert baseline_policy == candidate_policy
    assert canonical_digest(baseline_policy) == canonical_digest(
        bundle.execution_plan.policy
    )
    assert observed_baseline == baseline_binding
    assert observed_candidate == candidate_binding
