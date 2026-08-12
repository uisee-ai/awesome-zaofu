from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from scenarioforge.api import ApiConfig, create_app


SCENARIO = {
    "schema_version": "scenarioforge.scenario-spec.v1",
    "name": "golden-path",
    "map": {"block_sequence": "S", "lane_count": 2, "lane_width": 3.5},
    "actors": [{"id": "ego", "role": "ego"}],
    "environment": {"traffic_density": 0.1},
    "tags": ["offline"],
}
HEADERS = {
    "Origin": "http://127.0.0.1:4173",
    "X-ScenarioForge-Capability": "test-capability",
    "X-ScenarioForge-CSRF": "test-csrf",
}


def _client(bundle_root: Path, **overrides: object) -> TestClient:
    values: dict[str, object] = {
        "bundle_root": bundle_root,
        "run_output_root": bundle_root,
        "allowed_origin": "http://127.0.0.1:4173",
        "capability_token": "test-capability",
        "csrf_token": "test-csrf",
    }
    values.update(overrides)
    app = create_app(ApiConfig(**values))
    return TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000))


def test_validate_returns_field_diagnostics_and_canonical_preview(tmp_path: Path) -> None:
    client = _client(tmp_path)

    valid = client.post(
        "/api/scenarios/validate",
        headers=HEADERS,
        json={"source": json.dumps(SCENARIO), "media_type": "application/json"},
    )
    invalid_payload = {**SCENARIO, "map": {**SCENARIO["map"], "lane_count": 99}}
    invalid = client.post(
        "/api/scenarios/validate",
        headers=HEADERS,
        json={"source": json.dumps(invalid_payload), "media_type": "application/json"},
    )

    assert valid.status_code == 200
    assert valid.json()["valid"] is True
    assert valid.json()["canonical"]["scenario"]["name"] == "golden-path"
    assert len(valid.json()["canonical"]["digest"]) == 64
    assert invalid.status_code == 422
    assert invalid.json()["valid"] is False
    assert invalid.json()["diagnostics"][0]["location"] == "map.lane_count"


def test_exports_canonical_json_and_yaml(tmp_path: Path) -> None:
    client = _client(tmp_path)

    responses = [
        client.post(
            "/api/scenarios/export",
            headers=HEADERS,
            json={
                "source": json.dumps(SCENARIO),
                "media_type": "application/json",
                "format": format_name,
            },
        )
        for format_name in ("json", "yaml")
    ]

    assert [response.status_code for response in responses] == [200, 200]
    assert responses[0].json()["document"].endswith("\n")
    assert "schema_version: scenarioforge.scenario-spec.v1" in responses[1].json()["document"]


def test_loads_replay_by_opaque_bundle_id(tmp_path: Path) -> None:
    bundle_root = Path("evidence/runtime/metadrive-smoke")
    client = _client(bundle_root)

    response = client.post(
        "/api/replays/load", headers=HEADERS, json={"bundle_id": "bundle"}
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["cases"][0]["frames"][20]["position"] == [7.8343329429626465, 3.5]
    assert payload["execution"]["runner_state"] == "stopped"
    serialized = response.text
    assert "worker_pid" not in serialized
    assert "platform" not in serialized


def test_run_control_is_async_and_supports_status_and_cancel(tmp_path: Path) -> None:
    calls: list[object] = []

    class FakeJobs:
        def submit(self, compiled: object, output_root: Path, *, job_id: str) -> dict[str, object]:
            calls.append((compiled, output_root, job_id))
            return {"job_id": job_id, "status": "queued", "retry_count": 0}

        def get(self, job_id: str) -> dict[str, object]:
            return {"job_id": job_id, "status": "running", "retry_count": 0}

        def cancel(self, job_id: str) -> dict[str, object]:
            return {"job_id": job_id, "status": "running", "cancel_requested": True, "retry_count": 0}

    client = _client(tmp_path, job_manager=FakeJobs())
    validate = client.post(
        "/api/scenarios/validate",
        headers=HEADERS,
        json={"source": json.dumps(SCENARIO), "media_type": "application/json"},
    ).json()
    request = {
        "schema_version": "scenarioforge.run-request.v1",
        "scenario_digest": validate["canonical"]["digest"],
        "seeds": [17],
        "profile": "default",
        "limits": {
            "workers": 1,
            "aggregate_cpu_threads": 2,
            "max_steps": 20,
            "max_simulated_seconds": 30.0,
            "case_wall_seconds": 60.0,
            "bundle_wall_seconds": 600.0,
            "bundle_disk_bytes": 1073741824,
        },
    }

    response = client.post(
        "/api/runs",
        headers=HEADERS,
        json={"source": json.dumps(SCENARIO), "media_type": "application/json", "request": request},
    )

    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    assert len(calls) == 1
    compiled, output_root, run_id = calls[0]
    assert compiled.backend.version == "0.4.3"
    assert output_root == tmp_path
    assert run_id.startswith("run-")
    assert client.get(f"/api/runs/{run_id}", headers=HEADERS).json()["status"] == "running"
    assert client.post(f"/api/runs/{run_id}/cancel", headers=HEADERS).json()["cancel_requested"] is True


def test_exposes_sample_catalog_and_exact_replay_verification(tmp_path: Path) -> None:
    client = _client(Path("evidence/runtime/metadrive-smoke"), sample_root=Path("samples"))

    catalog = client.get("/api/samples", headers=HEADERS)
    verification = client.post(
        "/api/replays/verify", headers=HEADERS, json={"bundle_id": "bundle"}
    )

    assert catalog.status_code == 200
    assert [item["id"] for item in catalog.json()["samples"]] == [
        "following",
        "following-emergency-brake",
        "merge",
        "lane-conflict",
        "intersection",
        "static-obstacle-avoidance",
    ]
    assert verification.status_code == 200
    assert verification.json()["status"] == "pass"


def test_exposes_only_catalog_declared_authoritative_sample_documents(tmp_path: Path) -> None:
    client = _client(tmp_path, sample_root=Path("samples"))

    document = client.get("/api/samples/following", headers=HEADERS)
    unknown = client.get("/api/samples/unknown-sample", headers=HEADERS)
    traversal = client.get("/api/samples/%2E%2E%2Fcatalog.json", headers=HEADERS)
    missing_capability = client.get(
        "/api/samples/following",
        headers={"Origin": "http://127.0.0.1:4173"},
    )

    assert document.status_code == 200
    assert document.json() == {
        "id": "following",
        "media_type": "application/json",
        "source": (Path("samples") / "following.json").read_text(encoding="utf-8"),
    }
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "sample_not_found"
    assert traversal.status_code == 404
    assert traversal.json()["error"]["code"] == "sample_not_found"
    assert missing_capability.status_code == 403
    assert missing_capability.json()["error"]["code"] == "capability_denied"
