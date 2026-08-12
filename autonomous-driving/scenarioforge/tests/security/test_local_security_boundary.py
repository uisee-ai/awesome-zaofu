from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from scenarioforge.api import ApiConfig, create_app


ORIGIN = "http://127.0.0.1:4173"
TOKEN = "capability-SECRET_CANARY-never-leak"
CSRF = "csrf-SECRET_CANARY-never-leak"


def _client(bundle_root: Path) -> TestClient:
    app = create_app(
        ApiConfig(
            bundle_root=bundle_root,
            run_output_root=bundle_root,
            allowed_origin=ORIGIN,
            capability_token=TOKEN,
            csrf_token=CSRF,
        )
    )
    return TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000))


def _headers(**updates: str) -> dict[str, str]:
    result = {
        "Origin": ORIGIN,
        "X-ScenarioForge-Capability": TOKEN,
        "X-ScenarioForge-CSRF": CSRF,
    }
    result.update(updates)
    return result


@pytest.mark.parametrize(
    ("headers", "code"),
    [
        (_headers(Origin="https://attacker.invalid"), "origin_denied"),
        (_headers(**{"X-ScenarioForge-Capability": "wrong"}), "capability_denied"),
        (_headers(**{"X-ScenarioForge-CSRF": "wrong"}), "csrf_denied"),
    ],
)
def test_rejects_origin_capability_and_csrf_without_disclosure(
    tmp_path: Path, headers: dict[str, str], code: str
) -> None:
    response = _client(tmp_path).post(
        "/api/replays/load", headers=headers, json={"bundle_id": "bundle"}
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == code
    leaked = "\n".join(
        [response.text, *[f"{key}:{value}" for key, value in response.headers.items()]]
    )
    assert TOKEN not in leaked
    assert CSRF not in leaked
    assert str(tmp_path) not in leaked
    assert "set-cookie" not in response.headers


@pytest.mark.parametrize("bundle_id", ["../bundle", "/tmp/bundle", "bundle/../../etc"])
def test_rejects_path_traversal_without_echo(tmp_path: Path, bundle_id: str) -> None:
    response = _client(tmp_path).post(
        "/api/replays/load", headers=_headers(), json={"bundle_id": bundle_id}
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_bundle_id"
    assert bundle_id not in response.text
    assert str(tmp_path) not in response.text


def test_rejects_symlink_and_hardlink_bundle_entries(tmp_path: Path) -> None:
    source = Path("evidence/runtime/metadrive-smoke/bundle")
    symlink_bundle = tmp_path / "symlink-bundle"
    shutil.copytree(source, symlink_bundle)
    trace = symlink_bundle / "traces" / "case-000.json"
    trace.unlink()
    trace.symlink_to(source.resolve() / "traces" / "case-000.json")

    hardlink_bundle = tmp_path / "hardlink-bundle"
    shutil.copytree(source, hardlink_bundle)
    trace = hardlink_bundle / "traces" / "case-000.json"
    outside = tmp_path / "outside.json"
    outside.write_bytes(trace.read_bytes())
    trace.unlink()
    os.link(outside, trace)

    for bundle_id in ("symlink-bundle", "hardlink-bundle"):
        response = _client(tmp_path).post(
            "/api/replays/load", headers=_headers(), json={"bundle_id": bundle_id}
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "unsafe_filesystem_entry"
        assert str(tmp_path) not in response.text


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ({"archive": "UEsDBAoAAAAA" * 1000}, "archive_import_disabled"),
        ({"archive": "\u0080\u0004pickle"}, "archive_import_disabled"),
    ],
)
def test_rejects_archive_bomb_and_pickle_inputs(
    tmp_path: Path, payload: dict[str, str], code: str
) -> None:
    response = _client(tmp_path).post(
        "/api/bundles/import", headers=_headers(), json=payload
    )
    assert response.status_code == 415
    assert response.json()["error"]["code"] == code


@pytest.mark.parametrize("value", ["<script>alert(1)</script>", "SECRET_CANARY_value"])
def test_rejects_xss_and_secret_canary_without_reflection(tmp_path: Path, value: str) -> None:
    scenario = {
        "schema_version": "scenarioforge.scenario-spec.v1",
        "name": value,
        "map": {"block_sequence": "S", "lane_count": 2, "lane_width": 3.5},
        "actors": [{"id": "ego", "role": "ego"}],
        "environment": {"traffic_density": 0.1},
    }
    response = _client(tmp_path).post(
        "/api/scenarios/validate",
        headers=_headers(),
        json={"source": json.dumps(scenario), "media_type": "application/json"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unsafe_input"
    assert value not in response.text
    assert str(tmp_path) not in response.text
