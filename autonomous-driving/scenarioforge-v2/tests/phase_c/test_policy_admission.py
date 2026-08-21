from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from scenarioforge.core import canonical_digest
from scenarioforge.policies import (
    BASELINE_POLICY_ID,
    BASELINE_POLICY_VERSION,
    CANDIDATE_POLICY_ID,
    CANDIDATE_POLICY_VERSION,
    PolicyAdmissionError,
    admit_policy_pair,
    bind_policy_execution,
    policy_contract,
    trusted_policy_pair,
)


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_FIXTURE = ROOT / "tests" / "fixtures" / "p0-continuation" / "policy-contract.json"


def _baseline_config() -> dict[str, object]:
    return {
        "default_action": {"steering": 0.0, "throttle_brake": 0.0},
        "participant_actions": [
            {"participant_id": "ego", "steering": 0.0, "throttle_brake": 0.0},
            {"participant_id": "lead", "steering": 0.0, "throttle_brake": 0.0},
        ],
    }


def test_policy_contract_is_the_complete_golden_contract() -> None:
    golden = json.loads(CONTRACT_FIXTURE.read_text(encoding="utf-8"))

    assert policy_contract() == golden
    assert golden["ordered_policy_identities"] == [
        "scenarioforge.deterministic-control@2.0.0",
        "scenarioforge.defensive-control@1.0.0",
    ]
    assert golden["candidate_config"] == {"profile": "defensive-v1"}
    assert golden["candidate_constants"] == {
        "nominal_target_speed_scale": 1.0,
        "desired_time_headway_s": 2.0,
        "minimum_gap_m": 5.0,
        "ttc_brake_threshold_s": 3.0,
        "maximum_brake_command": 1.0,
        "release_hysteresis_s": 0.5,
    }


def test_trusted_pair_locks_every_identity_schema_config_constant_and_code_axis() -> None:
    baseline, candidate = trusted_policy_pair(_baseline_config())

    assert (baseline.role, baseline.id, baseline.version) == (
        "baseline",
        BASELINE_POLICY_ID,
        BASELINE_POLICY_VERSION,
    )
    assert (candidate.role, candidate.id, candidate.version) == (
        "candidate",
        CANDIDATE_POLICY_ID,
        CANDIDATE_POLICY_VERSION,
    )
    for binding in (baseline, candidate):
        value = binding.to_dict()
        assert set(value) == {
            "schema_version",
            "role",
            "id",
            "version",
            "provider",
            "config_schema",
            "config_schema_digest",
            "config",
            "configuration_digest",
            "constants",
            "constants_digest",
            "implementation_code_digest",
            "dynamic_code",
            "network_access",
            "runtime_override",
        }
        assert value["config_schema_digest"] == canonical_digest(value["config_schema"])
        assert value["configuration_digest"] == canonical_digest(value["config"])
        assert value["constants_digest"] == canonical_digest(value["constants"])
        assert len(value["implementation_code_digest"]) == 64
        assert set(value["implementation_code_digest"]) <= set("0123456789abcdef")
        assert value["provider"] == "scenarioforge.builtin-policy/v1"
        assert value["dynamic_code"] is False
        assert value["network_access"] is False
        assert value["runtime_override"] is False

    assert admit_policy_pair((baseline, candidate)) == (baseline, candidate)


@pytest.mark.parametrize(
    "mutation",
    [
        "identical",
        "reversed",
        "unknown",
        "config_digest",
        "schema_digest",
        "constants_digest",
        "code_digest",
        "dynamic",
        "network",
        "override",
        "provider",
        "candidate_config",
    ],
)
def test_admission_fails_closed_for_every_untrusted_binding_axis(mutation: str) -> None:
    baseline, candidate = trusted_policy_pair(_baseline_config())
    pair = (baseline, candidate)
    if mutation == "identical":
        pair = (baseline, baseline)
    elif mutation == "reversed":
        pair = (candidate, baseline)
    elif mutation == "unknown":
        pair = (baseline, replace(candidate, id="third.party.policy"))
    elif mutation == "config_digest":
        pair = (baseline, replace(candidate, configuration_digest="0" * 64))
    elif mutation == "schema_digest":
        pair = (baseline, replace(candidate, config_schema_digest="0" * 64))
    elif mutation == "constants_digest":
        pair = (baseline, replace(candidate, constants_digest="0" * 64))
    elif mutation == "code_digest":
        pair = (baseline, replace(candidate, implementation_code_digest="0" * 64))
    elif mutation == "dynamic":
        pair = (baseline, replace(candidate, dynamic_code=True))
    elif mutation == "network":
        pair = (baseline, replace(candidate, network_access=True))
    elif mutation == "override":
        pair = (baseline, replace(candidate, runtime_override=True))
    elif mutation == "provider":
        pair = (baseline, replace(candidate, provider="https://policy.invalid"))
    elif mutation == "candidate_config":
        pair = (
            baseline,
            replace(
                candidate,
                config={"profile": "defensive-v1", "extra": True},
                configuration_digest=canonical_digest(
                    {"profile": "defensive-v1", "extra": True}
                ),
            ),
        )

    with pytest.raises(PolicyAdmissionError):
        admit_policy_pair(pair)


def test_bound_execution_is_exact_and_rejects_a_binding_for_another_baseline_config() -> None:
    baseline_policy = {
        "schema_version": "scenarioforge.deterministic-policy/v2",
        "id": BASELINE_POLICY_ID,
        "version": BASELINE_POLICY_VERSION,
        "determinism": {
            "fixed_seed_required": True,
            "decision_order": "participant_order",
            "floating_point_contract": "backend_bound",
        },
        "config": _baseline_config(),
    }
    baseline, candidate = trusted_policy_pair(_baseline_config())

    assert bind_policy_execution(baseline_policy, candidate) == {
        "schema_version": "scenarioforge.bound-policy-execution/v1",
        "baseline_policy": baseline_policy,
        "binding": candidate.to_dict(),
    }
    mismatched = dict(baseline_policy)
    mismatched["config"] = {
        "default_action": {"steering": 0.0, "throttle_brake": 0.1},
        "participant_actions": [],
    }
    with pytest.raises(PolicyAdmissionError):
        bind_policy_execution(mismatched, baseline)
