from __future__ import annotations

import itertools
import re
from dataclasses import dataclass, replace
from functools import reduce
from operator import mul
from types import MappingProxyType
from typing import Any, Mapping

from scenarioforge.core.canonical import (
    CanonicalModel,
    JSONValue,
    canonical_digest,
    freeze_json,
    thaw_json,
)


_SAFE_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_DEFINITION_FIELDS = {"schema_version", "matrix", "inputs", "limits"}
_LIMIT_FIELDS = {
    "active_experiments",
    "artifact_bytes",
    "concurrency",
    "cpu_max_period",
    "cpu_max_quota",
    "log_bytes",
    "max_jobs",
    "memory_mib",
    "pids",
    "timeout_seconds",
}


class ExperimentContractError(ValueError):
    pass


class CapacityExceededError(ExperimentContractError):
    pass


def _strict_positive_integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ExperimentContractError(f"{label} must be a positive integer")
    return value


@dataclass(frozen=True)
class ExperimentLimits(CanonicalModel):
    active_experiments: int
    artifact_bytes: int
    concurrency: int
    cpu_max_period: int
    cpu_max_quota: int
    log_bytes: int
    max_jobs: int
    memory_mib: int
    pids: int
    timeout_seconds: int

    @classmethod
    def release_default(cls) -> "ExperimentLimits":
        return cls(
            active_experiments=1,
            artifact_bytes=10 * 1024 * 1024,
            concurrency=2,
            cpu_max_period=100_000,
            cpu_max_quota=100_000,
            log_bytes=1024 * 1024,
            max_jobs=64,
            memory_mib=4096,
            pids=32,
            timeout_seconds=120,
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "ExperimentLimits":
        if set(value) != _LIMIT_FIELDS:
            raise ExperimentContractError("experiment limit fields are invalid")
        limits = cls(
            **{
                field: _strict_positive_integer(value[field], field)
                for field in sorted(_LIMIT_FIELDS)
            }
        )
        release = cls.release_default()
        if limits.concurrency > release.concurrency:
            raise CapacityExceededError("concurrency exceeds the limit of two")
        if limits.max_jobs > release.max_jobs:
            raise CapacityExceededError("max_jobs exceeds the limit of 64")
        if limits.active_experiments > release.active_experiments:
            raise CapacityExceededError("only one active Experiment is allowed")
        hard_fields = (
            "artifact_bytes",
            "cpu_max_period",
            "cpu_max_quota",
            "log_bytes",
            "memory_mib",
            "pids",
            "timeout_seconds",
        )
        if any(getattr(limits, field) > getattr(release, field) for field in hard_fields):
            raise CapacityExceededError("resource limits exceed the release profile")
        return limits


@dataclass(frozen=True)
class ExperimentDefinition(CanonicalModel):
    schema_version: str
    matrix: Mapping[str, tuple[JSONValue, ...]]
    inputs: Mapping[str, JSONValue]
    limits: ExperimentLimits

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "ExperimentDefinition":
        if not isinstance(value, Mapping) or set(value) != _DEFINITION_FIELDS:
            raise ExperimentContractError("Experiment definition fields are invalid")
        if value.get("schema_version") != "scenarioforge.experiment-definition/v1":
            raise ExperimentContractError("Experiment definition schema is invalid")
        raw_matrix = value.get("matrix")
        if not isinstance(raw_matrix, Mapping) or not raw_matrix:
            raise ExperimentContractError("Experiment matrix must be a non-empty object")
        matrix: dict[str, tuple[JSONValue, ...]] = {}
        for name in sorted(raw_matrix):
            values = raw_matrix[name]
            if not isinstance(name, str) or _SAFE_NAME.fullmatch(name) is None:
                raise ExperimentContractError("Experiment matrix dimension is invalid")
            if not isinstance(values, (list, tuple)) or not values:
                raise ExperimentContractError("Experiment matrix dimensions cannot be empty")
            frozen_values = tuple(freeze_json(item) for item in values)
            digests = [canonical_digest(item) for item in frozen_values]
            if len(digests) != len(set(digests)):
                raise ExperimentContractError("Experiment matrix values must be unique")
            matrix[name] = frozen_values
        raw_inputs = value.get("inputs")
        if not isinstance(raw_inputs, Mapping):
            raise ExperimentContractError("Experiment inputs must be an object")
        limits_value = value.get("limits")
        if not isinstance(limits_value, Mapping):
            raise ExperimentContractError("Experiment limits must be an object")
        return cls(
            schema_version="scenarioforge.experiment-definition/v1",
            matrix=MappingProxyType(matrix),
            inputs=freeze_json(raw_inputs),
            limits=ExperimentLimits.from_mapping(limits_value),
        )

    @property
    def cardinality(self) -> int:
        return reduce(mul, (len(values) for values in self.matrix.values()), 1)

    @property
    def inputs_digest(self) -> str:
        return canonical_digest(self.inputs)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "matrix": thaw_json(self.matrix),
            "inputs": thaw_json(self.inputs),
            "limits": self.limits.to_dict(),
        }

    def validate_capacity(self) -> None:
        if self.cardinality > self.limits.max_jobs:
            raise CapacityExceededError(
                f"Experiment contains {self.cardinality} jobs; at most 64 jobs are allowed"
            )

    def freeze(self, experiment_id: str) -> "ExperimentManifest":
        if not isinstance(experiment_id, str) or _SAFE_ID.fullmatch(experiment_id) is None:
            raise ExperimentContractError("experiment_id is invalid")
        self.validate_capacity()
        names = tuple(self.matrix)
        jobs: list[ExperimentJob] = []
        for offset, values in enumerate(
            itertools.product(*(self.matrix[name] for name in names)),
            start=1,
        ):
            job_id = f"job-{offset:04d}"
            jobs.append(
                ExperimentJob(
                    schema_version="scenarioforge.experiment-job/v1",
                    experiment_id=experiment_id,
                    job_id=job_id,
                    logical_run_id=f"run-{experiment_id}-{offset:04d}",
                    child_ref=f"experiments/{experiment_id}/jobs/{job_id}",
                    parameters=MappingProxyType(dict(zip(names, values, strict=True))),
                    inputs_digest=self.inputs_digest,
                    limits_digest=self.limits.digest,
                )
            )
        return ExperimentManifest(
            schema_version="scenarioforge.experiment-manifest/v1",
            experiment_id=experiment_id,
            definition_digest=self.digest,
            matrix=self.matrix,
            cardinality=len(jobs),
            inputs=self.inputs,
            limits=self.limits,
            jobs=tuple(jobs),
        )


@dataclass(frozen=True)
class ExperimentJob(CanonicalModel):
    schema_version: str
    experiment_id: str
    job_id: str
    logical_run_id: str
    child_ref: str
    parameters: Mapping[str, JSONValue]
    inputs_digest: str
    limits_digest: str


@dataclass(frozen=True)
class ExperimentManifest(CanonicalModel):
    schema_version: str
    experiment_id: str
    definition_digest: str
    matrix: Mapping[str, tuple[JSONValue, ...]]
    cardinality: int
    inputs: Mapping[str, JSONValue]
    limits: ExperimentLimits
    jobs: tuple[ExperimentJob, ...]


JOB_STATES = frozenset(
    {"queued", "running", "paused", "completed", "failed", "timeout", "cancelled"}
)
EXPERIMENT_STATES = frozenset(
    {"queued", "running", "paused", "completed", "failed", "cancelled"}
)


@dataclass(frozen=True)
class JobState(CanonicalModel):
    schema_version: str
    experiment_id: str
    job_id: str
    logical_run_id: str
    state: str
    attempt_id: str | None
    attempts: tuple[Mapping[str, JSONValue], ...] = ()

    def __post_init__(self) -> None:
        if self.state not in JOB_STATES:
            raise ExperimentContractError("job state is invalid")


@dataclass(frozen=True)
class ExperimentState(CanonicalModel):
    schema_version: str
    experiment_id: str
    state: str
    sequence: int
    jobs: tuple[JobState, ...]
    commands: Mapping[str, JSONValue]

    def __post_init__(self) -> None:
        if self.state not in EXPERIMENT_STATES:
            raise ExperimentContractError("Experiment state is invalid")
        if isinstance(self.sequence, bool) or self.sequence < 0:
            raise ExperimentContractError("Experiment sequence is invalid")

    def with_update(self, **changes: Any) -> "ExperimentState":
        return replace(self, **changes)
