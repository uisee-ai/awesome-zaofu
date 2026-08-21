from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from scenarioforge.core import InputLimits, ScenarioCompiler, instantiate_scenario, load_scenario
from scenarioforge.failsafe import terminate_process_tree
from scenarioforge.security import (
    ArtifactVerification,
    ResourceObservation,
    ResourcePolicy,
    SecurityViolation,
    build_worker_environment,
    enforce_resource_policy,
    load_untrusted_scenario,
    observe_process_group,
    redact_log,
    validate_isolated_directories,
    verify_output_artifacts,
    verify_snapshot_binding,
)
from scenarioforge.runtime.snapshot import prepare_run


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "security" / "security_cases.json"
EXAMPLE = ROOT / "examples" / "p0a" / "brake_lead.json"


@pytest.fixture(scope="module")
def security_cases() -> dict[str, object]:
    value = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert value == {
        "schema_version": "scenarioforge.security-negative-cases/v1",
        "environment_cases": [
            {
                "case_id": "secret-canary",
                "overrides": {
                    "SCENARIOFORGE_SECRET_CANARY": "CANARY-MUST-NOT-LEAK"
                },
                "expected_code": "unexpected_environment",
            },
            {
                "case_id": "pythonpath-override",
                "overrides": {"PYTHONPATH": "/tmp/shadowed-runtime"},
                "expected_code": "unexpected_environment",
            },
        ],
        "resource_policy": {
            "wall_clock_timeout_s": 1,
            "memory_limit_mb": 64,
            "pid_limit": 2,
            "log_limit_bytes": 16,
            "artifact_limit_bytes": 32,
        },
        "resource_cases": [
            {
                "case_id": "wall-clock",
                "observation": {
                    "elapsed_seconds": 1.001,
                    "memory_bytes": 1,
                    "process_count": 1,
                    "log_bytes": 1,
                    "artifact_bytes": 1,
                },
                "expected_code": "wall_clock_limit_exceeded",
            },
            {
                "case_id": "memory",
                "observation": {
                    "elapsed_seconds": 0.5,
                    "memory_bytes": 67_108_865,
                    "process_count": 1,
                    "log_bytes": 1,
                    "artifact_bytes": 1,
                },
                "expected_code": "memory_limit_exceeded",
            },
            {
                "case_id": "pid-count",
                "observation": {
                    "elapsed_seconds": 0.5,
                    "memory_bytes": 1,
                    "process_count": 3,
                    "log_bytes": 1,
                    "artifact_bytes": 1,
                },
                "expected_code": "pid_limit_exceeded",
            },
            {
                "case_id": "log-size",
                "observation": {
                    "elapsed_seconds": 0.5,
                    "memory_bytes": 1,
                    "process_count": 1,
                    "log_bytes": 17,
                    "artifact_bytes": 1,
                },
                "expected_code": "log_limit_exceeded",
            },
            {
                "case_id": "artifact-size",
                "observation": {
                    "elapsed_seconds": 0.5,
                    "memory_bytes": 1,
                    "process_count": 1,
                    "log_bytes": 1,
                    "artifact_bytes": 33,
                },
                "expected_code": "artifact_limit_exceeded",
            },
        ],
    }
    return value


def test_worker_environment_is_fixed_and_rejects_secret_or_pythonpath_overrides(
    security_cases: dict[str, object],
) -> None:
    assert build_worker_environment() == {
        "PATH": os.defpath,
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
    }
    cases = security_cases["environment_cases"]
    assert isinstance(cases, list)
    for case in cases:
        assert isinstance(case, dict)
        with pytest.raises(SecurityViolation) as caught:
            build_worker_environment(case["overrides"])
        assert caught.value.code == case["expected_code"]
        assert "CANARY-MUST-NOT-LEAK" not in str(caught.value)
        assert "/tmp/shadowed-runtime" not in str(caught.value)


def test_every_resource_budget_excess_fails_closed_with_a_stable_code(
    security_cases: dict[str, object],
) -> None:
    policy_value = security_cases["resource_policy"]
    assert isinstance(policy_value, dict)
    policy = ResourcePolicy.from_mapping(policy_value)
    cases = security_cases["resource_cases"]
    assert isinstance(cases, list)

    for case in cases:
        assert isinstance(case, dict)
        observation_value = case["observation"]
        assert isinstance(observation_value, dict)
        observation = ResourceObservation(**observation_value)
        with pytest.raises(SecurityViolation) as caught:
            enforce_resource_policy(policy, observation)
        assert caught.value.code == case["expected_code"]

    enforce_resource_policy(
        policy,
        ResourceObservation(
            elapsed_seconds=1.0,
            memory_bytes=64 * 1024 * 1024,
            process_count=2,
            log_bytes=16,
            artifact_bytes=32,
        ),
    )

    invalid_policy = {**policy_value, "pid_limit": 1.5}
    with pytest.raises(SecurityViolation) as policy_error:
        ResourcePolicy.from_mapping(invalid_policy)
    assert policy_error.value.code == "invalid_resource_policy"
    with pytest.raises(SecurityViolation) as observation_error:
        ResourceObservation(
            elapsed_seconds=0,
            memory_bytes=0,
            process_count=-1,
            log_bytes=0,
            artifact_bytes=0,
        )
    assert observation_error.value.code == "invalid_resource_observation"


def test_security_gate_fails_closed_for_deep_and_oversized_untrusted_input(
    tmp_path: Path,
) -> None:
    value = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    value["backend_extensions"]["extensions"]["future"] = {
        "schema_version": "future/v1",
        "options": {"a": {"b": {"c": {"d": 1}}}},
    }
    deep = tmp_path / "deep.json"
    deep.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(SecurityViolation) as depth_error:
        load_untrusted_scenario(deep, limits=InputLimits(max_depth=8))
    assert depth_error.value.code == "max_depth_exceeded"

    oversized = tmp_path / "oversized.json"
    oversized.write_bytes(EXAMPLE.read_bytes())
    with pytest.raises(SecurityViolation) as size_error:
        load_untrusted_scenario(oversized, limits=InputLimits(byte_limit=64))
    assert size_error.value.code == "byte_limit_exceeded"


def test_snapshot_and_staging_paths_reject_escape_overlap_links_and_special_files(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    input_snapshot = workspace / "input" / "input-run-attempt"
    output_staging = workspace / "staging" / "staging-run-attempt"
    input_snapshot.mkdir(parents=True)
    output_staging.mkdir(parents=True)

    validate_isolated_directories(input_snapshot, output_staging, workspace=workspace)

    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(SecurityViolation) as escape_error:
        validate_isolated_directories(outside, output_staging, workspace=workspace)
    assert escape_error.value.code == "path_boundary_escape"

    with pytest.raises(SecurityViolation) as overlap_error:
        validate_isolated_directories(input_snapshot, input_snapshot, workspace=workspace)
    assert overlap_error.value.code == "path_overlap"

    linked = workspace / "linked-input"
    linked.symlink_to(outside, target_is_directory=True)
    with pytest.raises(SecurityViolation) as link_error:
        validate_isolated_directories(linked, output_staging, workspace=workspace)
    assert link_error.value.code == "link_or_special_file"

    if hasattr(os, "mkfifo"):
        fifo = output_staging / "worker.fifo"
        os.mkfifo(fifo)
        with pytest.raises(SecurityViolation) as fifo_error:
            validate_isolated_directories(input_snapshot, output_staging, workspace=workspace)
        assert fifo_error.value.code == "link_or_special_file"


def test_frozen_snapshot_tampering_is_rejected_before_worker_or_publication(
    tmp_path: Path,
) -> None:
    bundle = ScenarioCompiler().compile(instantiate_scenario(load_scenario(EXAMPLE)))
    prepared = prepare_run(
        bundle,
        workspace=tmp_path,
        project_root=ROOT,
        run_id="run-tampered-snapshot",
        attempt_id="attempt-0001",
    )
    assert verify_snapshot_binding(
        prepared.input_snapshot_path,
        expected_digest=prepared.run_request.input_snapshot_digest,
    ) == prepared.run_request.input_snapshot_digest

    report = prepared.input_snapshot_path / "compile_report.json"
    report.chmod(0o644)
    report.write_bytes(report.read_bytes() + b" ")

    with pytest.raises(SecurityViolation) as caught:
        verify_snapshot_binding(
            prepared.input_snapshot_path,
            expected_digest=prepared.run_request.input_snapshot_digest,
        )
    assert caught.value.code == "snapshot_tampered"
    assert not prepared.published_path.exists()


def test_output_artifacts_reject_tampering_links_special_files_and_size_excess(
    tmp_path: Path,
) -> None:
    staging = tmp_path / "staging"
    staging.mkdir()
    artifact = staging / "events.json"
    artifact.write_bytes(b'[{"tick":0,"type":"started"}]')
    original_digest = hashlib.sha256(artifact.read_bytes()).hexdigest()

    verified = verify_output_artifacts(
        staging,
        required_names=("events.json",),
        max_file_bytes=64,
        artifact_limit_bytes=64,
        expected_digests={"events.json": original_digest},
    )
    assert verified == (
        ArtifactVerification(
            path="events.json",
            size_bytes=29,
            digest=original_digest,
            validation="verified",
        ),
    )
    assert verified[0].to_dict() == {
        "path": "events.json",
        "size_bytes": 29,
        "digest": original_digest,
        "validation": "verified",
    }

    artifact.write_bytes(b'[{"tick":1,"type":"tampered"}]')
    with pytest.raises(SecurityViolation) as tamper_error:
        verify_output_artifacts(
            staging,
            required_names=("events.json",),
            max_file_bytes=64,
            artifact_limit_bytes=64,
            expected_digests={"events.json": original_digest},
        )
    assert tamper_error.value.code == "artifact_digest_mismatch"

    artifact.unlink()
    artifact.symlink_to(EXAMPLE)
    with pytest.raises(SecurityViolation) as link_error:
        verify_output_artifacts(
            staging,
            required_names=("events.json",),
            max_file_bytes=64,
            artifact_limit_bytes=64,
        )
    assert link_error.value.code == "link_or_special_file"

    artifact.unlink()
    artifact.write_bytes(b"[" + b"0," * 64 + b"0]")
    with pytest.raises(SecurityViolation) as size_error:
        verify_output_artifacts(
            staging,
            required_names=("events.json",),
            max_file_bytes=64,
            artifact_limit_bytes=64,
        )
    assert size_error.value.code == "artifact_size_limit_exceeded"


def test_logs_remove_canary_host_path_and_secret_assignment_before_truncation() -> None:
    canary = "CANARY-MUST-NOT-LEAK"
    raw = f"token=visible {canary} {ROOT}/private.json " + "x" * 200

    result = redact_log(
        raw,
        sensitive_values=(canary,),
        redacted_paths=(ROOT,),
        limit_bytes=96,
    )

    assert result.truncated is True
    assert len(result.text.encode("utf-8")) <= 96
    assert canary not in result.text
    assert str(ROOT) not in result.text
    assert "token=visible" not in result.text
    assert "token=<redacted>" in result.text
    assert "<project>/private.json" in result.text
    assert result.text.endswith("<truncated>")

    tiny = redact_log("secret=visible", limit_bytes=4)
    assert tiny.truncated is True
    assert len(tiny.text.encode("utf-8")) <= 4
    assert "visible" not in tiny.text


def test_real_process_group_observation_drives_resource_failure(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "events.json").write_bytes(b"[]")
    script = (
        "import subprocess,sys,time;"
        "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);"
        "print(child.pid,flush=True);"
        "time.sleep(60)"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    assert process.stdout is not None
    child_pid = int(process.stdout.readline().strip())
    started_at = time.monotonic()
    try:
        observed = observe_process_group(
            process.pid,
            started_at=started_at,
            log_bytes=7,
            artifact_root=staging,
        )

        assert observed.process_count == 2
        assert observed.memory_bytes > 0
        assert observed.elapsed_seconds >= 0
        assert observed.log_bytes == 7
        assert observed.artifact_bytes == 2
        policy = ResourcePolicy(
            wall_clock_timeout_s=60,
            memory_limit_mb=1_000_000,
            pid_limit=1,
            log_limit_bytes=1_000,
            artifact_limit_bytes=1_000,
        )
        with pytest.raises(SecurityViolation) as caught:
            enforce_resource_policy(policy, observed)
        assert caught.value.code == "pid_limit_exceeded"
    finally:
        evidence = terminate_process_tree(process, trigger="resource_limit_exceeded")
    assert evidence.observed_pids == (process.pid, child_pid)
    assert evidence.complete is True
