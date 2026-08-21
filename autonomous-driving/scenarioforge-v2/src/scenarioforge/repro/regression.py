from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping, Sequence

from scenarioforge.core import canonical_digest, strict_loads
from scenarioforge.core.canonical import CanonicalModel, JSONValue, freeze_json
from scenarioforge.core.models import CompileBundle
from scenarioforge.policies import (
    PolicyBinding,
    admit_policy_pair,
    bind_policy_execution,
    policy_contract,
    planned_defensive_response_tick,
    validate_bound_policy_execution,
)
from scenarioforge.runtime.contracts import RunOutcome


_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_PRESETS = (
    "construction_merge",
    "highway_merge",
    "brake_lead",
    "dangerous_cut_in",
    "unprotected_left_turn",
)
_SEEDS = (7, 8, 9)
_SHARED_PAIR_AXES = (
    "world_instance_digest",
    "scenario_revision_digest",
    "seed",
    "assets_digest",
    "environment_digest",
    "resource_config_digest",
    "metric_definitions_digest",
    "tolerances_digest",
    "route_digest",
    "nominal_speed_digest",
)
_BLOCKING_CONDITIONS = (
    "new_collision",
    "success_to_failure",
    "success_rate_decline",
    "threshold_transition",
    "minimum_ttc_regression",
    "completion_time_regression",
    "hard_braking_regression",
    "route_changed",
    "nominal_speed_changed",
    "scenario_priority_changed",
    "defensive_response_not_earlier",
)
_METRICS = ("minimum_ttc", "completion_time", "hard_braking")


class RegressionContractError(ValueError):
    pass


def _digest(value: str, field: str) -> None:
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        raise RegressionContractError(f"{field} must be a locked SHA-256 digest")


def _finite_optional(value: Any, field: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RegressionContractError(f"{field} must be numeric or null")
    number = float(value)
    if not math.isfinite(number):
        raise RegressionContractError(f"{field} must be finite")
    return number


def _rounded(value: float) -> float:
    return round(value, 12)


@dataclass(frozen=True)
class P0MatrixSpec(CanonicalModel):
    schema_version: str
    presets: tuple[str, ...]
    policy_order: tuple[str, ...]
    seeds: tuple[int, ...]
    pair_count: int
    real_child_runs: int
    statistical_significance_claimed: bool

    @classmethod
    def p0(cls) -> "P0MatrixSpec":
        identities = policy_contract()["ordered_policy_identities"]
        return cls(
            schema_version="scenarioforge.regression-matrix/v1",
            presets=_PRESETS,
            policy_order=tuple(str(item) for item in identities),
            seeds=_SEEDS,
            pair_count=15,
            real_child_runs=30,
            statistical_significance_claimed=False,
        )


@dataclass(frozen=True)
class RegressionThresholds(CanonicalModel):
    schema_version: str
    minimum_ttc_drop_s: float
    completion_time_increase_s: float
    hard_braking_decrease_mps2: float

    @classmethod
    def p0(cls) -> "RegressionThresholds":
        return cls(
            schema_version="scenarioforge.regression-thresholds/v1",
            minimum_ttc_drop_s=0.05,
            completion_time_increase_s=1.0,
            hard_braking_decrease_mps2=0.05,
        )


@dataclass(frozen=True)
class RegressionCase(CanonicalModel):
    schema_version: str
    case_id: str
    preset_id: str
    seed: int
    world_instance_digest: str
    scenario_revision_digest: str
    assets_digest: str
    environment_digest: str
    resource_config_digest: str
    metric_definitions_digest: str
    tolerances_digest: str
    route_digest: str
    nominal_speed_digest: str

    def validate(self) -> None:
        if self.schema_version != "scenarioforge.regression-case/v1":
            raise RegressionContractError("unsupported RegressionCase schema_version")
        if self.preset_id not in _PRESETS:
            raise RegressionContractError("RegressionCase preset is not frozen")
        if self.seed not in _SEEDS:
            raise RegressionContractError("RegressionCase Seed is not frozen")
        if self.case_id != f"{self.preset_id}-seed-{self.seed}":
            raise RegressionContractError("RegressionCase identity is not canonical")
        for field in _SHARED_PAIR_AXES:
            if field == "seed":
                continue
            _digest(str(getattr(self, field)), field)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RegressionCase":
        fields = {
            "schema_version",
            "case_id",
            "preset_id",
            "seed",
            "world_instance_digest",
            "scenario_revision_digest",
            "assets_digest",
            "environment_digest",
            "resource_config_digest",
            "metric_definitions_digest",
            "tolerances_digest",
            "route_digest",
            "nominal_speed_digest",
        }
        if set(value) != fields:
            raise RegressionContractError("RegressionCase has an unknown or missing field")
        if isinstance(value["seed"], bool) or not isinstance(value["seed"], int):
            raise RegressionContractError("RegressionCase Seed must be an integer")
        case = cls(**{field: value[field] for field in fields})
        case.validate()
        return case


@dataclass(frozen=True)
class PolicyRunSample(CanonicalModel):
    schema_version: str
    case_digest: str
    run_id: str
    attempt_id: str
    policy_binding: PolicyBinding
    world_instance_digest: str
    route_digest: str
    nominal_speed_digest: str
    collision: bool
    success: bool
    scenario_outcome: str
    metrics: Mapping[str, JSONValue]
    earliest_brake_tick: int | None
    scenario_override_digest: str
    run_result_digest: str
    artifact_index_digest: str

    def __post_init__(self) -> None:
        frozen = freeze_json(self.metrics)
        assert isinstance(frozen, Mapping)
        object.__setattr__(self, "metrics", frozen)

    def validate(self) -> None:
        if self.schema_version != "scenarioforge.policy-run-sample/v1":
            raise RegressionContractError("unsupported PolicyRunSample schema_version")
        for field in (
            "case_digest",
            "world_instance_digest",
            "route_digest",
            "nominal_speed_digest",
            "scenario_override_digest",
            "run_result_digest",
            "artifact_index_digest",
        ):
            _digest(str(getattr(self, field)), field)
        if not self.run_id or not self.attempt_id:
            raise RegressionContractError("PolicyRunSample run identity is missing")
        if set(self.metrics) != set(_METRICS):
            raise RegressionContractError("PolicyRunSample metrics are incomplete")
        for metric in _METRICS:
            item = self.metrics[metric]
            if not isinstance(item, Mapping) or set(item) != {
                "definition_id",
                "unit",
                "value",
                "threshold",
                "threshold_met",
                "null_semantics",
            }:
                raise RegressionContractError(f"{metric} evidence is incomplete")
            _finite_optional(item["value"], f"{metric}.value")
            if item["threshold_met"] not in {None, False, True}:
                raise RegressionContractError(f"{metric}.threshold_met is invalid")
        if self.earliest_brake_tick is not None and (
            isinstance(self.earliest_brake_tick, bool)
            or not isinstance(self.earliest_brake_tick, int)
            or self.earliest_brake_tick < 0
        ):
            raise RegressionContractError("earliest brake tick is invalid")

    @classmethod
    def from_outcome(
        cls,
        case: RegressionCase,
        outcome: RunOutcome,
    ) -> "PolicyRunSample":
        plan = outcome.bundle.execution_plan
        if plan is None:
            raise RegressionContractError("policy sample requires an execution plan")
        _, binding = validate_bound_policy_execution(plan.policy)
        if _world_instance_digest(outcome.bundle) != case.world_instance_digest:
            raise RegressionContractError("run outcome does not match the frozen world")
        if _route_digest(outcome.bundle) != case.route_digest:
            raise RegressionContractError("run outcome changed the frozen route")
        if _nominal_speed_digest(outcome.bundle) != case.nominal_speed_digest:
            raise RegressionContractError("run outcome changed nominal target speed")

        actions = _read_json(outcome.published_path / "output" / "actions.json")
        metrics = _read_json(outcome.published_path / "output" / "metrics.json")
        if not isinstance(actions, list) or not isinstance(metrics, Mapping):
            raise RegressionContractError("run outcome evidence has an invalid shape")
        ego_ids = {
            str(participant["id"])
            for participant in plan.participants
            if participant["role"] == "ego"
        }
        if binding.role == "candidate":
            response_tick = planned_defensive_response_tick(plan.to_dict())
            if response_tick is not None and not any(
                int(record["tick"]) == response_tick
                and str(record["participant_id"]) in ego_ids
                and record["source"] == "policy"
                and float(record["policy_action"]["throttle_brake"]) < -1e-6
                for record in actions
            ):
                raise RegressionContractError(
                    "candidate did not emit its evidence-bound defensive response"
                )
        else:
            ego_brake_ticks = sorted(
                int(event["trigger"]["tick"])
                for event in plan.events
                if str(event["participant_id"]) in ego_ids
                and float(event["action"]["throttle_brake"]) < 0.0
            )
            event_ticks = sorted(
                int(event["trigger"]["tick"])
                for event in plan.events
                if event["trigger"]["kind"] == "tick"
            )
            response_tick = (
                ego_brake_ticks[0]
                if ego_brake_ticks
                else (event_ticks[0] if event_ticks else None)
            )
        overrides = [
            {
                "tick": int(record["tick"]),
                "participant_id": str(record["participant_id"]),
                "final_action": record["final_action"],
            }
            for record in actions
            if record["source"] == "scenario_override"
        ]
        metric_values = metrics.get("metric_values")
        if not isinstance(metric_values, list):
            raise RegressionContractError("run outcome lacks metric values")
        selected: dict[str, Any] = {}
        for item in metric_values:
            if not isinstance(item, Mapping) or item.get("metric") not in _METRICS:
                continue
            name = str(item["metric"])
            selected[name] = {
                "definition_id": item["definition_id"],
                "unit": item["unit"],
                "value": item["value"],
                "threshold": item["threshold"],
                "threshold_met": item["threshold_met"],
                "null_semantics": item["null_semantics"],
            }
        sample = cls(
            schema_version="scenarioforge.policy-run-sample/v1",
            case_digest=case.digest,
            run_id=outcome.run_result.run_id,
            attempt_id=outcome.run_result.attempt_id,
            policy_binding=binding,
            world_instance_digest=case.world_instance_digest,
            route_digest=case.route_digest,
            nominal_speed_digest=case.nominal_speed_digest,
            collision=bool(metrics["collision"]),
            success=(
                metrics.get("execution_status") == "completed"
                and not bool(metrics["collision"])
            ),
            scenario_outcome=str(metrics["scenario_outcome"]),
            metrics=selected,
            earliest_brake_tick=response_tick,
            scenario_override_digest=canonical_digest(overrides),
            run_result_digest=_file_digest(
                outcome.published_path / "run_result.json"
            ),
            artifact_index_digest=_file_digest(
                outcome.published_path / "artifact_index.json"
            ),
        )
        sample.validate()
        return sample


@dataclass(frozen=True)
class PairedRegressionReport(CanonicalModel):
    schema_version: str
    case: RegressionCase
    baseline: PolicyRunSample
    candidate: PolicyRunSample
    thresholds: RegressionThresholds
    metric_deltas: Mapping[str, JSONValue]
    violations: tuple[str, ...]
    passed: bool


@dataclass(frozen=True)
class RegressionMatrixReport(CanonicalModel):
    schema_version: str
    matrix: P0MatrixSpec
    pairs: tuple[PairedRegressionReport, ...]
    pair_count: int
    real_child_runs: int
    baseline_success_count: int
    candidate_success_count: int
    baseline_success_rate: float
    candidate_success_rate: float
    violations: tuple[str, ...]
    statistical_significance_claimed: bool
    passed: bool


def _metric(sample: PolicyRunSample, name: str) -> Mapping[str, Any]:
    item = sample.metrics[name]
    if not isinstance(item, Mapping):
        raise RegressionContractError(f"{name} metric is invalid")
    return item


def _delta(
    baseline: PolicyRunSample,
    candidate: PolicyRunSample,
    name: str,
) -> float | None:
    baseline_value = _finite_optional(_metric(baseline, name)["value"], name)
    candidate_value = _finite_optional(_metric(candidate, name)["value"], name)
    if baseline_value is None or candidate_value is None:
        return None
    return _rounded(candidate_value - baseline_value)


def compare_policy_pair(
    case: RegressionCase,
    baseline: PolicyRunSample,
    candidate: PolicyRunSample,
    thresholds: RegressionThresholds | None = None,
) -> PairedRegressionReport:
    case.validate()
    baseline.validate()
    candidate.validate()
    if baseline.case_digest != case.digest or candidate.case_digest != case.digest:
        raise RegressionContractError("policy sample is bound to a stale RegressionCase")
    if (
        baseline.world_instance_digest != case.world_instance_digest
        or candidate.world_instance_digest != case.world_instance_digest
    ):
        raise RegressionContractError("policy samples do not share the frozen world")
    try:
        admit_policy_pair((baseline.policy_binding, candidate.policy_binding))
    except ValueError as error:
        raise RegressionContractError("policy samples are not the admitted ordered pair") from error

    profile = RegressionThresholds.p0() if thresholds is None else thresholds
    metric_deltas = {
        "minimum_ttc_s": _delta(baseline, candidate, "minimum_ttc"),
        "completion_time_s": _delta(baseline, candidate, "completion_time"),
        "hard_braking_mps2": _delta(baseline, candidate, "hard_braking"),
    }
    violations: list[str] = []
    if not baseline.collision and candidate.collision:
        violations.append("new_collision")
    if baseline.success and not candidate.success:
        violations.append("success_to_failure")
    for metric in _METRICS:
        if (
            _metric(baseline, metric)["threshold_met"] is not True
            and _metric(candidate, metric)["threshold_met"] is True
        ):
            violations.append(f"threshold_transition:{metric}")
    minimum_ttc_delta = metric_deltas["minimum_ttc_s"]
    if (
        minimum_ttc_delta is not None
        and float(minimum_ttc_delta) < -profile.minimum_ttc_drop_s - 1e-12
    ):
        violations.append("minimum_ttc_regression")
    completion_delta = metric_deltas["completion_time_s"]
    if (
        completion_delta is not None
        and float(completion_delta) > profile.completion_time_increase_s + 1e-12
    ):
        violations.append("completion_time_regression")
    braking_delta = metric_deltas["hard_braking_mps2"]
    if (
        braking_delta is not None
        and float(braking_delta) < -profile.hard_braking_decrease_mps2 - 1e-12
    ):
        violations.append("hard_braking_regression")
    if baseline.route_digest != case.route_digest or candidate.route_digest != case.route_digest:
        violations.append("route_changed")
    if (
        baseline.nominal_speed_digest != case.nominal_speed_digest
        or candidate.nominal_speed_digest != case.nominal_speed_digest
    ):
        violations.append("nominal_speed_changed")
    if baseline.scenario_override_digest != candidate.scenario_override_digest:
        violations.append("scenario_priority_changed")
    if candidate.earliest_brake_tick is None or (
        baseline.earliest_brake_tick is not None
        and candidate.earliest_brake_tick >= baseline.earliest_brake_tick
    ):
        violations.append("defensive_response_not_earlier")

    frozen_deltas = freeze_json(metric_deltas)
    assert isinstance(frozen_deltas, Mapping)
    return PairedRegressionReport(
        schema_version="scenarioforge.paired-regression/v1",
        case=case,
        baseline=baseline,
        candidate=candidate,
        thresholds=profile,
        metric_deltas=frozen_deltas,
        violations=tuple(violations),
        passed=not violations,
    )


def compare_regression_matrix(
    pairs: Sequence[PairedRegressionReport],
    matrix: P0MatrixSpec | None = None,
) -> RegressionMatrixReport:
    spec = P0MatrixSpec.p0() if matrix is None else matrix
    expected = {
        (preset_id, seed)
        for preset_id in spec.presets
        for seed in spec.seeds
    }
    observed = [(pair.case.preset_id, pair.case.seed) for pair in pairs]
    if len(pairs) != spec.pair_count or set(observed) != expected or len(set(observed)) != len(observed):
        raise RegressionContractError("regression matrix is not the exact 5x2x3 contract")

    baseline_success_count = sum(pair.baseline.success for pair in pairs)
    candidate_success_count = sum(pair.candidate.success for pair in pairs)
    violations = [
        f"pair:{pair.case.case_id}:{violation}"
        for pair in pairs
        for violation in pair.violations
    ]
    if candidate_success_count < baseline_success_count:
        violations.append("success_rate_decline")
    pair_count = len(pairs)
    baseline_rate = baseline_success_count / pair_count
    candidate_rate = candidate_success_count / pair_count
    return RegressionMatrixReport(
        schema_version="scenarioforge.regression-matrix-report/v1",
        matrix=spec,
        pairs=tuple(pairs),
        pair_count=pair_count,
        real_child_runs=pair_count * 2,
        baseline_success_count=baseline_success_count,
        candidate_success_count=candidate_success_count,
        baseline_success_rate=baseline_rate,
        candidate_success_rate=candidate_rate,
        violations=tuple(violations),
        statistical_significance_claimed=False,
        passed=not violations,
    )


def _read_json(path: Path) -> Any:
    return strict_loads(path.read_bytes())


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _world_instance_digest(bundle: CompileBundle) -> str:
    value = bundle.scenario_instance.to_dict()
    value.pop("policy")
    return canonical_digest(value)


def _route_digest(bundle: CompileBundle) -> str:
    plan = bundle.execution_plan
    if plan is None:
        raise RegressionContractError("RegressionCase requires an execution plan")
    return canonical_digest(
        [
            {"participant_id": participant["id"], "route": participant["route"]}
            for participant in plan.participants
        ]
    )


def _nominal_speed_digest(bundle: CompileBundle) -> str:
    plan = bundle.execution_plan
    if plan is None:
        raise RegressionContractError("RegressionCase requires an execution plan")
    return canonical_digest(
        [
            {
                "participant_id": participant["id"],
                "nominal_target_speed_mps": participant["spawn"]["speed_mps"],
            }
            for participant in plan.participants
        ]
    )


def build_regression_case(
    bundle: CompileBundle,
    *,
    preset_id: str,
    environment_fingerprint: Mapping[str, Any],
) -> RegressionCase:
    plan = bundle.execution_plan
    if plan is None or plan.schema_version != "scenarioforge.execution-plan/v2":
        raise RegressionContractError("RegressionCase requires an exact v2 plan")
    if preset_id != bundle.scenario_instance.scenario_id:
        raise RegressionContractError("preset identity does not match ScenarioInstance")
    expected_fingerprint_fields = {
        "schema_version",
        "os",
        "architecture",
        "python",
        "simulator",
        "rendering",
        "dependency_lock",
    }
    if set(environment_fingerprint) != expected_fingerprint_fields:
        raise RegressionContractError("environment fingerprint is incomplete")
    simulator = environment_fingerprint["simulator"]
    if not isinstance(simulator, Mapping):
        raise RegressionContractError("simulator fingerprint is missing")
    case = RegressionCase(
        schema_version="scenarioforge.regression-case/v1",
        case_id=f"{preset_id}-seed-{bundle.scenario_instance.seed}",
        preset_id=preset_id,
        seed=bundle.scenario_instance.seed,
        world_instance_digest=_world_instance_digest(bundle),
        scenario_revision_digest=(
            bundle.scenario_instance.revision_digest
            or bundle.scenario_instance.source_spec_digest
        ),
        assets_digest=canonical_digest(simulator),
        environment_digest=canonical_digest(environment_fingerprint),
        resource_config_digest=canonical_digest(plan.resource_config),
        metric_definitions_digest=canonical_digest(
            plan.constraints["metric_definitions"]
        ),
        tolerances_digest=canonical_digest(
            {"tolerances_version": plan.tolerances_version}
        ),
        route_digest=_route_digest(bundle),
        nominal_speed_digest=_nominal_speed_digest(bundle),
    )
    case.validate()
    return case


def bind_regression_policy(
    bundle: CompileBundle,
    binding: PolicyBinding,
) -> CompileBundle:
    plan = bundle.execution_plan
    if plan is None or plan.schema_version != "scenarioforge.execution-plan/v2":
        raise RegressionContractError("policy binding requires an exact v2 plan")
    bound_policy = freeze_json(bind_policy_execution(plan.policy, binding))
    assert isinstance(bound_policy, Mapping)
    return replace(bundle, execution_plan=replace(plan, policy=bound_policy))


def regression_contract() -> dict[str, Any]:
    return {
        "schema_version": "scenarioforge.p0-regression-contract/v1",
        "matrix": P0MatrixSpec.p0().to_dict(),
        "thresholds": RegressionThresholds.p0().to_dict(),
        "shared_pair_axes": list(_SHARED_PAIR_AXES),
        "blocking_conditions": list(_BLOCKING_CONDITIONS),
    }
