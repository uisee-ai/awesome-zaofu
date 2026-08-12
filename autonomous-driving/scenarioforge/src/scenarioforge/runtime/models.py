from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict


class RunRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal["scenarioforge.run-record.v1"]
    case_index: int
    seed: int
    status: Literal["completed", "crashed", "timed_out", "cancelled", "aborted", "not_run"]
    scenario_verdict: Literal["pass", "fail"] | None
    termination_reason: str
    steps: int
    simulated_seconds: float
    collision: bool
    off_road: bool
    route_progress: float
    wall_seconds: float
    cpu_seconds: float
    peak_rss_bytes: int
    worker_pid: int | None
    worker_instance_id: str | None
    retry_count: Literal[0]
    backend: Literal["metadrive-simulator"]
    backend_version: Literal["0.4.3"]
    effective_config_digest: str


@dataclass(frozen=True)
class RunOutcome:
    run_id: str
    status: Literal["completed", "partial", "cancelled", "aborted"]
    bundle_path: Path
    records: tuple[RunRecord, ...]
