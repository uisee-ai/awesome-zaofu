from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from scenarioforge.core.canonical import (
    CanonicalModel,
    JSONValue,
    canonical_digest,
    freeze_json,
    thaw_json,
)
from scenarioforge.core.models import CompileBundle


_PUBLIC_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_AGENT_ROLES = frozenset({"ego", "controlled", "social_vehicle", "pedestrian"})


def _require_schema(actual: str, expected: str) -> None:
    if actual != expected:
        raise ValueError(f"schema_version must be {expected}")


def _require_id(value: str, label: str) -> None:
    if not _PUBLIC_ID.fullmatch(value):
        raise ValueError(f"{label} is invalid")


def _require_tick(value: int) -> None:
    if isinstance(value, bool) or value < 0:
        raise ValueError("tick must be a non-negative integer")


def _require_finite(value: float, label: str) -> None:
    if isinstance(value, bool) or not math.isfinite(value):
        raise ValueError(f"{label} must be finite")


def _freeze_mapping(value: Mapping[str, Any], label: str) -> Mapping[str, JSONValue]:
    frozen = freeze_json(value)
    if not isinstance(frozen, Mapping):
        raise TypeError(f"{label} must be a JSON object")
    return frozen


@dataclass(frozen=True)
class AdapterDescriptor(CanonicalModel):
    schema_version: str
    adapter_id: str
    adapter_version: str
    adapter_digest: str

    def __post_init__(self) -> None:
        _require_schema(self.schema_version, "scenarioforge.adapter-descriptor/v1")
        _require_id(self.adapter_id, "adapter_id")
        if not self.adapter_version:
            raise ValueError("adapter_version is required")
        if not _DIGEST.fullmatch(self.adapter_digest):
            raise ValueError("adapter_digest must be a sha256 digest")


@dataclass(frozen=True)
class Observation(CanonicalModel):
    schema_version: str
    agent_id: str
    role: str
    tick: int
    values: Mapping[str, JSONValue]

    def __post_init__(self) -> None:
        _require_schema(self.schema_version, "scenarioforge.observation/v1")
        _require_id(self.agent_id, "agent_id")
        if self.role not in _AGENT_ROLES:
            raise ValueError("role is unsupported")
        _require_tick(self.tick)
        object.__setattr__(self, "values", _freeze_mapping(self.values, "values"))


@dataclass(frozen=True)
class Action(CanonicalModel):
    schema_version: str
    agent_id: str
    tick: int
    values: Mapping[str, JSONValue]

    def __post_init__(self) -> None:
        _require_schema(self.schema_version, "scenarioforge.action/v1")
        _require_id(self.agent_id, "agent_id")
        _require_tick(self.tick)
        object.__setattr__(self, "values", _freeze_mapping(self.values, "values"))


@dataclass(frozen=True)
class Reward(CanonicalModel):
    schema_version: str
    agent_id: str
    tick: int
    value: float
    components: Mapping[str, float]

    def __post_init__(self) -> None:
        _require_schema(self.schema_version, "scenarioforge.reward/v1")
        _require_id(self.agent_id, "agent_id")
        _require_tick(self.tick)
        _require_finite(self.value, "reward")
        components = dict(self.components)
        if any(not isinstance(key, str) or not key for key in components):
            raise ValueError("reward component names must be non-empty strings")
        for component, value in components.items():
            _require_finite(value, f"reward component {component}")
        object.__setattr__(self, "components", _freeze_mapping(components, "components"))


@dataclass(frozen=True)
class Termination(CanonicalModel):
    schema_version: str
    agent_id: str
    tick: int
    terminated: bool
    truncated: bool
    reason: str

    def __post_init__(self) -> None:
        _require_schema(self.schema_version, "scenarioforge.termination/v1")
        _require_id(self.agent_id, "agent_id")
        _require_tick(self.tick)
        if not isinstance(self.terminated, bool) or not isinstance(self.truncated, bool):
            raise TypeError("termination flags must be booleans")
        if not self.reason:
            raise ValueError("termination reason is required")


@dataclass(frozen=True)
class TrajectorySample(CanonicalModel):
    schema_version: str
    agent_id: str
    role: str
    tick: int
    position_m: tuple[float, float, float]
    heading_deg: float
    speed_mps: float
    values: Mapping[str, JSONValue]

    def __post_init__(self) -> None:
        _require_schema(self.schema_version, "scenarioforge.trajectory-sample/v1")
        _require_id(self.agent_id, "agent_id")
        if self.role not in _AGENT_ROLES:
            raise ValueError("role is unsupported")
        _require_tick(self.tick)
        if len(self.position_m) != 3:
            raise ValueError("position_m must contain exactly three coordinates")
        for coordinate in self.position_m:
            _require_finite(coordinate, "position coordinate")
        _require_finite(self.heading_deg, "heading_deg")
        _require_finite(self.speed_mps, "speed_mps")
        object.__setattr__(self, "position_m", tuple(self.position_m))
        object.__setattr__(self, "values", _freeze_mapping(self.values, "values"))


@dataclass(frozen=True)
class AdapterStep(CanonicalModel):
    schema_version: str
    tick: int
    observations: tuple[Observation, ...]
    actions: tuple[Action, ...]
    rewards: tuple[Reward, ...]
    terminations: tuple[Termination, ...]
    trajectory: tuple[TrajectorySample, ...]

    def __post_init__(self) -> None:
        _require_schema(self.schema_version, "scenarioforge.adapter-step/v1")
        _require_tick(self.tick)
        groups = (
            self.observations,
            self.actions,
            self.rewards,
            self.terminations,
            self.trajectory,
        )
        if any(item.tick != self.tick for group in groups for item in group):
            raise ValueError("adapter step members must bind the same tick")


@dataclass(frozen=True)
class RunRequest(CanonicalModel):
    schema_version: str
    run_id: str
    attempt_id: str
    input_snapshot_ref: str
    input_snapshot_digest: str
    run_manifest_digest: str
    execution_plan_digest: str


@dataclass(frozen=True)
class ArtifactEntry:
    path: str
    status: str
    size_bytes: int
    digest: str
    validation: str

    def to_dict(self) -> dict[str, str | int]:
        return {
            "path": self.path,
            "status": self.status,
            "size_bytes": self.size_bytes,
            "digest": self.digest,
            "validation": self.validation,
        }


@dataclass(frozen=True)
class ArtifactIndex(CanonicalModel):
    schema_version: str
    run_id: str
    attempt_id: str
    artifacts: tuple[ArtifactEntry, ...]
    run_manifest_digest: str | None = None
    execution_status: str | None = None
    scenario_outcome: str | None = None
    termination_reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        legacy: dict[str, object] = {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "attempt_id": self.attempt_id,
            "artifacts": [entry.to_dict() for entry in self.artifacts],
        }
        if self.schema_version == "scenarioforge.artifact-index/v1":
            return legacy
        if None in {
            self.run_manifest_digest,
            self.execution_status,
            self.scenario_outcome,
            self.termination_reason,
        }:
            raise ValueError("v2 ArtifactIndex requires complete terminal bindings")
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "attempt_id": self.attempt_id,
            "run_manifest_digest": self.run_manifest_digest,
            "execution_status": self.execution_status,
            "scenario_outcome": self.scenario_outcome,
            "termination_reason": self.termination_reason,
            "artifacts": [entry.to_dict() for entry in self.artifacts],
        }


@dataclass(frozen=True)
class RunResult(CanonicalModel):
    schema_version: str
    run_id: str
    attempt_id: str
    status: str
    reason: str
    worker_exit_code: int
    run_manifest_digest: str
    compile_report_digest: str
    execution_plan_digest: str
    artifact_index_digest: str
    execution_status: str | None = None
    scenario_outcome: str | None = None
    termination_reason: str | None = None
    traceability_digest: str | None = None
    scenario_revision_digest: str | None = None
    control_command: Mapping[str, Any] | None = None
    process_tree_cleanup: Mapping[str, Any] | None = None
    statistics_eligible: bool | None = None

    def to_dict(self) -> dict[str, object]:
        common: dict[str, object] = {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "attempt_id": self.attempt_id,
        }
        digests = {
            "worker_exit_code": self.worker_exit_code,
            "run_manifest_digest": self.run_manifest_digest,
            "compile_report_digest": self.compile_report_digest,
            "execution_plan_digest": self.execution_plan_digest,
            "artifact_index_digest": self.artifact_index_digest,
        }
        if self.schema_version == "scenarioforge.run-result/v1":
            return {**common, "status": self.status, "reason": self.reason, **digests}
        if None in {
            self.execution_status,
            self.scenario_outcome,
            self.termination_reason,
        }:
            raise ValueError("v2 RunResult requires all terminal axes")
        terminal = {
            **common,
            "execution_status": self.execution_status,
            "scenario_outcome": self.scenario_outcome,
            "termination_reason": self.termination_reason,
            **digests,
        }
        if self.schema_version == "scenarioforge.run-result/v2":
            return terminal
        if None in {self.traceability_digest, self.scenario_revision_digest}:
            raise ValueError("v3+ RunResult requires complete revision traceability")
        revision_terminal = {
            **terminal,
            "traceability_digest": self.traceability_digest,
            "scenario_revision_digest": self.scenario_revision_digest,
        }
        if self.schema_version == "scenarioforge.run-result/v3":
            return revision_terminal
        if self.schema_version != "scenarioforge.run-result/v4":
            raise ValueError("RunResult schema version is unsupported")
        if (
            self.status != "cancelled"
            or self.execution_status != "cancelled"
            or self.scenario_outcome != "not_applicable"
            or self.control_command is None
            or self.process_tree_cleanup is None
            or self.statistics_eligible is not False
        ):
            raise ValueError("v4 cancellation requires command and cleanup evidence")
        return {
            **revision_terminal,
            "status": self.status,
            "reason": self.reason,
            "control_command": thaw_json(self.control_command),
            "process_tree_cleanup": thaw_json(self.process_tree_cleanup),
            "statistics_eligible": False,
        }


@dataclass(frozen=True)
class PreparedRun:
    bundle: CompileBundle
    input_snapshot_path: Path
    output_staging_path: Path
    published_path: Path
    run_request: RunRequest


@dataclass(frozen=True)
class RunOutcome:
    bundle: CompileBundle
    input_snapshot_path: Path
    output_staging_path: Path
    published_path: Path
    run_request: RunRequest
    run_result: RunResult
    artifact_index: ArtifactIndex
    worker_pid: int
    worker_exit_code: int
    worker_exited: bool


class TraceabilityError(RuntimeError):
    pass


TRACEABILITY_KEYS = frozenset(
    {
        "scenario_revision_digest",
        "scenario_instance_digest",
        "compile_bundle_digest",
        "compile_report_digest",
        "execution_plan_digest",
        "policy_digest",
        "code_commit",
        "adapter_digest",
        "metadrive_digest",
        "assets_digest",
        "environment_digest",
        "seed",
    }
)


def _object(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TraceabilityError(f"{label} is missing or invalid")
    return value


def validate_run_traceability(
    manifest: Mapping[str, Any],
    result: RunResult | None = None,
) -> None:
    if manifest.get("schema_version") != "scenarioforge.run-manifest/v3":
        raise TraceabilityError("revision traceability requires RunManifest v3")
    revision = _object(manifest.get("scenario_revision"), "scenario revision")
    instance = _object(manifest.get("scenario_instance"), "ScenarioInstance")
    trace = _object(manifest.get("traceability"), "traceability")
    if set(trace) != TRACEABILITY_KEYS:
        raise TraceabilityError("traceability identifiers are missing or duplicated")
    if revision.get("scenario_id") != instance.get("scenario_id"):
        raise TraceabilityError("scenario identity mismatch")
    if revision.get("revision_id") != instance.get("revision_id"):
        raise TraceabilityError("revision identity mismatch")
    if revision.get("digest") != instance.get("revision_digest"):
        raise TraceabilityError("revision digest mismatch")
    if trace.get("scenario_revision_digest") != revision.get("digest"):
        raise TraceabilityError("revision digest trace mismatch")
    expected = {
        "scenario_instance_digest": manifest.get("scenario_instance_digest"),
        "compile_bundle_digest": manifest.get("compile_bundle_digest"),
        "compile_report_digest": _object(manifest.get("compile_report"), "CompileReport").get("digest"),
        "execution_plan_digest": _object(manifest.get("execution_plan"), "ExecutionPlan").get("digest"),
        "policy_digest": canonical_digest(_object(manifest.get("policy"), "policy")),
        "adapter_digest": _object(manifest.get("adapter"), "adapter").get("digest"),
        "metadrive_digest": canonical_digest(_object(manifest.get("simulator"), "MetaDrive")),
        "assets_digest": _object(manifest.get("assets"), "assets").get("digest"),
        "environment_digest": canonical_digest(_object(manifest.get("environment"), "environment")),
        "seed": manifest.get("seed"),
    }
    for key, value in expected.items():
        if trace.get(key) != value:
            raise TraceabilityError(f"{key} mismatch")
    code_commit = trace.get("code_commit")
    if not isinstance(code_commit, str) or len(code_commit) not in {40, 64}:
        raise TraceabilityError("code commit identity is missing")
    digest_keys = TRACEABILITY_KEYS - {"code_commit", "seed"}
    if any(
        not isinstance(trace.get(key), str)
        or len(str(trace[key])) != 64
        or any(character not in "0123456789abcdef" for character in str(trace[key]))
        for key in digest_keys
    ):
        raise TraceabilityError("traceability digest is invalid")
    if result is not None:
        if result.run_id != manifest.get("run_id") or result.attempt_id != manifest.get("attempt_id"):
            raise TraceabilityError("RunResult identity mismatch")
        if result.run_manifest_digest != canonical_digest(manifest):
            raise TraceabilityError("RunResult manifest digest mismatch")
        if result.compile_report_digest != trace["compile_report_digest"]:
            raise TraceabilityError("RunResult CompileReport mismatch")
        if result.execution_plan_digest != trace["execution_plan_digest"]:
            raise TraceabilityError("RunResult ExecutionPlan mismatch")
        if result.traceability_digest != canonical_digest(trace):
            raise TraceabilityError("RunResult traceability digest mismatch")
        if result.scenario_revision_digest != revision.get("digest"):
            raise TraceabilityError("RunResult revision digest mismatch")


def assert_replay_eligible(result: RunResult, index: ArtifactIndex) -> None:
    if result.status != "success" or result.execution_status != "completed":
        raise TraceabilityError("replay requires a completed success")
    if index.execution_status != "completed":
        raise TraceabilityError("replay requires a completed success")
    if (result.run_id, result.attempt_id) != (index.run_id, index.attempt_id):
        raise TraceabilityError("replay evidence identity mismatch")
    if result.run_manifest_digest != index.run_manifest_digest:
        raise TraceabilityError("replay manifest digest mismatch")
    if result.artifact_index_digest != index.digest:
        raise TraceabilityError("replay ArtifactIndex digest mismatch")
    if not index.artifacts or any(
        entry.status != "present" or entry.validation != "verified"
        for entry in index.artifacts
    ):
        raise TraceabilityError("replay requires fully verified artifacts")
