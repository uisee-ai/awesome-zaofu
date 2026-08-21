from __future__ import annotations

import json
from pathlib import Path

from starlette.testclient import TestClient

from scenarioforge.authoring.library import LocalScenarioLibrary
from scenarioforge.web.api import ScenarioForgeAPI
from scenarioforge.web.server import create_app


ROOT = Path(__file__).resolve().parents[3]
PORT = 8871
ORIGIN = f"http://127.0.0.1:{PORT}"
CSRF = "p1-authoring-csrf-token-that-is-long-enough"


class Coordinator:
    def interrupt_active_for_shutdown(self) -> bool:
        return False

    def wait_for_terminal(self, run_id: str, *, timeout: float | None = None):
        return None


def _headers() -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Origin": ORIGIN,
        "X-CSRF-Token": CSRF,
    }


def _value() -> dict[str, object]:
    value = json.loads(
        (ROOT / "tests/fixtures/authoring/valid_scenario.json").read_text(
            encoding="utf-8"
        )
    )
    value["road"]["topology_kind"] = "corridor"
    value["road"]["conflict_zones"] = []
    value["routes"] = value["routes"][:2]
    value["actors"] = value["actors"][:2]
    value["static_obstacles"] = []
    value["required_capabilities"] = ["actor.vehicle", "route.stable-id"]
    return value


def test_p1_http_actions_keep_provider_and_run_authority_on_server(tmp_path: Path) -> None:
    coordinator = Coordinator()
    library = LocalScenarioLibrary(tmp_path / "library")
    api = ScenarioForgeAPI(
        coordinator=coordinator,
        evidence=object(),
        library=library,
    )
    app = create_app(
        api=api,
        coordinator=coordinator,
        port=PORT,
        csrf_token=CSRF,
    )
    with TestClient(app, base_url=ORIGIN) as client:
        provider = client.post(
            "/api/authoring/provider-drafts",
            headers=_headers(),
            json={
                "provider_id": "scenarioforge.offline-reference",
                "prompt": "Create a highway merge with social vehicles",
            },
        )
        assert provider.status_code == 201
        assert provider.json()["status"] == "needs_correction"
        assert client.post(
            "/api/authoring/provider-drafts",
            headers=_headers(),
            json={"provider_id": "cloud-unregistered", "prompt": "merge"},
        ).status_code == 400

        draft = client.post(
            "/api/authoring/drafts",
            headers=_headers(),
            json={"content": _value()},
        ).json()
        revision = client.post(
            f"/api/authoring/drafts/{draft['scenario_id']}/revisions",
            headers=_headers(),
            json={"expected_generation": draft["generation"]},
        ).json()
        preflight = client.post(
            f"/api/authoring/revisions/{revision['revision_id']}/p1-preflight",
            headers=_headers(),
            json={"backend_id": "scenarioforge.metadrive"},
        ).json()
        authorization = client.post(
            f"/api/authoring/p1-preflights/{preflight['preflight_id']}/confirm",
            headers=_headers(),
            json={},
        ).json()
        receipt = client.post(
            f"/api/authoring/p1-preflights/{preflight['preflight_id']}/authorize-run",
            headers=_headers(),
            json={"authorization": authorization},
        )

        assert receipt.status_code == 201
        assert receipt.json()["authorized"] is True
        replay = client.post(
            f"/api/authoring/p1-preflights/{preflight['preflight_id']}/authorize-run",
            headers=_headers(),
            json={"authorization": authorization},
        )
        assert replay.status_code in {400, 409}
