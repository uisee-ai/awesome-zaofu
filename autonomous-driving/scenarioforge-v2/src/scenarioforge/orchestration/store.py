from __future__ import annotations

import os
import secrets
import threading
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from scenarioforge.core.canonical import canonical_bytes, freeze_json
from scenarioforge.core.strict_json import strict_loads

from .contracts import (
    EXPERIMENT_STATES,
    ExperimentContractError,
    ExperimentDefinition,
    ExperimentJob,
    ExperimentLimits,
    ExperimentManifest,
    ExperimentState,
    JobState,
)


_ACTIVE_STATES = frozenset({"queued", "running", "paused"})


class ExperimentStoreError(RuntimeError):
    pass


class UnknownExperimentError(ExperimentStoreError):
    pass


class ActiveExperimentError(ExperimentStoreError):
    def __init__(self, experiment_id: str) -> None:
        super().__init__("only one active Experiment is allowed")
        self.experiment_id = experiment_id


def _write_new(path: Path, value: object, *, mode: int) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
        mode,
    )
    try:
        payload = canonical_bytes(value)
        if os.write(descriptor, payload) != len(payload):
            raise ExperimentStoreError(f"short write for {path.name}")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _read_object(path: Path) -> dict[str, Any]:
    try:
        payload = path.read_bytes()
        value = strict_loads(payload)
    except (FileNotFoundError, TypeError, ValueError) as error:
        raise UnknownExperimentError("Experiment storage is unavailable") from error
    if not isinstance(value, dict) or canonical_bytes(value) != payload:
        raise ExperimentStoreError(f"{path.name} is not canonical strict JSON")
    return value


class ExperimentStore:
    """Filesystem-backed immutable manifests with separate scheduler state."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = Path(workspace)
        self.root = self.workspace / "experiments"
        self._lock = threading.RLock()

    def submit(
        self,
        definition: ExperimentDefinition,
        *,
        idempotency_key: str,
    ) -> ExperimentManifest:
        if not isinstance(idempotency_key, str) or not idempotency_key:
            raise ExperimentContractError("idempotency_key is invalid")
        definition.validate_capacity()
        with self._lock:
            index = self._load_index()
            prior_id = index.get(idempotency_key)
            if isinstance(prior_id, str):
                prior = self.load_manifest(prior_id)
                if prior.definition_digest != definition.digest:
                    raise ExperimentStoreError(
                        "idempotency key is bound to a different Experiment definition"
                    )
                return prior
            active = self.active_experiment_id()
            if active is not None:
                raise ActiveExperimentError(active)
            experiment_id = f"experiment-{secrets.token_hex(12)}"
            manifest = definition.freeze(experiment_id)
            experiment_root = self.root / experiment_id
            experiment_root.mkdir(parents=True, mode=0o700)
            _write_new(experiment_root / "manifest.json", manifest, mode=0o600)
            (experiment_root / "manifest.json").chmod(0o444)
            state = ExperimentState(
                schema_version="scenarioforge.experiment-state/v1",
                experiment_id=experiment_id,
                state="queued",
                sequence=0,
                jobs=tuple(
                    JobState(
                        schema_version="scenarioforge.experiment-job-state/v1",
                        experiment_id=experiment_id,
                        job_id=job.job_id,
                        logical_run_id=job.logical_run_id,
                        state="queued",
                        attempt_id=None,
                    )
                    for job in manifest.jobs
                ),
                commands=MappingProxyType({}),
            )
            _write_new(experiment_root / "state.json", state, mode=0o600)
            index[idempotency_key] = experiment_id
            self._save_index(index)
            return manifest

    def active_experiment_id(self) -> str | None:
        if not self.root.exists():
            return None
        for path in sorted(self.root.iterdir()):
            if not path.is_dir():
                continue
            try:
                state = self.load_state(path.name)
            except UnknownExperimentError:
                continue
            if state.state in _ACTIVE_STATES:
                return state.experiment_id
        return None

    def list_experiment_ids(self) -> tuple[str, ...]:
        if not self.root.exists():
            return ()
        return tuple(
            path.name
            for path in sorted(self.root.iterdir())
            if path.is_dir() and (path / "manifest.json").is_file()
        )

    def load_manifest(self, experiment_id: str) -> ExperimentManifest:
        value = _read_object(self.root / experiment_id / "manifest.json")
        try:
            limits = ExperimentLimits.from_mapping(value["limits"])
            jobs = tuple(
                ExperimentJob(
                    schema_version=item["schema_version"],
                    experiment_id=item["experiment_id"],
                    job_id=item["job_id"],
                    logical_run_id=item["logical_run_id"],
                    child_ref=item["child_ref"],
                    parameters=freeze_json(item["parameters"]),
                    inputs_digest=item["inputs_digest"],
                    limits_digest=item["limits_digest"],
                )
                for item in value["jobs"]
            )
            return ExperimentManifest(
                schema_version=value["schema_version"],
                experiment_id=value["experiment_id"],
                definition_digest=value["definition_digest"],
                matrix=freeze_json(value["matrix"]),
                cardinality=value["cardinality"],
                inputs=freeze_json(value["inputs"]),
                limits=limits,
                jobs=jobs,
            )
        except (KeyError, TypeError, ExperimentContractError) as error:
            raise ExperimentStoreError("Experiment manifest is invalid") from error

    def load_state(self, experiment_id: str) -> ExperimentState:
        value = _read_object(self.root / experiment_id / "state.json")
        try:
            if value["state"] not in EXPERIMENT_STATES:
                raise ValueError("invalid state")
            jobs = tuple(
                JobState(
                    schema_version=item["schema_version"],
                    experiment_id=item["experiment_id"],
                    job_id=item["job_id"],
                    logical_run_id=item["logical_run_id"],
                    state=item["state"],
                    attempt_id=item["attempt_id"],
                    attempts=tuple(freeze_json(entry) for entry in item.get("attempts", [])),
                )
                for item in value["jobs"]
            )
            return ExperimentState(
                schema_version=value["schema_version"],
                experiment_id=value["experiment_id"],
                state=value["state"],
                sequence=value["sequence"],
                jobs=jobs,
                commands=freeze_json(value.get("commands", {})),
            )
        except (KeyError, TypeError, ValueError, ExperimentContractError) as error:
            raise ExperimentStoreError("Experiment scheduler state is invalid") from error

    def save_state(self, state: ExperimentState) -> None:
        path = self.root / state.experiment_id / "state.json"
        temporary = path.with_name(".state.json.tmp")
        with self._lock:
            if temporary.exists():
                temporary.unlink()
            _write_new(temporary, state, mode=0o600)
            os.replace(temporary, path)
            path.chmod(0o600)

    def _load_index(self) -> dict[str, str]:
        path = self.root / "idempotency.json"
        if not path.exists():
            return {}
        value = _read_object(path)
        if any(not isinstance(key, str) or not isinstance(item, str) for key, item in value.items()):
            raise ExperimentStoreError("Experiment idempotency index is invalid")
        return dict(value)

    def _save_index(self, value: Mapping[str, str]) -> None:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = self.root / "idempotency.json"
        temporary = self.root / ".idempotency.json.tmp"
        if temporary.exists():
            temporary.unlink()
        _write_new(temporary, value, mode=0o600)
        os.replace(temporary, path)
        path.chmod(0o600)
