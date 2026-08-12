from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


Number = int | float


class _ReplayModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class ReplayFrame(_ReplayModel):
    step: int = Field(ge=0)
    position: tuple[Number, Number]
    heading: Number
    speed_km_h: Number = Field(ge=0)
    collision: bool
    off_road: bool
    route_progress: Number
    actors: tuple["ReplayActor", ...] = ()
    event_receipts: tuple["ReplayEventReceipt", ...] = ()
    static_obstacles: tuple["ReplayObstacle", ...] = ()

    @field_validator("position", mode="before")
    @classmethod
    def freeze_position(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("actors", "event_receipts", "static_obstacles", mode="before")
    @classmethod
    def freeze_evidence_sequences(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


class ReplayActor(_ReplayModel):
    actor_id: str
    role: Literal["ego", "traffic"]
    position: tuple[Number, Number]
    speed_mps: Number = Field(ge=0)
    heading: Number
    state: str

    @field_validator("position", mode="before")
    @classmethod
    def freeze_position(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


class ReplayEventReceipt(_ReplayModel):
    trigger_id: str
    target_actor_id: str
    action: str
    status: str
    result: str


class ReplayObstacle(_ReplayModel):
    obstacle_id: str
    position: tuple[Number, Number]
    state: str

    @field_validator("position", mode="before")
    @classmethod
    def freeze_position(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


class ReplayEvent(_ReplayModel):
    tick: int = Field(ge=0)
    kind: Literal["collision", "off_road", "termination"]
    label: str


class ReplaySafetyMetrics(_ReplayModel):
    minimum_ttc_seconds: Number | None
    minimum_headway_seconds: Number | None
    event_to_response_latency_seconds: Number | None
    collision: bool
    off_road: bool
    route_progress: Number


class ReplaySafetyCase(_ReplayModel):
    case_index: int = Field(ge=0)
    metrics: ReplaySafetyMetrics
    safety_constraints: dict[str, bool | Number]
    safety_verdict: Literal["pass", "fail"]
    violations: tuple[str, ...]

    @field_validator("violations", mode="before")
    @classmethod
    def freeze_violations(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


class ReplayMetricDefinition(_ReplayModel):
    formula_version: str
    formula: str
    unit: str
    missing_value: None


class ReplaySafetyEvidence(_ReplayModel):
    schema_version: Literal["scenarioforge.safety-evidence.v1"]
    metric_definitions: dict[str, ReplayMetricDefinition]
    cases: tuple[ReplaySafetyCase, ...]

    @field_validator("cases", mode="before")
    @classmethod
    def freeze_cases(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


class ReplayCase(_ReplayModel):
    case_index: int = Field(ge=0)
    seed: int = Field(ge=0)
    status: Literal["completed", "crashed", "timed_out", "cancelled", "aborted", "not_run"]
    scenario_verdict: Literal["pass", "fail"] | None
    termination_reason: str
    steps: int = Field(ge=0)
    simulated_seconds: Number = Field(ge=0)
    collision: bool
    off_road: bool
    route_progress: Number
    frames: tuple[ReplayFrame, ...]
    events: tuple[ReplayEvent, ...]


class ReplayMetrics(_ReplayModel):
    case_count: int = Field(ge=0)
    completed_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    total_steps: int = Field(ge=0)
    total_case_wall_seconds: Number = Field(ge=0)
    total_cpu_seconds: Number = Field(ge=0)
    peak_worker_rss_bytes: int = Field(ge=0)


class ReplayProvider(_ReplayModel):
    backend: Literal["metadrive-simulator"]
    backend_version: Literal["0.4.3"]
    execution_kind: Literal["real-metadrive"]
    network_policy: Literal["denied"]
    auto_download: Literal[False]


class ReplayExecution(_ReplayModel):
    runner_state: Literal["stopped"]
    metadrive_calls: Literal[0]
    external_network: Literal["denied"]


class ReplayBundle(_ReplayModel):
    schema_version: Literal["scenarioforge.replay.v1"]
    bundle_id: str
    status: Literal["completed", "partial", "cancelled", "aborted"]
    scenario_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    cases: tuple[ReplayCase, ...]
    metrics: ReplayMetrics
    safety_evidence: ReplaySafetyEvidence | None = None
    provider: ReplayProvider
    execution: ReplayExecution
