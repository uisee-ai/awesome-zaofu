from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from scenarioforge.core.canonical import CanonicalModel, JSONValue, freeze_json
from scenarioforge.runtime.contracts import RunOutcome


SUPPORTED_SEED_PATHS = (
    "$.parameters.initial_gap_m",
    "$.parameters.vehicle_speed_mps",
    "$.parameters.brake_tick",
    "$.parameters.brake_intensity",
)


@dataclass(frozen=True)
class SeedField(CanonicalModel):
    path: str
    choices: tuple[JSONValue, ...]


@dataclass(frozen=True)
class SeedContract(CanonicalModel):
    schema_version: str
    fields: tuple[SeedField, ...]

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SeedContract":
        if set(value) != {"schema_version", "fields"}:
            raise ValueError("SeedContract contains an unknown or missing field")
        if value["schema_version"] != "scenarioforge.seed-contract/v1":
            raise ValueError("unsupported SeedContract schema_version")
        raw_fields = value["fields"]
        if not isinstance(raw_fields, list) or not raw_fields:
            raise ValueError("SeedContract fields must be a non-empty list")
        fields: list[SeedField] = []
        seen: set[str] = set()
        for raw in raw_fields:
            if not isinstance(raw, dict) or set(raw) != {"path", "choices"}:
                raise ValueError("SeedContract field contains an unknown or missing field")
            path = raw["path"]
            choices = raw["choices"]
            if path not in SUPPORTED_SEED_PATHS or path in seen:
                raise ValueError(f"unsupported or duplicate seeded field: {path}")
            if not isinstance(choices, list) or len(choices) < 2:
                raise ValueError("seeded fields require at least two declared choices")
            frozen_choices = freeze_json(choices)
            assert isinstance(frozen_choices, tuple)
            fields.append(SeedField(path=path, choices=frozen_choices))
            seen.add(path)
        return cls(schema_version=str(value["schema_version"]), fields=tuple(fields))


@dataclass(frozen=True)
class CounterfactualSpec(CanonicalModel):
    schema_version: str
    counterfactual_id: str
    kind: str
    expected_change: str
    initial_gap_m: float | None = None

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CounterfactualSpec":
        common = {"schema_version", "counterfactual_id", "kind", "expected_change"}
        if value.get("schema_version") != "scenarioforge.counterfactual/v1":
            raise ValueError("unsupported counterfactual schema_version")
        kind = value.get("kind")
        if kind == "cancel_braking":
            if set(value) != common or value.get("expected_change") != "key_event":
                raise ValueError("cancel_braking must declare only a key_event change")
            gap = None
        elif kind == "increase_initial_gap":
            if set(value) != common | {"initial_gap_m"}:
                raise ValueError("increase_initial_gap has an invalid field set")
            if value.get("expected_change") not in {"key_event", "terminal_result"}:
                raise ValueError("increase_initial_gap must declare a supported expected change")
            gap = float(value["initial_gap_m"])
            if not 1.0 <= gap <= 200.0:
                raise ValueError("initial_gap_m is outside the P0-A contract")
        else:
            raise ValueError(f"unsupported counterfactual kind: {kind}")
        counterfactual_id = value.get("counterfactual_id")
        if not isinstance(counterfactual_id, str) or not counterfactual_id:
            raise ValueError("counterfactual_id must be a non-empty string")
        return cls(
            schema_version=str(value["schema_version"]),
            counterfactual_id=counterfactual_id,
            kind=str(kind),
            expected_change=str(value["expected_change"]),
            initial_gap_m=gap,
        )

    def to_dict(self) -> dict[str, Any]:
        value = {
            "schema_version": self.schema_version,
            "counterfactual_id": self.counterfactual_id,
            "kind": self.kind,
            "expected_change": self.expected_change,
        }
        if self.initial_gap_m is not None:
            value["initial_gap_m"] = self.initial_gap_m
        return value


@dataclass(frozen=True)
class CounterfactualResult(CanonicalModel):
    schema_version: str
    counterfactual_id: str
    kind: str
    expected_change: str
    observed_change: bool
    baseline: Mapping[str, JSONValue]
    variant: Mapping[str, JSONValue]
    passed: bool


@dataclass(frozen=True)
class ToleranceProfile(CanonicalModel):
    schema_version: str
    tolerances_version: str
    position_m: float
    speed_mps: float
    heading_deg: float
    min_ttc_s: float
    completed_steps: int

    @classmethod
    def p0a(cls) -> "ToleranceProfile":
        return cls(
            schema_version="scenarioforge.tolerance-profile/v1",
            tolerances_version="scenarioforge.p0a-tolerances/v1",
            position_m=0.01,
            speed_mps=0.01,
            heading_deg=0.1,
            min_ttc_s=0.05,
            completed_steps=1,
        )


@dataclass(frozen=True)
class ContinuousComparison(CanonicalModel):
    schema_version: str
    aligned_participant_ids: tuple[str, ...]
    aligned_ticks: tuple[int, ...]
    max_deltas: Mapping[str, JSONValue]
    null_ttc_semantics: str
    violations: tuple[Mapping[str, JSONValue], ...]
    passed: bool


@dataclass(frozen=True)
class ImmutableRunReference(CanonicalModel):
    schema_version: str
    run_id: str
    scenario_instance_digest: str
    execution_plan_digest: str
    run_result_digest: str
    artifact_index_digest: str


@dataclass(frozen=True)
class ComparisonReport(CanonicalModel):
    schema_version: str
    comparison_id: str
    run_references: tuple[ImmutableRunReference, ...]
    comparison_scope: Mapping[str, JSONValue]
    excluded_nonsemantic_fields: tuple[str, ...]
    policy_reexecution: Mapping[str, JSONValue]
    discrete: Mapping[str, JSONValue]
    continuous: ContinuousComparison
    tolerances: ToleranceProfile
    passed: bool


@dataclass(frozen=True)
class ReproductionOutcome:
    runs: tuple[RunOutcome, ...]
    report: ComparisonReport


def freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, JSONValue]:
    frozen = freeze_json(value)
    assert isinstance(frozen, Mapping)
    return frozen


def ensure_destination_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
