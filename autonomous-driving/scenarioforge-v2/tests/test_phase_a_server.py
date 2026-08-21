from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from starlette.testclient import TestClient

from scenarioforge.authoring.library import LocalScenarioLibrary
from scenarioforge.authoring.presets import BUILTIN_PRESET_IDS, PresetCatalog
from scenarioforge.web.api import ScenarioForgeAPI
from scenarioforge.web.coordinator import ExecutionState, RunReference, UnknownRunError
from scenarioforge.web.server import CONTENT_SECURITY_POLICY, create_app


ROOT = Path(__file__).resolve().parents[1]
PORT = 8765
ORIGIN = f"http://127.0.0.1:{PORT}"
CSRF = "phase-a-test-csrf-token-that-is-long-enough"


class Coordinator:
    def start(self, scenario_id: str, *, idempotency_key: str) -> RunReference:
        raise AssertionError("authoring HTTP must not run a mutable catalog alias")

    def active_state(self, run_id: str) -> ExecutionState | None:
        raise UnknownRunError("unknown run_id")

    def reference(self, run_id: str) -> RunReference:
        raise UnknownRunError("unknown run_id")

    def interrupt_active_for_shutdown(self) -> bool:
        return False

    def wait_for_terminal(self, run_id: str, *, timeout: float | None = None) -> object:
        return object()


class Evidence:
    def terminal(self, run_id: str, attempt_id: str) -> dict[str, object]:
        return {"run_id": run_id, "attempt_id": attempt_id, "terminal": True}

    def playback(self, run_id: str, attempt_id: str) -> dict[str, object]:
        return {"run_id": run_id, "attempt_id": attempt_id, "trajectory": []}


class Runner:
    def run(
        self,
        bundle: Any,
        *,
        run_id: str,
        attempt_id: str,
        timeout_seconds: float,
    ) -> dict[str, object]:
        return {"run_id": run_id, "attempt_id": attempt_id}


def _client(tmp_path: Path) -> TestClient:
    coordinator = Coordinator()
    api = ScenarioForgeAPI(
        coordinator=coordinator,
        evidence=Evidence(),
        catalog_profile="p0c",
        library=LocalScenarioLibrary(
            tmp_path / "library",
            preset_catalog=PresetCatalog(ROOT / "examples/p0c"),
        ),
        authoring_runner=Runner(),
    )
    return TestClient(
        create_app(api=api, coordinator=coordinator, port=PORT, csrf_token=CSRF),
        base_url=ORIGIN,
    )


def _headers(*, idempotency_key: str | None = None) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "Origin": ORIGIN,
        "X-CSRF-Token": CSRF,
    }
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    return headers


def test_http_authoring_flow_reaches_an_immutable_revision_run(tmp_path: Path) -> None:
    value = json.loads(
        (ROOT / "tests/fixtures/authoring/valid_scenario.json").read_text(
            encoding="utf-8"
        )
    )
    with _client(tmp_path) as client:
        created_response = client.post(
            "/api/authoring/drafts", headers=_headers(), json={"content": value}
        )
        assert created_response.status_code == 201
        assert created_response.headers["content-security-policy"] == CONTENT_SECURITY_POLICY
        draft = created_response.json()
        scenario_id = draft["scenario_id"]

        invalid = copy.deepcopy(value)
        invalid["actors"][0]["spawn"]["lane_id"] = "missing-lane"
        edited = client.put(
            f"/api/authoring/drafts/{scenario_id}",
            headers=_headers(),
            json={"expected_generation": 0, "content": invalid},
        ).json()
        validation = client.get(
            f"/api/authoring/drafts/{scenario_id}/validation"
        ).json()
        assert validation["valid"] is False
        assert any(item["path"].endswith("spawn.lane_id") for item in validation["diagnostics"])

        restored = client.put(
            f"/api/authoring/drafts/{scenario_id}",
            headers=_headers(),
            json={"expected_generation": edited["generation"], "content": value},
        ).json()
        saved = client.post(
            f"/api/authoring/drafts/{scenario_id}/revisions",
            headers=_headers(),
            json={"expected_generation": restored["generation"]},
        )
        assert saved.status_code == 201
        revision = saved.json()
        history = client.get(
            f"/api/authoring/scenarios/{scenario_id}/history"
        ).json()
        assert history["revisions"] == [revision]

        preflight = client.post(
            f"/api/authoring/revisions/{revision['revision_id']}/preflight",
            headers=_headers(),
            json={},
        )
        assert preflight.status_code == 200
        assert preflight.json()["revision_id"] == revision["revision_id"]
        assert preflight.json()["status"] == "unsupported"
        blocked = client.post(
            f"/api/authoring/revisions/{revision['revision_id']}/runs",
            headers=_headers(idempotency_key="phase-a-http-blocked-0001"),
            json={},
        )
        assert blocked.status_code == 409

        exact_value = json.loads(
            (ROOT / "examples/p0a/brake_lead.json").read_text(encoding="utf-8")
        )
        exact_draft = client.post(
            "/api/authoring/drafts",
            headers=_headers(),
            json={"content": exact_value},
        ).json()
        exact_revision = client.post(
            f"/api/authoring/drafts/{exact_draft['scenario_id']}/revisions",
            headers=_headers(),
            json={"expected_generation": exact_draft["generation"]},
        ).json()
        exact_preflight = client.post(
            f"/api/authoring/revisions/{exact_revision['revision_id']}/preflight",
            headers=_headers(),
            json={},
        )
        assert exact_preflight.json()["status"] == "exact"

        run = client.post(
            f"/api/authoring/revisions/{exact_revision['revision_id']}/runs",
            headers=_headers(idempotency_key="phase-a-http-run-0001"),
            json={},
        )
        assert run.status_code == 201
        reference = run.json()
        assert reference["revision_id"] == exact_revision["revision_id"]
        assert client.get(f"/api/runs/{reference['run_id']}").json()["terminal"] is True


def test_http_clone_archive_presets_and_inline_round_trip(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        presets = client.get("/api/authoring/presets").json()
        assert tuple(item["template_id"] for item in presets["templates"]) == BUILTIN_PRESET_IDS
        source = presets["templates"][0]["content"]
        forked = client.post(
            "/api/authoring/presets/brake_lead/fork",
            headers=_headers(),
            json={"content": source},
        ).json()
        cloned = client.post(
            f"/api/authoring/scenarios/{forked['scenario_id']}/clone",
            headers=_headers(),
            json={},
        ).json()
        archived = client.post(
            f"/api/authoring/scenarios/{cloned['scenario_id']}/archive",
            headers=_headers(),
            json={},
        ).json()
        assert archived["scenario_id"] == cloned["scenario_id"]

        value = json.loads(
            (ROOT / "tests/fixtures/authoring/valid_scenario.json").read_text(
                encoding="utf-8"
            )
        )
        imported = client.post(
            "/api/authoring/import",
            headers=_headers(),
            json={"format": "json", "content": json.dumps(value)},
        )
        assert imported.status_code == 201
        imported_id = imported.json()["draft"]["scenario_id"]
        exported = client.get(
            f"/api/authoring/drafts/{imported_id}/export?format=yaml"
        ).json()
        assert exported["format"] == "yaml"
        assert "schema_version:" in exported["content"]


def test_authoring_writes_reuse_security_boundary_and_sanitize_failures(
    tmp_path: Path,
) -> None:
    with _client(tmp_path) as client:
        assert client.post("/api/authoring/drafts", json={"content": {}}).status_code == 403
        assert client.post(
            "/api/authoring/drafts",
            headers={**_headers(), "X-CSRF-Token": "wrong"},
            json={"content": {}},
        ).status_code == 403

        secret = "PWNED-/tmp/phase-a-secret"
        invalid = client.post(
            "/api/authoring/import",
            headers=_headers(),
            json={
                "format": "yaml",
                "content": f"!!python/object/apply:os.system ['{secret}']",
            },
        )
        assert invalid.status_code == 422
        assert secret not in invalid.text
        assert "/tmp/phase-a-secret" not in invalid.text

        oversized = client.post(
            "/api/authoring/import",
            headers=_headers(),
            content=json.dumps({"format": "json", "content": "x" * 70_000}),
        )
        assert oversized.status_code == 400
        assert "x" * 100 not in oversized.text
