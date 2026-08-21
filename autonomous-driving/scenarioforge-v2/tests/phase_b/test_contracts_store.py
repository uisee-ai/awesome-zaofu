from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from scenarioforge.orchestration.contracts import (
    CapacityExceededError,
    ExperimentDefinition,
    ExperimentLimits,
)
from scenarioforge.orchestration.store import (
    ActiveExperimentError,
    ExperimentStore,
)


def _definition() -> ExperimentDefinition:
    return ExperimentDefinition.from_mapping(
        {
            "schema_version": "scenarioforge.experiment-definition/v1",
            "matrix": {
                "scenario_id": ["brake_lead", "cut_in"],
                "seed": [7, 8],
            },
            "inputs": {
                "scenario_revision_digest": "a" * 64,
                "policy_binding_ref": "policies/baseline-v2.json",
            },
            "limits": ExperimentLimits.release_default().to_dict(),
        }
    )


def test_definition_freezes_complete_deterministic_matrix_and_child_refs() -> None:
    definition = _definition()

    manifest = definition.freeze("experiment-0001")

    assert manifest.to_dict() == {
        "schema_version": "scenarioforge.experiment-manifest/v1",
        "experiment_id": "experiment-0001",
        "definition_digest": definition.digest,
        "matrix": {
            "scenario_id": ["brake_lead", "cut_in"],
            "seed": [7, 8],
        },
        "cardinality": 4,
        "inputs": {
            "policy_binding_ref": "policies/baseline-v2.json",
            "scenario_revision_digest": "a" * 64,
        },
        "limits": {
            "active_experiments": 1,
            "artifact_bytes": 10_485_760,
            "concurrency": 2,
            "cpu_max_period": 100_000,
            "cpu_max_quota": 100_000,
            "log_bytes": 1_048_576,
            "max_jobs": 64,
            "memory_mib": 4_096,
            "pids": 32,
            "timeout_seconds": 120,
        },
        "jobs": [
            {
                "schema_version": "scenarioforge.experiment-job/v1",
                "experiment_id": "experiment-0001",
                "job_id": "job-0001",
                "logical_run_id": "run-experiment-0001-0001",
                "child_ref": "experiments/experiment-0001/jobs/job-0001",
                "parameters": {"scenario_id": "brake_lead", "seed": 7},
                "inputs_digest": definition.inputs_digest,
                "limits_digest": definition.limits.digest,
            },
            {
                "schema_version": "scenarioforge.experiment-job/v1",
                "experiment_id": "experiment-0001",
                "job_id": "job-0002",
                "logical_run_id": "run-experiment-0001-0002",
                "child_ref": "experiments/experiment-0001/jobs/job-0002",
                "parameters": {"scenario_id": "brake_lead", "seed": 8},
                "inputs_digest": definition.inputs_digest,
                "limits_digest": definition.limits.digest,
            },
            {
                "schema_version": "scenarioforge.experiment-job/v1",
                "experiment_id": "experiment-0001",
                "job_id": "job-0003",
                "logical_run_id": "run-experiment-0001-0003",
                "child_ref": "experiments/experiment-0001/jobs/job-0003",
                "parameters": {"scenario_id": "cut_in", "seed": 7},
                "inputs_digest": definition.inputs_digest,
                "limits_digest": definition.limits.digest,
            },
            {
                "schema_version": "scenarioforge.experiment-job/v1",
                "experiment_id": "experiment-0001",
                "job_id": "job-0004",
                "logical_run_id": "run-experiment-0001-0004",
                "child_ref": "experiments/experiment-0001/jobs/job-0004",
                "parameters": {"scenario_id": "cut_in", "seed": 8},
                "inputs_digest": definition.inputs_digest,
                "limits_digest": definition.limits.digest,
            },
        ],
    }


def test_capacity_is_rejected_before_a_manifest_or_state_is_written(tmp_path: Path) -> None:
    store = ExperimentStore(tmp_path)
    too_large = ExperimentDefinition.from_mapping(
        {
            "schema_version": "scenarioforge.experiment-definition/v1",
            "matrix": {"scenario_id": ["brake_lead"], "seed": list(range(65))},
            "inputs": {},
            "limits": ExperimentLimits.release_default().to_dict(),
        }
    )

    with pytest.raises(CapacityExceededError, match="at most 64 jobs"):
        store.submit(too_large, idempotency_key="request-over-limit")

    assert not (tmp_path / "experiments").exists()


def test_store_keeps_immutable_manifest_and_mutable_scheduler_state_separate(
    tmp_path: Path,
) -> None:
    store = ExperimentStore(tmp_path)

    first = store.submit(_definition(), idempotency_key="request-0001")
    replay = store.submit(_definition(), idempotency_key="request-0001")

    assert replay == first
    root = tmp_path / "experiments" / first.experiment_id
    manifest_path = root / "manifest.json"
    state_path = root / "state.json"
    before = manifest_path.read_bytes()
    assert stat.S_IMODE(manifest_path.stat().st_mode) == 0o444
    assert stat.S_IMODE(state_path.stat().st_mode) == 0o600
    assert json.loads(state_path.read_text(encoding="utf-8"))["state"] == "queued"

    state = store.load_state(first.experiment_id)
    updated = state.with_update(state="running", sequence=state.sequence + 1)
    store.save_state(updated)

    assert manifest_path.read_bytes() == before
    assert store.load_manifest(first.experiment_id) == first
    assert store.load_state(first.experiment_id).state == "running"


def test_only_one_nonterminal_experiment_can_be_submitted(tmp_path: Path) -> None:
    store = ExperimentStore(tmp_path)
    first = store.submit(_definition(), idempotency_key="request-0001")

    with pytest.raises(ActiveExperimentError) as conflict:
        store.submit(_definition(), idempotency_key="request-0002")

    assert conflict.value.experiment_id == first.experiment_id
