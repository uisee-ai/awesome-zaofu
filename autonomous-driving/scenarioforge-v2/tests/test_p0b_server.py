from __future__ import annotations

import json
import signal
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from starlette.testclient import TestClient
from uvicorn import Config

from scenarioforge import __main__ as cli
from scenarioforge.core.models import EnvironmentFingerprint
from scenarioforge.failsafe import live_process_group_members
from scenarioforge.web.api import ScenarioForgeAPI
from scenarioforge.web.coordinator import RunCoordinator
from scenarioforge.web.evidence import PublishedEvidenceReader
from scenarioforge.web import server as server_module
from scenarioforge.web.server import (
    CONTENT_SECURITY_POLICY,
    LOOPBACK_HOST,
    LoopbackServer,
    create_app,
)


PORT = 7419
ORIGIN = f"http://127.0.0.1:{PORT}"
CSRF_TOKEN = "test-token-abcdefghijklmnopqrstuvwxyz-0123456789"
ROOT = Path(__file__).resolve().parents[1]


@dataclass
class FakeAPI:
    calls: list[tuple[object, ...]] = field(default_factory=list)

    def get_catalog(self) -> dict[str, object]:
        self.calls.append(("catalog",))
        return {
            "schema_version": "scenarioforge.scenario-catalog/v1",
            "scenarios": [{"scenario_id": "brake_lead"}],
        }

    def start_run(self, scenario_id: str, *, idempotency_key: str) -> dict[str, object]:
        self.calls.append(("start", scenario_id, idempotency_key))
        return {
            "schema_version": "scenarioforge.run-reference/v1",
            "scenario_id": scenario_id,
            "run_id": "run-safe-0001",
            "attempt_id": "attempt-0001",
            "published_ref": "published/run-safe-0001/attempt-0001",
        }

    def get_run_status(self, run_id: str) -> dict[str, object]:
        self.calls.append(("status", run_id))
        return {
            "schema_version": "scenarioforge.execution-state/v1",
            "run_id": run_id,
            "state": "running",
            "terminal": False,
        }

    def get_run_artifact(self, run_id: str, artifact_key: str) -> dict[str, object]:
        self.calls.append(("artifact", run_id, artifact_key))
        return {
            "schema_version": "scenarioforge.playback/v1",
            "run_id": run_id,
            "artifact_key": artifact_key,
        }


@dataclass
class FakeCoordinator:
    active: bool = False
    interrupt_calls: int = 0
    waited_for: list[tuple[str, float | None]] = field(default_factory=list)

    def interrupt_active_for_shutdown(self) -> bool:
        self.interrupt_calls += 1
        return self.active

    def wait_for_terminal(self, run_id: str, *, timeout: float | None = None) -> object:
        self.waited_for.append((run_id, timeout))
        return object()


def _client(api: FakeAPI | None = None) -> tuple[TestClient, FakeAPI]:
    selected_api = api or FakeAPI()
    app = create_app(
        api=selected_api,
        coordinator=FakeCoordinator(),
        port=PORT,
        csrf_token=CSRF_TOKEN,
    )
    return TestClient(app, base_url=ORIGIN), selected_api


def _state_headers(**extra: str) -> dict[str, str]:
    return {
        "Origin": ORIGIN,
        "X-CSRF-Token": CSRF_TOKEN,
        "Idempotency-Key": "request-safe-0001",
        **extra,
    }


def test_host_authority_accepts_only_configured_loopback_service() -> None:
    client, _ = _client()

    allowed = client.get("/api/session")
    hostile = client.get("/api/session", headers={"Host": "attacker.example"})
    wrong_port = client.get(
        "/api/session", headers={"Host": "127.0.0.1:7420"}
    )

    assert allowed.status_code == 200
    assert hostile.status_code == 400
    assert hostile.json() == {"detail": "invalid Host authority"}
    assert wrong_port.status_code == 400


def test_session_token_and_api_routes_are_exactly_assembled() -> None:
    client, api = _client()

    session = client.get("/api/session")
    catalog = client.get("/api/scenarios")
    started = client.post(
        "/api/runs",
        headers=_state_headers(),
        json={"scenario_id": "brake_lead"},
    )
    status = client.get("/api/runs/run-safe-0001")
    trajectory = client.get(
        "/api/runs/run-safe-0001/artifacts/trajectory"
    )

    assert session.json() == {
        "schema_version": "scenarioforge.web-session/v1",
        "csrf_token": CSRF_TOKEN,
    }
    assert catalog.json()["scenarios"] == [{"scenario_id": "brake_lead"}]
    assert started.status_code == 201
    assert started.json()["run_id"] == "run-safe-0001"
    assert status.json()["state"] == "running"
    assert trajectory.json()["artifact_key"] == "trajectory"
    assert api.calls == [
        ("catalog",),
        ("start", "brake_lead", "request-safe-0001"),
        ("status", "run-safe-0001"),
        ("artifact", "run-safe-0001", "trajectory"),
    ]


def test_default_csrf_token_is_unguessable_and_unique_per_launch() -> None:
    first = create_app(api=FakeAPI(), coordinator=FakeCoordinator(), port=PORT)
    second = create_app(api=FakeAPI(), coordinator=FakeCoordinator(), port=PORT)

    assert len(first.csrf_token) >= 43
    assert len(second.csrf_token) >= 43
    assert first.csrf_token != second.csrf_token


@pytest.mark.parametrize(
    ("origin", "token"),
    [
        (None, CSRF_TOKEN),
        ("http://attacker.example", CSRF_TOKEN),
        (ORIGIN, None),
        (ORIGIN, "wrong-token"),
    ],
)
def test_state_changes_require_same_origin_and_launch_token(
    origin: str | None,
    token: str | None,
) -> None:
    client, api = _client()
    headers = {"Idempotency-Key": "request-safe-0001"}
    if origin is not None:
        headers["Origin"] = origin
    if token is not None:
        headers["X-CSRF-Token"] = token

    response = client.post(
        "/api/runs",
        headers=headers,
        json={"scenario_id": "brake_lead"},
    )

    assert response.status_code == 403
    assert api.calls == []


def test_cross_origin_requests_are_rejected_even_when_they_carry_credentials() -> None:
    client, api = _client()

    response = client.get(
        "/api/scenarios",
        headers={
            "Origin": "http://attacker.example",
            "Cookie": "session=ambient-credential",
            "Authorization": "Bearer ambient-credential",
        },
    )

    assert response.status_code == 403
    assert response.headers.get("access-control-allow-origin") is None
    assert response.headers.get("access-control-allow-credentials") is None
    assert api.calls == []


@pytest.mark.parametrize("operation", ("stop", "pause", "step", "reset", "cancel"))
def test_unsupported_live_run_control_routes_do_not_exist(operation: str) -> None:
    client, api = _client()

    response = client.post(
        f"/api/runs/run-safe-0001/{operation}",
        headers=_state_headers(),
        json={},
    )

    assert response.status_code == 404
    assert api.calls == []


@pytest.mark.parametrize(
    ("path", "content_type"),
    [
        ("/", "text/html"),
        ("/static/styles.css", "text/css"),
        ("/static/app.js", "text/javascript"),
        ("/api/session", "application/json"),
    ],
)
def test_every_response_has_restrictive_content_and_browser_security_headers(
    path: str,
    content_type: str,
) -> None:
    client, _ = _client()

    response = client.get(path)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(content_type)
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-security-policy"] == CONTENT_SECURITY_POLICY
    assert response.headers["cross-origin-resource-policy"] == "same-origin"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cache-control"] == "no-store"
    lowered_csp = CONTENT_SECURITY_POLICY.lower()
    assert "http:" not in lowered_csp
    assert "https:" not in lowered_csp
    assert "'unsafe-inline'" not in lowered_csp
    assert "'unsafe-eval'" not in lowered_csp


def test_signal_handler_requests_one_interruption_and_uvicorn_shutdown() -> None:
    coordinator = FakeCoordinator(active=True)
    app = create_app(
        api=FakeAPI(),
        coordinator=coordinator,
        port=PORT,
        csrf_token=CSRF_TOKEN,
    )
    server = LoopbackServer(
        Config(app, host=LOOPBACK_HOST, port=PORT, log_config=None),
        shutdown=app.shutdown,
    )

    server.handle_exit(signal.SIGTERM, None)
    server.handle_exit(signal.SIGTERM, None)

    assert coordinator.interrupt_calls == 1
    assert server.should_exit is True
    assert server._captured_signals == [signal.SIGTERM, signal.SIGTERM]


def test_lifespan_waits_for_the_tracked_run_after_shutdown_request() -> None:
    coordinator = FakeCoordinator(active=True)
    app = create_app(
        api=FakeAPI(),
        coordinator=coordinator,
        port=PORT,
        csrf_token=CSRF_TOKEN,
    )

    with TestClient(app, base_url=ORIGIN) as client:
        response = client.post(
            "/api/runs",
            headers=_state_headers(),
            json={"scenario_id": "brake_lead"},
        )
        assert response.status_code == 201

    assert coordinator.interrupt_calls == 1
    assert coordinator.waited_for == [("run-safe-0001", 10.0)]


@pytest.mark.parametrize("shutdown_signal", (signal.SIGINT, signal.SIGTERM))
def test_signal_closes_real_worker_tree_and_publishes_operator_interruption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    shutdown_signal: signal.Signals,
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
        lambda name: {"jsonschema": "4.25.1", "metadrive-simulator": "0.4.3"}[
            name
        ],
    )
    script = (
        "import subprocess,sys,time;"
        "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],"
        "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);"
        "print(child.pid,flush=True);"
        "time.sleep(60)"
    )
    real_popen = subprocess.Popen
    worker_started = threading.Event()

    def controlled_popen(_command: object, **kwargs: object) -> subprocess.Popen[str]:
        process = real_popen([sys.executable, "-c", script], **kwargs)
        worker_started.set()
        return process

    monkeypatch.setattr(
        "scenarioforge.runtime.supervisor.subprocess.Popen", controlled_popen
    )
    coordinator = RunCoordinator(workspace=tmp_path, project_root=ROOT)
    evidence = PublishedEvidenceReader(publish_root=tmp_path / "published")
    app = create_app(
        api=ScenarioForgeAPI(coordinator=coordinator, evidence=evidence),
        coordinator=coordinator,
        port=PORT,
        csrf_token=CSRF_TOKEN,
    )
    server = LoopbackServer(
        Config(app, host=LOOPBACK_HOST, port=PORT, log_config=None),
        shutdown=app.shutdown,
    )

    with TestClient(app, base_url=ORIGIN) as client:
        response = client.post(
            "/api/runs",
            headers=_state_headers(),
            json={"scenario_id": "brake_lead"},
        )
        reference = response.json()
        assert response.status_code == 201
        assert worker_started.wait(timeout=3)
        server.handle_exit(shutdown_signal, None)

    terminal = evidence.terminal(reference["run_id"], reference["attempt_id"])
    published = (
        tmp_path / "published" / reference["run_id"] / reference["attempt_id"]
    )
    failure = json.loads(
        (published / "failure_evidence.json").read_text(encoding="utf-8")
    )

    assert terminal["status"] == "failed"
    assert terminal["reason"] == "operator_interrupted"
    assert terminal["failure_stage"] == "operator_interruption"
    assert failure["failure_kind"] == "operator_interrupted"
    assert failure["termination"]["complete"] is True
    assert failure["termination"]["remaining_pids"] == []
    assert "SIGTERM" in failure["termination"]["signals_sent"]
    assert live_process_group_members(
        failure["termination"]["process_group_id"]
    ) == ()
    assert (published / "FAILED").is_file()
    assert not (published / "SUCCESS").exists()


def test_cli_web_command_has_no_public_bind_option(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(cli, "serve_web", lambda **kwargs: calls.append(kwargs))

    result = cli.main(
        [
            "--project-root",
            str(ROOT),
            "--workspace",
            str(tmp_path),
            "web",
            "--port",
            str(PORT),
            "--timeout-seconds",
            "23",
        ]
    )

    assert result == 0
    assert calls == [
        {
            "workspace": tmp_path,
            "project_root": ROOT,
            "port": PORT,
            "timeout_seconds": 23,
        }
    ]
    with pytest.raises(SystemExit):
        cli._parser().parse_args(["web", "--host", "0.0.0.0"])


def test_service_runner_pins_uvicorn_to_loopback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}
    coordinator = FakeCoordinator()
    shutdown = object()
    app = type("App", (), {"shutdown": shutdown})()

    monkeypatch.setattr(
        server_module,
        "RunCoordinator",
        lambda **_kwargs: coordinator,
    )
    monkeypatch.setattr(
        server_module,
        "PublishedEvidenceReader",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(
        server_module,
        "ScenarioForgeAPI",
        lambda **_kwargs: FakeAPI(),
    )
    monkeypatch.setattr(server_module, "create_app", lambda **_kwargs: app)

    def fake_config(selected_app: object, **kwargs: object) -> object:
        captured["app"] = selected_app
        captured["config"] = kwargs
        return object()

    class FakeServer:
        def __init__(self, config: object, *, shutdown: object) -> None:
            captured["server"] = (config, shutdown)

        def run(self) -> None:
            captured["ran"] = True

    monkeypatch.setattr(server_module.uvicorn, "Config", fake_config)
    monkeypatch.setattr(server_module, "LoopbackServer", FakeServer)

    server_module.serve(
        workspace=tmp_path,
        project_root=ROOT,
        port=PORT,
        timeout_seconds=23,
    )

    assert captured["app"] is app
    assert captured["config"] == {
        "host": "127.0.0.1",
        "port": PORT,
        "proxy_headers": False,
        "server_header": False,
        "timeout_graceful_shutdown": 15,
    }
    assert captured["server"][1] is shutdown
    assert captured["ran"] is True
