from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

from scenarioforge.replay import ReplayBundle
from scenarioforge.runtime import RunOutcome


class _OracleModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class ToleranceProfile(_OracleModel):
    schema_version: Literal["scenarioforge.tolerance-profile.v1"]
    profile_version: Literal[1]
    backend: Literal["metadrive-simulator"]
    backend_version: Literal["0.4.3"]
    scenario_digest: str
    effective_config_digest: str
    ordered_seeds: tuple[int, ...]
    calibration_runs: Literal[5]
    numeric_tolerances: dict[str, float]
    sample_bundle_digests: tuple[str, ...]
    profile_digest: str

    @field_validator("ordered_seeds", "sample_bundle_digests", mode="before")
    @classmethod
    def freeze_sequences(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


class ExactDifference(_OracleModel):
    field: str
    baseline: bool | int | str | None
    candidate: bool | int | str | None


class NumericDifference(_OracleModel):
    field: str
    baseline: float
    candidate: float
    absolute_difference: float
    tolerance: float


class SafetyMetrics(_OracleModel):
    minimum_ttc_seconds: float | None
    minimum_headway_seconds: float | None
    event_to_response_latency_seconds: float | None
    collision: bool
    off_road: bool
    route_progress: float


class SafetyEvidenceCase(_OracleModel):
    case_index: int
    metrics: SafetyMetrics
    safety_constraints: dict[str, bool | float]
    safety_verdict: Literal["pass", "fail"]
    violations: tuple[str, ...]

    @field_validator("violations", mode="before")
    @classmethod
    def freeze_violations(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


class SafetyMetricDefinition(_OracleModel):
    formula_version: str
    formula: str
    unit: str
    missing_value: None


class SafetyEvidence(_OracleModel):
    schema_version: Literal["scenarioforge.safety-evidence.v1"]
    metric_definitions: dict[str, SafetyMetricDefinition]
    cases: tuple[SafetyEvidenceCase, ...]

    @field_validator("cases", mode="before")
    @classmethod
    def freeze_cases(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


class ResimulationReport(_OracleModel):
    schema_version: Literal["scenarioforge.resimulation-report.v1"]
    status: Literal["pass", "regression", "incompatible"]
    baseline_bundle_id: str
    candidate_bundle_id: str
    profile_digest: str
    incompatibilities: tuple[str, ...]
    exact_differences: tuple[ExactDifference, ...]
    numeric_differences: tuple[NumericDifference, ...]


class ExactReplayVerification(_OracleModel):
    schema_version: Literal["scenarioforge.exact-replay-verification.v1"]
    status: Literal["pass"]
    bundle_id: str
    manifest_digest: str
    replay: ReplayBundle


@dataclass(frozen=True)
class ResimulationResult:
    outcome: RunOutcome
    report: ResimulationReport
