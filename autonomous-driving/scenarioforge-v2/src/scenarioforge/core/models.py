from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from .canonical import CanonicalModel, JSONValue, freeze_json


class CompilationStatus(str, Enum):
    EXACT = "exact"
    LOSSY = "lossy"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class ScenarioDocument:
    value: Mapping[str, JSONValue]
    raw_digest: str
    canonical_digest: str
    canonical_payload: bytes
    source_path: Path


@dataclass(frozen=True)
class ScenarioInstance(CanonicalModel):
    schema_version: str
    scenario_id: str
    source_schema_version: str
    source_spec_digest: str
    seed: int
    road: Mapping[str, JSONValue]
    participants: tuple[Mapping[str, JSONValue], ...]
    parameters: Mapping[str, JSONValue]
    events: tuple[Mapping[str, JSONValue], ...]
    constraints: Mapping[str, JSONValue]
    policy: Mapping[str, JSONValue]
    required_capabilities: tuple[str, ...]
    backend_extensions: Mapping[str, JSONValue]
    revision_id: str | None = None
    revision_digest: str | None = None
    revision_schema_version: str | None = None

    def to_dict(self) -> dict[str, Any]:
        value = super().to_dict()
        revision_fields = ("revision_id", "revision_digest", "revision_schema_version")
        if self.revision_id is None:
            for field in revision_fields:
                value.pop(field)
        elif any(value[field] is None for field in revision_fields):
            raise ValueError("revision-aware ScenarioInstance requires complete revision identity")
        return value

    @classmethod
    def from_spec(cls, spec: Mapping[str, Any], source_spec_digest: str) -> "ScenarioInstance":
        source_schema_version = str(spec["schema_version"])
        return cls(
            schema_version=(
                "scenarioforge.scenario-instance/v2"
                if source_schema_version == "scenarioforge.scenario/v2"
                else "scenarioforge.scenario-instance/v1"
            ),
            scenario_id=str(spec["scenario_id"]),
            source_schema_version=source_schema_version,
            source_spec_digest=source_spec_digest,
            seed=int(spec["seed"]),
            road=freeze_json(spec["road"]),
            participants=freeze_json(spec["participants"]),
            parameters=freeze_json(spec["parameters"]),
            events=freeze_json(spec["events"]),
            constraints=freeze_json(spec["constraints"]),
            policy=freeze_json(spec["policy"]),
            required_capabilities=tuple(str(item) for item in spec["required_capabilities"]),
            backend_extensions=freeze_json(spec["backend_extensions"]),
        )


@dataclass(frozen=True)
class CapabilityDescriptor(CanonicalModel):
    schema_version: str
    backend_id: str
    backend_version: str
    adapter_id: str
    adapter_version: str
    compiler_version: str
    supported_capabilities: tuple[str, ...]
    extension_contracts: Mapping[str, JSONValue]


@dataclass(frozen=True)
class CompilationDiagnostic(CanonicalModel):
    path: str
    capability: str
    status: CompilationStatus
    reason: str
    alternative: str | None


@dataclass(frozen=True)
class CapabilityMapping(CanonicalModel):
    path: str
    capability: str
    status: CompilationStatus
    reason: str
    alternative: str | None


@dataclass(frozen=True)
class CompileReport(CanonicalModel):
    schema_version: str
    compiler_version: str
    capability_descriptor_digest: str
    scenario_instance_digest: str
    overall_status: CompilationStatus
    executable: bool
    mappings: tuple[CapabilityMapping, ...]
    diagnostics: tuple[CompilationDiagnostic, ...]
    adapter_id: str | None = None
    adapter_version: str | None = None
    adapter_digest: str | None = None

    def to_dict(self) -> dict[str, Any]:
        value = super().to_dict()
        adapter_fields = ("adapter_id", "adapter_version", "adapter_digest")
        if self.adapter_id is None:
            for field in adapter_fields:
                value.pop(field)
        elif any(value[field] is None for field in adapter_fields):
            raise ValueError("versioned CompileReport requires complete adapter identity")
        return value


@dataclass(frozen=True)
class ExecutionPlan(CanonicalModel):
    schema_version: str
    scenario_instance_digest: str
    backend: Mapping[str, JSONValue]
    seed: int
    simulation: Mapping[str, JSONValue]
    participants: tuple[Mapping[str, JSONValue], ...]
    events: tuple[Mapping[str, JSONValue], ...]
    constraints: Mapping[str, JSONValue]
    policy: Mapping[str, JSONValue]
    tick_contract: Mapping[str, JSONValue]
    artifact_contract: Mapping[str, JSONValue]
    resource_config: Mapping[str, JSONValue]
    tolerances_version: str


@dataclass(frozen=True)
class CompileBundle(CanonicalModel):
    scenario_instance: ScenarioInstance
    report: CompileReport
    execution_plan: ExecutionPlan | None
    confirmation: Mapping[str, JSONValue] | None = None

    def to_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "scenario_instance": self.scenario_instance.to_dict(),
            "report": self.report.to_dict(),
            "execution_plan": (
                None if self.execution_plan is None else self.execution_plan.to_dict()
            ),
        }
        if self.confirmation is not None:
            value["confirmation"] = self.confirmation
        return value


@dataclass(frozen=True)
class EnvironmentFingerprint(CanonicalModel):
    schema_version: str
    os: str
    architecture: str
    python: Mapping[str, JSONValue]
    simulator: Mapping[str, JSONValue]
    rendering: Mapping[str, JSONValue]
    dependency_lock: Mapping[str, JSONValue]
