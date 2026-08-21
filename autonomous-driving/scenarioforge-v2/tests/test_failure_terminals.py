from __future__ import annotations

import hashlib
import json
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from scenarioforge.core import ScenarioCompiler, canonical_bytes, instantiate_scenario, load_scenario
from scenarioforge.failsafe import (
    FailureController,
    FailureKind,
    FailurePublicationError,
    ProcessTreeIsolationError,
    TerminalStatus,
    TerminationEvidence,
    create_run_result,
    live_process_group_members,
    publish_failure,
    terminate_process_tree,
)
from scenarioforge.runtime.snapshot import INPUT_FILES, prepare_run


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "p0a" / "brake_lead.json"


BASE_RESULT = {
    "schema_version": "scenarioforge.run-result/v1",
    "run_id": "run-failure-0001",
    "attempt_id": "attempt-0001",
    "status": "failed",
    "reason": "worker_crashed",
    "worker_exit_code": 17,
    "run_manifest_digest": "1" * 64,
    "compile_report_digest": "2" * 64,
    "execution_plan_digest": "3" * 64,
    "artifact_index_digest": "4" * 64,
}


def _read(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def exact_bundle():
    instance = instantiate_scenario(load_scenario(EXAMPLE))
    return ScenarioCompiler().compile(instance)


def test_run_result_accepts_only_the_three_public_terminal_states() -> None:
    for status in TerminalStatus:
        result = create_run_result(
            **{
                **BASE_RESULT,
                "status": status.value,
                "reason": f"terminal_{status.value}",
            }
        )

        assert result.to_dict() == {
            **BASE_RESULT,
            "status": status.value,
            "reason": f"terminal_{status.value}",
        }

    for forbidden in ("starting", "running", "stopping", "cancelled"):
        with pytest.raises(ValueError, match="public terminal status"):
            create_run_result(**{**BASE_RESULT, "status": forbidden})


def test_run_result_keeps_run_attempt_and_comparison_id_semantics_separate() -> None:
    with pytest.raises(ValueError, match="run_id and attempt_id"):
        create_run_result(
            **{
                **BASE_RESULT,
                "run_id": "same-identity",
                "attempt_id": "same-identity",
            }
        )

    result = create_run_result(**BASE_RESULT)

    assert result.run_id == "run-failure-0001"
    assert result.attempt_id == "attempt-0001"
    assert "comparison_id" not in result.to_dict()


def test_complete_process_tree_is_terminated_with_replayable_evidence() -> None:
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

    evidence = terminate_process_tree(process, trigger="worker_crashed")

    assert evidence.to_dict() == {
        "schema_version": "scenarioforge.process-tree-termination/v1",
        "trigger": "worker_crashed",
        "process_group_id": process.pid,
        "observed_pids": [process.pid, child_pid],
        "signals_sent": ["SIGTERM"],
        "remaining_pids": [],
        "complete": True,
    }
    assert process.wait(timeout=1) == -15
    assert live_process_group_members(process.pid) == ()


def test_process_tree_terminator_rejects_a_nonisolated_process_group() -> None:
    process = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(60)"])
    try:
        with pytest.raises(ProcessTreeIsolationError, match="isolated process group"):
            terminate_process_tree(process, trigger="worker_crashed")
        assert process.poll() is None
    finally:
        process.terminate()
        process.wait(timeout=1)


@pytest.mark.parametrize(
    ("kind", "expected_status", "stage"),
    [
        (FailureKind.WORKER_CRASHED, "failed", "worker_execution"),
        (FailureKind.TIMEOUT, "timeout", "worker_execution"),
        (FailureKind.RESOURCE_LIMIT, "failed", "resource_monitor"),
        (FailureKind.ARTIFACT_VALIDATION, "failed", "artifact_validation"),
        (FailureKind.OPERATOR_INTERRUPTED, "failed", "operator_interruption"),
    ],
)
def test_each_failure_atomically_publishes_minimum_evidence_without_success(
    tmp_path: Path,
    exact_bundle,
    kind: FailureKind,
    expected_status: str,
    stage: str,
) -> None:
    prepared = prepare_run(
        exact_bundle,
        workspace=tmp_path,
        project_root=ROOT,
        run_id=f"run-{kind.value}",
        attempt_id="attempt-0001",
    )
    if kind is FailureKind.ARTIFACT_VALIDATION:
        (prepared.output_staging_path / "metrics.json").write_bytes(b"{")
    else:
        (prepared.output_staging_path / "events.json").write_bytes(
            canonical_bytes([{"type": "worker_started", "tick": 0}])
        )
    termination = TerminationEvidence(
        schema_version="scenarioforge.process-tree-termination/v1",
        trigger=kind.value,
        process_group_id=4321,
        observed_pids=(4321, 4322),
        signals_sent=("SIGTERM", "SIGKILL"),
        remaining_pids=(),
        complete=True,
    )

    outcome = publish_failure(
        prepared,
        kind=kind,
        stage=stage,
        worker_exit_code=17,
        termination=termination,
        stdout="worker stopped",
        stderr=f"token=top-secret at {ROOT}/private.json",
        sensitive_values=("top-secret",),
        redacted_paths=(ROOT,),
    )

    published = outcome.published_path
    result = _read(published / "run_result.json")
    index = _read(published / "artifact_index.json")
    evidence = _read(published / "failure_evidence.json")
    marker_name = expected_status.upper()
    marker = _read(published / marker_name)

    assert result == {
        "schema_version": "scenarioforge.run-result/v1",
        "run_id": f"run-{kind.value}",
        "attempt_id": "attempt-0001",
        "status": expected_status,
        "reason": kind.value,
        "worker_exit_code": 17,
        "run_manifest_digest": prepared.run_request.run_manifest_digest,
        "compile_report_digest": exact_bundle.report.digest,
        "execution_plan_digest": prepared.run_request.execution_plan_digest,
        "artifact_index_digest": outcome.artifact_index.digest,
    }
    assert result == outcome.run_result.to_dict()
    assert set(result) == set(BASE_RESULT)
    assert "comparison_id" not in result
    assert not (published / "SUCCESS").exists()
    assert not (published / "CANCELLED").exists()
    assert marker == {
        "schema_version": "scenarioforge.completion-marker/v1",
        "status": expected_status,
        "run_result_digest": _digest(published / "run_result.json"),
        "artifact_index_digest": _digest(published / "artifact_index.json"),
        "failure_evidence_digest": _digest(published / "failure_evidence.json"),
    }

    assert evidence == {
        "schema_version": "scenarioforge.failure-evidence/v1",
        "run_id": f"run-{kind.value}",
        "attempt_id": "attempt-0001",
        "failure_kind": kind.value,
        "failure_stage": stage,
        "reason": kind.value,
        "worker_exit_code": 17,
        "termination": termination.to_dict(),
        "logs": {
            "stdout": "worker stopped",
            "stderr": "token=<redacted> at <project>/private.json",
            "truncated": False,
        },
        "frozen_evidence": {
            "run_manifest": {
                "ref": "input/run_manifest.json",
                "digest": prepared.run_request.run_manifest_digest,
            },
            "compile_report": {
                "ref": "input/compile_report.json",
                "digest": exact_bundle.report.digest,
            },
            "execution_plan": {
                "ref": "input/execution_plan.json",
                "digest": prepared.run_request.execution_plan_digest,
            },
        },
        "partial_artifacts": [
            entry
            for entry in index["artifacts"]
            if entry["path"].startswith("output/")
        ],
        "missing_artifacts": [
            entry["path"]
            for entry in index["artifacts"]
            if entry["status"] == "missing"
        ],
    }

    expected_paths = [f"input/{name}" for name in INPUT_FILES]
    expected_paths += ["failure_evidence.json"]
    expected_paths += [
        "output/actions.json",
        "output/events.json",
        "output/metrics.json",
        "output/trajectory.json",
        "output/worker_result.json",
    ]
    assert [entry["path"] for entry in index["artifacts"]] == sorted(expected_paths)
    for entry in index["artifacts"]:
        assert set(entry) == {"path", "status", "size_bytes", "digest", "validation"}
    output_entries = {
        entry["path"]: entry for entry in index["artifacts"] if entry["path"].startswith("output/")
    }
    expected_partial = "output/metrics.json" if kind is FailureKind.ARTIFACT_VALIDATION else "output/events.json"
    assert output_entries[expected_partial]["status"] == (
        "invalid" if kind is FailureKind.ARTIFACT_VALIDATION else "present"
    )
    assert {
        path for path, entry in output_entries.items() if entry["status"] == "missing"
    } == set(output_entries) - {expected_partial}
    assert not prepared.output_staging_path.exists()
    assert not published.with_name(f".{published.name}.publishing").exists()
    for path in published.rglob("*"):
        assert not path.is_symlink()
        assert not (path.stat().st_mode & stat.S_IWUSR)


def test_failure_publication_refuses_incomplete_process_tree_cleanup(
    tmp_path: Path, exact_bundle
) -> None:
    prepared = prepare_run(
        exact_bundle,
        workspace=tmp_path,
        project_root=ROOT,
        run_id="run-live-child",
        attempt_id="attempt-0001",
    )
    incomplete = TerminationEvidence(
        schema_version="scenarioforge.process-tree-termination/v1",
        trigger="timeout",
        process_group_id=99,
        observed_pids=(99, 100),
        signals_sent=("SIGTERM", "SIGKILL"),
        remaining_pids=(100,),
        complete=False,
    )

    with pytest.raises(FailurePublicationError, match="process tree"):
        publish_failure(
            prepared,
            kind=FailureKind.TIMEOUT,
            stage="worker_execution",
            worker_exit_code=-9,
            termination=incomplete,
        )

    assert not prepared.published_path.exists()


@pytest.mark.parametrize("kind", list(FailureKind))
def test_failure_controller_always_cleans_tree_before_terminal_publication(
    tmp_path: Path,
    exact_bundle,
    kind: FailureKind,
) -> None:
    prepared = prepare_run(
        exact_bundle,
        workspace=tmp_path,
        project_root=ROOT,
        run_id=f"run-controlled-{kind.value}",
        attempt_id="attempt-0001",
    )
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

    outcome = FailureController().close(
        prepared,
        process=process,
        kind=kind,
        stage="operator_interruption" if kind is FailureKind.OPERATOR_INTERRUPTED else "worker_execution",
    )

    assert outcome.termination.observed_pids == (process.pid, child_pid)
    assert outcome.termination.remaining_pids == ()
    assert outcome.termination.complete is True
    assert outcome.run_result.status == kind.terminal_status.value
    assert outcome.run_result.worker_exit_code == -15
    assert (outcome.published_path / outcome.run_result.status.upper()).is_file()
    assert not (outcome.published_path / "SUCCESS").exists()
