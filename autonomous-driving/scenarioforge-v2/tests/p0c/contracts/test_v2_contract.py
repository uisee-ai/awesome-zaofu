from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scenarioforge.core import EnvironmentFingerprint, ScenarioCompiler, canonical_bytes, instantiate_scenario, load_scenario
from scenarioforge.runtime.artifact_publish import publish_success
from scenarioforge.runtime.snapshot import prepare_run


ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "tests" / "fixtures" / "p0c" / "contracts" / "prototype_v2.json"


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _write(path: Path, value: object) -> None:
    path.write_bytes(canonical_bytes(value))


def test_collision_outcome_is_completed_and_bound_across_v2_terminal_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fingerprint = EnvironmentFingerprint(
        schema_version="scenarioforge.environment-fingerprint/v1",
        os="Linux",
        architecture="x86_64",
        python={"implementation": "CPython", "version": "3.11.15"},
        simulator={
            "distribution": "metadrive-simulator",
            "version": "0.4.3",
            "asset_version": "0.4.3",
            "asset_digest": "a" * 64,
        },
        rendering={"headless": True, "gpu_required": False},
        dependency_lock={"format": "uv.lock", "digest": "b" * 64},
    )
    monkeypatch.setattr(
        "scenarioforge.runtime.snapshot.environment_fingerprint",
        lambda _lockfile: fingerprint,
    )
    monkeypatch.setattr(
        "scenarioforge.runtime.snapshot.importlib.metadata.version",
        lambda name: {"jsonschema": "4.25.1", "metadrive-simulator": "0.4.3"}[name],
    )
    bundle = ScenarioCompiler().compile(instantiate_scenario(load_scenario(FIXTURE)))
    prepared = prepare_run(
        bundle,
        workspace=tmp_path,
        project_root=ROOT,
        run_id="run-v2-collision",
        attempt_id="attempt-0001",
    )
    terminal = {
        "execution_status": "completed",
        "scenario_outcome": "collision_failure",
        "termination_reason": "collision",
    }
    _write(prepared.output_staging_path / "actions.json", [])
    _write(
        prepared.output_staging_path / "events.json",
        [{"schema_version": "scenarioforge.event/v2", "event_id": "collision"}],
    )
    _write(
        prepared.output_staging_path / "metrics.json",
        {
            "schema_version": "scenarioforge.metrics/v2",
            **terminal,
            "collision": True,
            "collision_participants": ["ego", "cutter"],
            "min_ttc_s": 0.0,
            "completed_steps": 30,
            "sample_interval_s": 0.1,
            "metric_definitions": bundle.scenario_instance.constraints["metric_definitions"],
        },
    )
    _write(prepared.output_staging_path / "trajectory.json", [])
    _write(
        prepared.output_staging_path / "worker_result.json",
        {
            "schema_version": "scenarioforge.worker-result/v2",
            "run_id": "run-v2-collision",
            "attempt_id": "attempt-0001",
            "worker_pid": 4321,
            "execution_plan_digest": prepared.run_request.execution_plan_digest,
            "completed_steps": 30,
            "collision": True,
            **terminal,
        },
    )

    result, index = publish_success(prepared, worker_exit_code=0)
    manifest = _read(prepared.input_snapshot_path / "run_manifest.json")
    marker = _read(prepared.published_path / "SUCCESS")

    assert manifest["schema_version"] == "scenarioforge.run-manifest/v2"
    assert manifest["terminal_contract"] == {
        "schema_version": "scenarioforge.terminal-contract/v2",
        "execution_status_values": ["completed", "failed", "timeout", "partial"],
        "scenario_outcome_values": ["safe_pass", "near_miss", "collision_failure"],
        "target_scenario_outcome": "collision_failure",
        "termination_reason_source": "verified_worker_metrics",
    }
    assert result.to_dict() == {
        "schema_version": "scenarioforge.run-result/v2",
        "run_id": "run-v2-collision",
        "attempt_id": "attempt-0001",
        **terminal,
        "worker_exit_code": 0,
        "run_manifest_digest": prepared.run_request.run_manifest_digest,
        "compile_report_digest": bundle.report.digest,
        "execution_plan_digest": prepared.run_request.execution_plan_digest,
        "artifact_index_digest": index.digest,
    }
    assert index.to_dict() == {
        "schema_version": "scenarioforge.artifact-index/v2",
        "run_id": "run-v2-collision",
        "attempt_id": "attempt-0001",
        "run_manifest_digest": prepared.run_request.run_manifest_digest,
        **terminal,
        "artifacts": [entry.to_dict() for entry in index.artifacts],
    }
    assert marker == {
        "schema_version": "scenarioforge.completion-marker/v2",
        **terminal,
        "run_result_digest": _digest(prepared.published_path / "run_result.json"),
        "artifact_index_digest": _digest(prepared.published_path / "artifact_index.json"),
    }
