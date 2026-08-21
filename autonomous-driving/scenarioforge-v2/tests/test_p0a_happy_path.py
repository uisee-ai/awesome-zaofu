from __future__ import annotations

import hashlib
import json
import math
import os
import stat
import sys
from pathlib import Path

import pytest

from scenarioforge.core import ScenarioCompiler, instantiate_scenario, load_scenario
from scenarioforge.runtime import RunSupervisor, validate_input_snapshot


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "p0a" / "brake_lead.json"
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "p0a" / "happy"


def _read(path: Path) -> dict[str, object] | list[object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _fixture(name: str) -> dict[str, object]:
    value = _read(FIXTURE_DIR / name)
    assert isinstance(value, dict)
    return value


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _assert_public_json(value: object) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            lowered = key.lower()
            assert "secret" not in lowered
            assert "token" not in lowered
            assert "host_path" not in lowered
            assert "executable" not in lowered
            _assert_public_json(item)
    elif isinstance(value, list):
        for item in value:
            _assert_public_json(item)
    elif isinstance(value, str):
        assert not value.startswith("/")
        assert not value.startswith("file:")
        assert "../" not in value


@pytest.fixture(scope="module")
def exact_bundle():
    instance = instantiate_scenario(load_scenario(EXAMPLE))
    return ScenarioCompiler().compile(instance)


def test_pure_compile_bundle_matches_complete_golden_contract(exact_bundle) -> None:
    assert "metadrive" not in sys.modules
    compiler = ScenarioCompiler()

    assert compiler.capabilities().to_dict() == _fixture("capability_descriptor.json")
    assert exact_bundle.report.to_dict() == _fixture("compile_report.json")
    assert exact_bundle.execution_plan is not None
    assert exact_bundle.execution_plan.to_dict() == _fixture("execution_plan.json")
    assert exact_bundle.report.digest == hashlib.sha256(
        json.dumps(
            _fixture("compile_report.json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    assert exact_bundle.execution_plan.digest == hashlib.sha256(
        json.dumps(
            _fixture("execution_plan.json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    assert "metadrive" not in sys.modules


@pytest.fixture(scope="module")
def published_run(tmp_path_factory: pytest.TempPathFactory, exact_bundle):
    workspace = tmp_path_factory.mktemp("scenarioforge-runs")
    supervisor = RunSupervisor(workspace=workspace, project_root=ROOT)
    outcome = supervisor.run(
        exact_bundle,
        run_id="run-happy-0001",
        attempt_id="attempt-0001",
        timeout_seconds=120,
    )
    return outcome


def test_real_metadrive_worker_is_single_run_isolated_and_exits(published_run) -> None:
    assert published_run.worker_exit_code == 0
    assert published_run.worker_pid != os.getpid()
    assert published_run.worker_exited is True
    assert "metadrive" not in sys.modules
    assert published_run.input_snapshot_path != published_run.output_staging_path
    assert os.path.commonpath(
        [published_run.input_snapshot_path, published_run.output_staging_path]
    ) != str(published_run.input_snapshot_path)
    assert not published_run.output_staging_path.exists()
    assert stat.S_IMODE(published_run.input_snapshot_path.stat().st_mode) == 0o555
    assert stat.S_IMODE(published_run.published_path.stat().st_mode) == 0o555
    assert validate_input_snapshot(published_run.input_snapshot_path) == (
        published_run.run_request.input_snapshot_digest
    )


def test_frozen_manifest_and_request_bind_complete_execution_inputs(published_run) -> None:
    manifest = _read(published_run.input_snapshot_path / "run_manifest.json")
    request = _read(published_run.input_snapshot_path / "run_request.json")
    assert isinstance(manifest, dict)
    assert isinstance(request, dict)

    assert set(manifest) == {
        "schema_version",
        "run_id",
        "attempt_id",
        "source_spec_digest",
        "scenario_instance",
        "scenario_instance_digest",
        "seed",
        "resolved_parameters",
        "policy",
        "adapter",
        "compiler",
        "compile_report",
        "execution_plan",
        "simulator",
        "python",
        "dependencies",
        "assets",
        "environment",
        "resource_config",
        "tolerances_version",
        "input_snapshot",
        "output_staging",
    }
    assert manifest["schema_version"] == "scenarioforge.run-manifest/v1"
    assert manifest["run_id"] == "run-happy-0001"
    assert manifest["attempt_id"] == "attempt-0001"
    assert manifest["scenario_instance"] == _fixture("scenario_instance.json")
    assert manifest["scenario_instance_digest"] == (
        "463a1a6f9e48df7c81ba7bbc11844d76906744accc437e8852c5735fb165783e"
    )
    assert manifest["seed"] == 7
    assert manifest["resolved_parameters"] == {
        "initial_gap_m": 20.0,
        "vehicle_speed_mps": 8.0,
        "brake_tick": 2,
        "brake_intensity": 1.0,
    }
    assert manifest["policy"] == {
        "id": "scenarioforge.constant-lane",
        "version": "1.0.0",
        "config_digest": hashlib.sha256(
            b'{"steering":0.0,"throttle_brake":0.0}'
        ).hexdigest(),
    }
    assert manifest["adapter"] == {
        "id": "scenarioforge.metadrive",
        "version": "1.0.0",
        "digest": hashlib.sha256(
            b'{"id":"scenarioforge.metadrive","version":"1.0.0"}'
        ).hexdigest(),
    }
    assert manifest["compiler"] == {
        "version": "1.0.0",
        "capability_descriptor_digest": (
            "5092ab83e644703b27b0d7dd724d9d2f9fe2c9fb4a28afd8f05507e963952d1d"
        ),
    }
    assert manifest["compile_report"] == {
        "ref": "compile_report.json",
        "digest": published_run.bundle.report.digest,
    }
    assert manifest["execution_plan"] == {
        "ref": "execution_plan.json",
        "digest": published_run.bundle.execution_plan.digest,
    }
    assert manifest["simulator"]["distribution"] == "metadrive-simulator"
    assert manifest["simulator"]["version"] == "0.4.3"
    assert manifest["simulator"]["asset_version"] == "0.4.3"
    assert len(manifest["simulator"]["asset_digest"]) == 64
    assert manifest["environment"] == {
        "os": "Linux",
        "architecture": "x86_64",
        "headless": True,
        "gpu_required": False,
    }
    assert manifest["resource_config"] == _fixture("execution_plan.json")["resource_config"]
    assert manifest["tolerances_version"] == "scenarioforge.p0a-tolerances/v1"
    assert manifest["input_snapshot"] == {
        "logical_id": "input-run-happy-0001-attempt-0001",
        "digest": published_run.run_request.input_snapshot_digest,
        "digest_contract": "scenarioforge.input-snapshot-digest/v1",
    }
    assert manifest["output_staging"] == {
        "logical_id": "staging-run-happy-0001-attempt-0001"
    }

    assert request == {
        "schema_version": "scenarioforge.run-request/v1",
        "run_id": "run-happy-0001",
        "attempt_id": "attempt-0001",
        "input_snapshot_ref": "input-run-happy-0001-attempt-0001",
        "input_snapshot_digest": published_run.run_request.input_snapshot_digest,
        "run_manifest_digest": published_run.run_request.run_manifest_digest,
        "execution_plan_digest": published_run.bundle.execution_plan.digest,
    }
    assert "scenario_instance" not in request
    _assert_public_json(manifest)
    _assert_public_json(request)


def test_tick_event_drives_s_n_to_s_n_plus_1_and_real_physics_artifacts(published_run) -> None:
    output = published_run.published_path / "output"
    actions = _read(output / "actions.json")
    events = _read(output / "events.json")
    trajectory = _read(output / "trajectory.json")
    metrics = _read(output / "metrics.json")
    worker_result = _read(output / "worker_result.json")

    assert events == [
        {
            "schema_version": "scenarioforge.event/v1",
            "event_id": "lead-brake",
            "type": "trigger_fired",
            "participant_id": "lead",
            "trigger_tick": 2,
            "effect_state_tick": 3,
            "priority_contract": "scenarioforge.trigger-priority/v1",
            "action": {"steering": 0.0, "throttle_brake": -1.0},
        }
    ]
    assert isinstance(actions, list) and len(actions) == 12
    assert [(item["tick"], item["participant_id"]) for item in actions] == [
        (tick, participant)
        for tick in range(6)
        for participant in ("ego", "lead")
    ]
    lead_brake = [
        item for item in actions if item["tick"] == 2 and item["participant_id"] == "lead"
    ]
    assert lead_brake == [
        {
            "schema_version": "scenarioforge.action/v1",
            "tick": 2,
            "participant_id": "lead",
            "policy_action": {"steering": 0.0, "throttle_brake": 0.0},
            "final_action": {"steering": 0.0, "throttle_brake": -1.0},
            "source": "scenario_override",
        }
    ]

    assert isinstance(trajectory, list) and len(trajectory) == 14
    assert [(item["tick"], item["participant_id"]) for item in trajectory] == [
        (tick, participant)
        for tick in range(7)
        for participant in ("ego", "lead")
    ]
    for item in trajectory:
        assert set(item) == {
            "schema_version",
            "tick",
            "participant_id",
            "position_m",
            "speed_mps",
            "heading_deg",
            "collision",
        }
        assert all(math.isfinite(value) for value in item["position_m"])
        assert math.isfinite(item["speed_mps"])
        assert math.isfinite(item["heading_deg"])

    assert set(metrics) == {
        "schema_version",
        "collision",
        "collision_participants",
        "termination_reason",
        "terminal_status",
        "min_ttc_s",
        "completed_steps",
        "sample_interval_s",
    }
    assert metrics["collision"] is False
    assert metrics["collision_participants"] == []
    assert metrics["termination_reason"] == "horizon_completed"
    assert metrics["terminal_status"] == "success"
    assert metrics["completed_steps"] == 6
    assert metrics["sample_interval_s"] == 0.1
    assert metrics["min_ttc_s"] is None or metrics["min_ttc_s"] >= 0.0

    assert set(worker_result) == {
        "schema_version",
        "run_id",
        "attempt_id",
        "worker_pid",
        "backend",
        "execution_plan_digest",
        "completed_steps",
        "collision",
        "termination_reason",
        "status",
    }
    assert worker_result["run_id"] == "run-happy-0001"
    assert worker_result["attempt_id"] == "attempt-0001"
    assert worker_result["worker_pid"] == published_run.worker_pid
    assert worker_result["backend"] == {
        "distribution": "metadrive-simulator",
        "version": "0.4.3",
        "asset_version": "0.4.3",
        "engine_class": "MultiAgentMetaDrive",
    }
    assert worker_result["execution_plan_digest"] == published_run.bundle.execution_plan.digest
    assert worker_result["completed_steps"] == 6
    assert worker_result["collision"] is False
    assert worker_result["termination_reason"] == "horizon_completed"
    assert worker_result["status"] == "completed"


def test_supervisor_atomically_publishes_immutable_success_evidence(published_run) -> None:
    result = _read(published_run.published_path / "run_result.json")
    index = _read(published_run.published_path / "artifact_index.json")
    marker = _read(published_run.published_path / "SUCCESS")
    assert isinstance(result, dict)
    assert isinstance(index, dict)
    assert isinstance(marker, dict)

    assert set(result) == {
        "schema_version",
        "run_id",
        "attempt_id",
        "status",
        "reason",
        "worker_exit_code",
        "run_manifest_digest",
        "compile_report_digest",
        "execution_plan_digest",
        "artifact_index_digest",
    }
    assert result == published_run.run_result.to_dict()
    assert result["status"] == "success"
    assert result["reason"] == "horizon_completed"
    assert result["worker_exit_code"] == 0
    assert result["artifact_index_digest"] == published_run.artifact_index.digest

    expected_paths = [
        "input/assets.json",
        "input/compile_report.json",
        "input/execution_plan.json",
        "input/policy.json",
        "input/run_manifest.json",
        "input/run_request.json",
        "output/actions.json",
        "output/events.json",
        "output/metrics.json",
        "output/trajectory.json",
        "output/worker_result.json",
    ]
    assert index["schema_version"] == "scenarioforge.artifact-index/v1"
    assert index["run_id"] == "run-happy-0001"
    assert index["attempt_id"] == "attempt-0001"
    assert [entry["path"] for entry in index["artifacts"]] == expected_paths
    for entry in index["artifacts"]:
        assert set(entry) == {"path", "status", "size_bytes", "digest", "validation"}
        path = published_run.published_path / entry["path"]
        assert entry == {
            "path": entry["path"],
            "status": "present",
            "size_bytes": path.stat().st_size,
            "digest": _digest(path),
            "validation": "verified",
        }

    assert marker == {
        "schema_version": "scenarioforge.completion-marker/v1",
        "status": "success",
        "run_result_digest": _digest(published_run.published_path / "run_result.json"),
        "artifact_index_digest": _digest(published_run.published_path / "artifact_index.json"),
    }
    for path in published_run.published_path.rglob("*"):
        assert not path.is_symlink()
        assert not (path.stat().st_mode & stat.S_IWUSR)
    _assert_public_json(result)
    _assert_public_json(index)
    _assert_public_json(marker)
