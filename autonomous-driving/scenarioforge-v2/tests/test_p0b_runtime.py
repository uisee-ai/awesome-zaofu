from __future__ import annotations

import re
import subprocess
import sys
import threading
import tomllib
from pathlib import Path

import pytest

from scenarioforge.core import ScenarioCompiler, instantiate_scenario, load_scenario
from scenarioforge.core.models import EnvironmentFingerprint
from scenarioforge.failsafe import FailureOutcome, live_process_group_members
from scenarioforge.runtime import RunSupervisor
from scenarioforge.web import (
    ExecutionState,
    InvalidIdentifierError,
    RunCoordinator,
    SlotOccupiedError,
    UnknownScenarioError,
)


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "p0a" / "brake_lead.json"
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class BlockingApplication:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.started = threading.Event()
        self.release = threading.Event()
        self.interrupted = threading.Event()

    def run_single(
        self,
        scenario_path: Path | str,
        *,
        run_id: str,
        attempt_id: str,
        timeout_seconds: int,
    ) -> object:
        self.calls.append(
            {
                "scenario_path": Path(scenario_path),
                "run_id": run_id,
                "attempt_id": attempt_id,
                "timeout_seconds": timeout_seconds,
            }
        )
        self.started.set()
        if not self.release.wait(timeout=3):
            raise TimeoutError("test application was not released")
        return object()

    def interrupt_active_for_shutdown(self) -> bool:
        self.interrupted.set()
        return True


def _coordinator(tmp_path: Path, application: BlockingApplication) -> RunCoordinator:
    return RunCoordinator(
        workspace=tmp_path,
        project_root=ROOT,
        timeout_seconds=17,
        application=application,
    )


def test_idle_start_uses_only_registered_scenario_and_safe_generated_ids(
    tmp_path: Path,
) -> None:
    application = BlockingApplication()
    coordinator = _coordinator(tmp_path, application)

    with pytest.raises(UnknownScenarioError, match="unknown scenario_id"):
        coordinator.start("not_registered", idempotency_key="request-unknown")
    with pytest.raises(InvalidIdentifierError, match="scenario_id"):
        coordinator.start("../brake_lead", idempotency_key="request-traversal")
    with pytest.raises(InvalidIdentifierError, match="idempotency_key"):
        coordinator.start("brake_lead", idempotency_key="../../escape")

    reference = coordinator.start("brake_lead", idempotency_key="request-safe-0001")
    try:
        assert application.started.wait(timeout=1)
        assert SAFE_ID.fullmatch(reference.run_id)
        assert SAFE_ID.fullmatch(reference.attempt_id)
        assert reference.run_id != reference.attempt_id
        assert reference.to_dict() == {
            "schema_version": "scenarioforge.run-reference/v1",
            "scenario_id": "brake_lead",
            "run_id": reference.run_id,
            "attempt_id": reference.attempt_id,
            "published_ref": f"published/{reference.run_id}/{reference.attempt_id}",
        }
        assert application.calls == [
            {
                "scenario_path": EXAMPLE,
                "run_id": reference.run_id,
                "attempt_id": reference.attempt_id,
                "timeout_seconds": 17,
            }
        ]
    finally:
        application.release.set()
        coordinator.wait_for_terminal(reference.run_id, timeout=2)


def test_same_key_is_idempotent_and_an_occupied_slot_is_http_409_compatible(
    tmp_path: Path,
) -> None:
    application = BlockingApplication()
    coordinator = _coordinator(tmp_path, application)
    reference = coordinator.start("brake_lead", idempotency_key="request-idempotent")
    try:
        assert application.started.wait(timeout=1)

        retry = coordinator.start(
            "brake_lead", idempotency_key="request-idempotent"
        )
        assert retry == reference
        with pytest.raises(SlotOccupiedError) as conflict:
            coordinator.start("brake_lead", idempotency_key="request-other")

        assert conflict.value.status_code == 409
        assert conflict.value.active_reference == reference
        assert len(application.calls) == 1
    finally:
        application.release.set()
        coordinator.wait_for_terminal(reference.run_id, timeout=2)


def test_active_state_is_bounded_ephemeral_and_client_lifecycle_independent(
    tmp_path: Path,
) -> None:
    application = BlockingApplication()
    coordinator = _coordinator(tmp_path, application)
    reference = coordinator.start("brake_lead", idempotency_key="request-refresh")
    try:
        assert application.started.wait(timeout=1)

        first_poll = coordinator.active_state(reference.run_id)
        refreshed_poll = coordinator.active_state(reference.run_id)
        assert first_poll is not None
        assert refreshed_poll == first_poll
        assert refreshed_poll.to_dict() == {
            "schema_version": "scenarioforge.execution-state/v1",
            "scenario_id": "brake_lead",
            "run_id": reference.run_id,
            "attempt_id": reference.attempt_id,
            "state": "running",
            "terminal": False,
        }
        assert "run_result" not in refreshed_poll.to_dict()
        assert coordinator.reference(reference.run_id) == reference
        assert not application.release.is_set()
    finally:
        application.release.set()

    assert coordinator.wait_for_terminal(reference.run_id, timeout=2) == reference
    assert coordinator.active_state(reference.run_id) is None
    assert coordinator.reference(reference.run_id) == reference


def test_service_shutdown_state_is_ephemeral_and_not_a_client_terminal(
    tmp_path: Path,
) -> None:
    application = BlockingApplication()
    coordinator = _coordinator(tmp_path, application)
    reference = coordinator.start("brake_lead", idempotency_key="request-shutdown")
    try:
        assert application.started.wait(timeout=1)

        assert coordinator.interrupt_active_for_shutdown() is True
        assert application.interrupted.is_set()
        state = coordinator.active_state(reference.run_id)
        assert state is not None
        assert state.to_dict() == {
            "schema_version": "scenarioforge.execution-state/v1",
            "scenario_id": "brake_lead",
            "run_id": reference.run_id,
            "attempt_id": reference.attempt_id,
            "state": "stopping",
            "terminal": False,
        }
        with pytest.raises(ValueError, match="non-terminal active states"):
            ExecutionState(
                schema_version="scenarioforge.execution-state/v1",
                scenario_id="brake_lead",
                run_id=reference.run_id,
                attempt_id=reference.attempt_id,
                state="failed",
                terminal=True,
            )
    finally:
        application.release.set()
        coordinator.wait_for_terminal(reference.run_id, timeout=2)


@pytest.fixture(scope="module")
def exact_bundle():
    instance = instantiate_scenario(load_scenario(EXAMPLE))
    return ScenarioCompiler().compile(instance)


@pytest.mark.parametrize(
    ("failure_mode", "expected_status", "expected_reason", "expected_exit_code"),
    [
        ("timeout", "timeout", "timeout", -15),
        ("crash", "failed", "worker_crashed", 17),
    ],
)
def test_supervisor_closes_the_complete_tree_and_publishes_failure(
    tmp_path: Path,
    exact_bundle,
    monkeypatch: pytest.MonkeyPatch,
    failure_mode: str,
    expected_status: str,
    expected_reason: str,
    expected_exit_code: int,
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
    real_popen = subprocess.Popen
    if failure_mode == "timeout":
        script = (
            "import subprocess,sys,time;"
            "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],"
            "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);"
            "print(child.pid,flush=True);"
            "time.sleep(60)"
        )
        timeout_seconds = 0.05
    else:
        script = (
            "import subprocess,sys;"
            "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],"
            "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);"
            "print(child.pid,flush=True);"
            "raise SystemExit(17)"
        )
        timeout_seconds = 1

    def controlled_popen(_command: object, **kwargs: object) -> subprocess.Popen[str]:
        return real_popen([sys.executable, "-c", script], **kwargs)

    monkeypatch.setattr(
        "scenarioforge.runtime.supervisor.subprocess.Popen", controlled_popen
    )
    supervisor = RunSupervisor(workspace=tmp_path, project_root=ROOT)

    outcome = supervisor.run(
        exact_bundle,
        run_id=f"run-{failure_mode}",
        attempt_id="attempt-0001",
        timeout_seconds=timeout_seconds,
    )

    assert isinstance(outcome, FailureOutcome)
    child_pid = int(outcome.failure_evidence["logs"]["stdout"].strip())
    assert child_pid in outcome.termination.observed_pids
    assert outcome.termination.remaining_pids == ()
    assert outcome.termination.complete is True
    assert live_process_group_members(outcome.termination.process_group_id) == ()
    assert outcome.run_result.to_dict() == {
        "schema_version": "scenarioforge.run-result/v1",
        "run_id": f"run-{failure_mode}",
        "attempt_id": "attempt-0001",
        "status": expected_status,
        "reason": expected_reason,
        "worker_exit_code": expected_exit_code,
        "run_manifest_digest": outcome.run_result.run_manifest_digest,
        "compile_report_digest": outcome.run_result.compile_report_digest,
        "execution_plan_digest": outcome.run_result.execution_plan_digest,
        "artifact_index_digest": outcome.run_result.artifact_index_digest,
    }
    assert (outcome.published_path / expected_status.upper()).is_file()
    assert not (outcome.published_path / "SUCCESS").exists()


def test_web_runtime_dependencies_are_exactly_pinned() -> None:
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert metadata["dependency-groups"]["web"] == [
        "starlette==1.3.1",
        "uvicorn==0.52.1",
    ]
    assert metadata["dependency-groups"]["browser"] == ["playwright==1.61.0"]
    assert metadata["tool"]["uv"]["default-groups"] == [
        "dev",
        "web",
        "browser",
        "simulation",
    ]
    assert metadata["tool"]["scenarioforge"]["web"] == {
        "threejs_version": "0.185.1",
    }
