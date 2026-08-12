from __future__ import annotations

from typing import Any, Literal

import rfc8785
from pydantic import BaseModel, ConfigDict, field_validator

from scenarioforge.spec import ActorSpec, ResourceLimits


class _CompiledModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class BackendVersion(_CompiledModel):
    distribution: Literal["metadrive-simulator"]
    version: Literal["0.4.3"]


class CompiledCase(_CompiledModel):
    case_index: int
    seed: int
    actor_plan: tuple[ActorSpec, ...]
    metadrive_config: dict[str, Any]
    p0_provenance: dict[str, Any]
    runtime_plan: dict[str, Any]
    effective_config_digest: str

    @field_validator("actor_plan", mode="before")
    @classmethod
    def freeze_actor_plan(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


class CompiledMetadata(_CompiledModel):
    scenario_name: str
    source_schema_version: str
    tags: tuple[str, ...]


class CompiledBundle(_CompiledModel):
    schema_version: Literal["scenarioforge.compiled-bundle.v1"]
    scenario_digest: str
    run_request_digest: str
    compiler_version: Literal["scenarioforge.compiler.v1"]
    backend: BackendVersion
    field_map: dict[str, str]
    metadata: CompiledMetadata
    limits: ResourceLimits
    cases: tuple[CompiledCase, ...]
    effective_config_digest: str
    compiled_digest: str

    def canonical_bytes(self) -> bytes:
        return rfc8785.dumps(self.model_dump(mode="json"))
