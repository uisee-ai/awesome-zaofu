from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from highwaypilot_lab.api import RuntimeService, create_app
from highwaypilot_lab.security import LoopbackBoundaryError, validate_bind_address


PROJECT_ROOT = Path(__file__).parents[2]
BASE_URL = "http://127.0.0.1:4317"
ORIGIN = BASE_URL


@pytest.fixture
def runtime() -> RuntimeService:
    return RuntimeService(project_root=PROJECT_ROOT)


@pytest.fixture
def client(runtime: RuntimeService) -> TestClient:
    return TestClient(create_app(runtime=runtime), base_url=BASE_URL)


def test_mutation_requires_exact_same_port_origin_before_state_changes(
    client: TestClient,
    runtime: RuntimeService,
) -> None:
    config = json.loads((PROJECT_ROOT / "configs/presets/normal-v1.json").read_text())
    payload = {"config": config}

    for headers in (
        {},
        {"origin": "null"},
        {"origin": "http://localhost:4317"},
        {"origin": "http://127.0.0.1:4318"},
        {"origin": "https://127.0.0.1:4317"},
    ):
        response = client.post("/api/sessions", json=payload, headers=headers)
        assert response.status_code == 403
        assert response.json() == {
            "error": {
                "code": "ORIGIN_REJECTED",
                "message": "request origin is not the exact loopback service origin",
            }
        }
        assert runtime.session_count == 0

    response = client.post(
        "/api/sessions",
        json=payload,
        headers={"origin": ORIGIN},
    )

    assert response.status_code == 201
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["connection_status"] == "connected"
    assert body["session_status"] == "active"
    assert body["simulation_status"] == "paused"
    assert body["snapshot"]["authority"] == "python"
    assert len(body["resume_token"]) == 43
    assert runtime.session_count == 1


@pytest.mark.parametrize(
    "headers",
    [
        {"host": "localhost:4317"},
        {"host": "127.0.0.2:4317"},
        {"host": "127.0.0.1:4318"},
        {"host": "127.0.0.1"},
        {"host": "evil.example:4317"},
        {"host": "127.0.0.1:4317", "x-forwarded-host": "evil.example"},
        {"host": "127.0.0.1:4317", "forwarded": "host=evil.example"},
    ],
)
def test_host_dns_rebinding_and_proxy_matrix_fails_closed(
    client: TestClient,
    headers: dict[str, str],
) -> None:
    response = client.get("/api/health", headers=headers)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "HOST_REJECTED"


def test_read_only_get_may_omit_origin_but_rejects_bad_origin(client: TestClient) -> None:
    accepted = client.get("/api/health")
    rejected = client.get("/api/health", headers={"origin": "http://localhost:4317"})

    assert accepted.status_code == 200
    assert accepted.json() == {"status": "ok", "bind_host": "127.0.0.1"}
    assert rejected.status_code == 403
    assert rejected.json()["error"]["code"] == "ORIGIN_REJECTED"


def test_service_bind_address_is_fixed_to_ipv4_loopback() -> None:
    assert validate_bind_address("127.0.0.1", 4317) == ("127.0.0.1", 4317)
    for host in ("localhost", "::1", "0.0.0.0", "127.0.0.2"):
        with pytest.raises(LoopbackBoundaryError, match="127.0.0.1"):
            validate_bind_address(host, 4317)


def test_websocket_requires_same_origin_and_streams_authoritative_session_state(
    client: TestClient,
    runtime: RuntimeService,
) -> None:
    config = json.loads((PROJECT_ROOT / "configs/presets/normal-v1.json").read_text())
    created = client.post(
        "/api/sessions",
        json={"config": config},
        headers={"origin": ORIGIN},
    ).json()
    path = f"/ws/sessions/{created['session_id']}"
    websocket_url = f"ws://127.0.0.1:4317{path}"

    with pytest.raises(WebSocketDisconnect) as rejected:
        with client.websocket_connect(websocket_url):
            pass
    assert rejected.value.code == 4403

    with client.websocket_connect(websocket_url, headers={"origin": ORIGIN}) as websocket:
        initial = websocket.receive_json()
        assert initial["type"] == "simulation.snapshot"
        assert initial["snapshot"]["authority"] == "python"
        websocket.send_json(
            {
                "protocol_version": "highwaypilot-ws/v1",
                "type": "command",
                "session_id": created["session_id"],
                "command_id": "hmi-step-1",
                "attachment_epoch": created["attachment_epoch"],
                "simulation_generation": created["simulation_generation"],
                "expected_state_seq": created["state_seq"],
                "name": "simulation.play",
                "payload": {},
            }
        )
        result = websocket.receive_json()
        assert result["type"] == "command.result"
        assert result["result"]["simulation_status"] == "playing"
        dynamic = websocket.receive_json()
        assert dynamic["type"] == "simulation.snapshot"
        assert dynamic["snapshot"]["authority"] == "python"
        assert dynamic["snapshot"]["step"] > created["snapshot"]["step"]

    session = runtime.session(created["session_id"])
    assert session is not None
    assert session.socket_status == "detached"
    assert session.simulation_status == "paused"
