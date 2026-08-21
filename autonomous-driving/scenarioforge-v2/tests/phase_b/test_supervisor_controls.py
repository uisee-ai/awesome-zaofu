from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from scenarioforge.core import ScenarioCompiler, instantiate_scenario, load_scenario
from scenarioforge.core.models import EnvironmentFingerprint
from scenarioforge.failsafe import FailureOutcome, live_process_group_members
from scenarioforge.orchestration.publication import CancellationOutcome
from scenarioforge.runtime.contracts import RunResult
from scenarioforge.runtime.supervisor import RunSupervisor


ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "p0a" / "brake_lead.json"


def _fingerprint() -> EnvironmentFingerprint:
    return EnvironmentFingerprint(
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


def _wait_for(predicate, *, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError("condition did not become true")
        time.sleep(0.01)


def test_run_result_v4_requires_cancel_command_cleanup_and_statistics_exclusion() -> None:
    result = RunResult(
        schema_version="scenarioforge.run-result/v4",
        run_id="run-0001",
        attempt_id="attempt-0001",
        status="cancelled",
        reason="user_cancelled",
        worker_exit_code=-15,
        run_manifest_digest="a" * 64,
        compile_report_digest="b" * 64,
        execution_plan_digest="c" * 64,
        artifact_index_digest="d" * 64,
        execution_status="cancelled",
        scenario_outcome="not_applicable",
        termination_reason="user_cancelled",
        traceability_digest="e" * 64,
        scenario_revision_digest="f" * 64,
        control_command={
            "schema_version": "scenarioforge.control-command/v1",
            "command_id": "command-stop-0001",
            "operation": "stop",
            "reason": "user_cancelled",
        },
        process_tree_cleanup={
            "schema_version": "scenarioforge.process-tree-termination/v1",
            "complete": True,
            "remaining_pids": [],
        },
        statistics_eligible=False,
    )

    assert result.to_dict() == {
        "schema_version": "scenarioforge.run-result/v4",
        "run_id": "run-0001",
        "attempt_id": "attempt-0001",
        "status": "cancelled",
        "reason": "user_cancelled",
        "worker_exit_code": -15,
        "run_manifest_digest": "a" * 64,
        "compile_report_digest": "b" * 64,
        "execution_plan_digest": "c" * 64,
        "artifact_index_digest": "d" * 64,
        "execution_status": "cancelled",
        "scenario_outcome": "not_applicable",
        "termination_reason": "user_cancelled",
        "traceability_digest": "e" * 64,
        "scenario_revision_digest": "f" * 64,
        "control_command": {
            "schema_version": "scenarioforge.control-command/v1",
            "command_id": "command-stop-0001",
            "operation": "stop",
            "reason": "user_cancelled",
        },
        "process_tree_cleanup": {
            "schema_version": "scenarioforge.process-tree-termination/v1",
            "complete": True,
            "remaining_pids": [],
        },
        "statistics_eligible": False,
    }


def test_real_supervisor_controls_and_cancellation_close_complete_process_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = ScenarioCompiler().compile(instantiate_scenario(load_scenario(EXAMPLE)))
    monkeypatch.setattr(
        "scenarioforge.runtime.snapshot.environment_fingerprint",
        lambda _lockfile: _fingerprint(),
    )
    monkeypatch.setattr(
        "scenarioforge.runtime.snapshot.importlib.metadata.version",
        lambda name: {"jsonschema": "4.25.1", "metadrive-simulator": "0.4.3"}[name],
    )
    real_popen = subprocess.Popen
    script = (
        "import subprocess,sys,time;"
        "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],"
        "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);"
        "print(child.pid,flush=True);"
        "time.sleep(60)"
    )

    def controlled_popen(_command: object, **kwargs: object) -> subprocess.Popen[str]:
        return real_popen([sys.executable, "-c", script], **kwargs)

    monkeypatch.setattr(
        "scenarioforge.runtime.supervisor.subprocess.Popen", controlled_popen
    )
    supervisor = RunSupervisor(workspace=tmp_path, project_root=ROOT)
    captured: dict[str, object] = {}

    def execute() -> None:
        captured["outcome"] = supervisor.run(
            bundle,
            run_id="run-controlled",
            attempt_id="attempt-0001",
            timeout_seconds=10,
        )

    thread = threading.Thread(target=execute)
    thread.start()
    _wait_for(lambda: supervisor.active_process_group_id is not None)
    process_group_id = supervisor.active_process_group_id
    assert process_group_id is not None

    assert supervisor.pause_active() is True
    assert supervisor.pause_active() is True
    assert supervisor.step_active(quantum_seconds=0.02) is True
    assert supervisor.resume_active() is True
    assert supervisor.resume_active() is True
    assert supervisor.cancel_active(
        command_id="command-stop-0001", reason="user_cancelled"
    ) is True
    thread.join(timeout=5)

    assert not thread.is_alive()
    outcome = captured["outcome"]
    assert isinstance(outcome, CancellationOutcome)
    assert outcome.run_result.schema_version == "scenarioforge.run-result/v4"
    assert outcome.run_result.status == "cancelled"
    assert outcome.run_result.statistics_eligible is False
    assert outcome.termination.complete is True
    assert outcome.termination.remaining_pids == ()
    assert live_process_group_members(process_group_id) == ()
    assert outcome.run_result.control_command == {
        "schema_version": "scenarioforge.control-command/v1",
        "command_id": "command-stop-0001",
        "operation": "stop",
        "reason": "user_cancelled",
    }
    published = tmp_path / "published" / "run-controlled" / "attempt-0001"
    evidence = json.loads(
        (published / "cancellation_evidence.json").read_text(encoding="utf-8")
    )
    assert evidence["command"] == outcome.run_result.control_command
    assert evidence["termination"]["remaining_pids"] == []
    assert evidence["statistics_eligible"] is False
    assert (published / "CANCELLED").is_file()
    assert not (published / "FAILED").exists()
    assert not (published / "SUCCESS").exists()


def test_interactive_readiness_window_does_not_extend_frozen_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = ScenarioCompiler().compile(instantiate_scenario(load_scenario(EXAMPLE)))
    monkeypatch.setattr(
        "scenarioforge.runtime.snapshot.environment_fingerprint",
        lambda _lockfile: _fingerprint(),
    )
    monkeypatch.setattr(
        "scenarioforge.runtime.snapshot.importlib.metadata.version",
        lambda name: {"jsonschema": "4.25.1", "metadrive-simulator": "0.4.3"}[name],
    )
    real_popen = subprocess.Popen

    def controlled_popen(_command: object, **kwargs: object) -> subprocess.Popen[str]:
        return real_popen([sys.executable, "-c", "import time;time.sleep(60)"], **kwargs)

    monkeypatch.setattr(
        "scenarioforge.runtime.supervisor.subprocess.Popen", controlled_popen
    )
    supervisor = RunSupervisor(workspace=tmp_path, project_root=ROOT)
    process_groups: list[int] = []

    started_at = time.monotonic()
    outcome = supervisor.run(
        bundle,
        run_id="run-interactive-timeout",
        attempt_id="attempt-0001",
        timeout_seconds=0.05,
        process_started=process_groups.append,
    )
    elapsed = time.monotonic() - started_at

    assert isinstance(outcome, FailureOutcome)
    assert outcome.run_result.status == "timeout"
    assert process_groups == [outcome.termination.process_group_id]
    assert elapsed < 1.0
