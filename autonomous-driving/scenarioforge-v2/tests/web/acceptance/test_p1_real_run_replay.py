from __future__ import annotations

import hashlib
import json
import time
from typing import Any
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from playwright.sync_api import Browser, expect

from scenarioforge.core import canonical_bytes, strict_loads

P1_SCENARIOS = (
    "highway_merge",
    "competitive_lane_change",
    "cross_traffic_red_light_violation",
    "unprotected_left_turn",
    "pedestrian_red_light_crossing",
)
P1_ROLES = {"ego", "controlled", "social_vehicle", "pedestrian"}
DIRECT_OPENER = build_opener(ProxyHandler({}))


def _json_request(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    body: dict[str, object] | None = None,
    csrf_token: str | None = None,
    idempotency_key: str | None = None,
) -> tuple[int, dict[str, Any]]:
    headers = {"Accept": "application/json"}
    payload = None
    if body is not None:
        payload = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
        headers["Origin"] = base_url
    if csrf_token is not None:
        headers["X-CSRF-Token"] = csrf_token
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    request = Request(
        f"{base_url}{path}",
        data=payload,
        headers=headers,
        method=method,
    )
    try:
        with DIRECT_OPENER.open(request, timeout=180) as response:
            return response.status, json.loads(response.read())
    except HTTPError as error:
        return error.code, json.loads(error.read())


def _wait_for_terminal(base_url: str, run_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        status, payload = _json_request(base_url, f"/api/p1/runs/{run_id}")
        assert status == 200, payload
        if payload.get("terminal") is True:
            return payload
        assert payload["state"] in {"starting", "running"}
        time.sleep(0.05)
    raise AssertionError(f"P1 run did not publish terminal evidence: {run_id}")


def test_five_canonical_p1_scenarios_cross_real_web_smarts_and_publish_replay(
    service_factory,
) -> None:
    service = service_factory(timeout_seconds=120)
    session_status, session = _json_request(service.base_url, "/api/session")
    assert session_status == 200
    token = session["csrf_token"]

    catalog_status, catalog = _json_request(service.base_url, "/api/p1/scenarios")
    assert catalog_status == 200
    assert catalog == {
        "schema_version": "scenarioforge.p1-scenario-catalog/v1",
        "default_scenario_id": "highway_merge",
        "scenarios": catalog["scenarios"],
    }
    assert tuple(item["scenario_id"] for item in catalog["scenarios"]) == P1_SCENARIOS
    assert all(
        item["backend"]
        == {
            "id": "scenarioforge.smarts",
            "version": "2.0.1",
            "status": "exact",
        }
        for item in catalog["scenarios"]
    )

    page = DIRECT_OPENER.open(f"{service.base_url}/", timeout=10).read().decode()
    assert 'id="studio-template-select"' in page
    assert 'id="studio-run"' in page

    for scenario_id in P1_SCENARIOS:
        start_status, reference = _json_request(
            service.base_url,
            "/api/p1/runs",
            method="POST",
            body={"scenario_id": scenario_id},
            csrf_token=token,
            idempotency_key=f"acceptance-{scenario_id}",
        )
        assert start_status == 201, reference
        assert reference["scenario_id"] == scenario_id
        assert reference["backend"] == {
            "id": "scenarioforge.smarts",
            "version": "2.0.1",
        }

        terminal = _wait_for_terminal(service.base_url, reference["run_id"])
        assert terminal["schema_version"] == "scenarioforge.p1-terminal-evidence/v1"
        assert terminal["scenario_id"] == scenario_id
        assert terminal["attempt_id"] == reference["attempt_id"]
        assert terminal["immutable"] is True
        assert terminal["execution_status"] == "completed"
        assert terminal["backend"] == {
            "id": "scenarioforge.smarts",
            "version": "2.0.1",
            "engine_class": "SMARTS",
        }
        assert terminal["metrics"]["completed_steps"] >= 1
        assert terminal["metrics"]["completion_time_s"] >= 10.0
        assert len(terminal["digests"]["evidence"]) == 64

        evidence_path = (
            service.workspace / reference["published_ref"] / "smarts_evidence.json"
        )
        evidence_payload = evidence_path.read_bytes()
        assert (
            hashlib.sha256(evidence_payload).hexdigest()
            == terminal["digests"]["evidence"]
        )
        assert canonical_bytes(strict_loads(evidence_payload)) == evidence_payload

        playback_status, playback = _json_request(
            service.base_url,
            f"/api/p1/runs/{reference['run_id']}/artifacts/trajectory",
        )
        assert playback_status == 200, playback
        assert playback["schema_version"] == "scenarioforge.p1-playback/v1"
        assert playback["scenario_id"] == scenario_id
        assert playback["trajectory_digest"] == terminal["digests"]["trajectory"]
        assert playback["coordinate_system"] == ("right-handed-map-x-east-y-north-z-up")
        assert playback["traffic_rule"] == "right-hand-traffic"
        assert playback["camera"] == {
            "default_mode": "ego-follow",
            "available_modes": ["ego-follow", "overview", "fixed", "free"],
            "target_participant_id": "ego",
            "pose_source": "recorded-trajectory",
        }
        assert playback["road"]["geometry"]["source"] == (
            "scenarioforge.smarts/2.0.1:road-map"
        )
        assert playback["road"]["geometry"]["lanes"]
        participant_ids = {item["id"] for item in playback["participants"]}
        assert {point["participant_id"] for point in playback["trajectory"]} == (
            participant_ids
        )
        participant_order = {
            item["id"]: index for index, item in enumerate(playback["participants"])
        }
        trajectory_order = [
            (point["tick"], participant_order[point["participant_id"]])
            for point in playback["trajectory"]
        ]
        assert trajectory_order == sorted(trajectory_order)
        for participant_id in participant_order:
            ticks = [
                point["tick"]
                for point in playback["trajectory"]
                if point["participant_id"] == participant_id
            ]
            assert ticks
            assert ticks == sorted(set(ticks))
        if scenario_id == "pedestrian_red_light_crossing":
            pedestrian_ticks = [
                point["tick"]
                for point in playback["trajectory"]
                if point["participant_id"] == "pedestrian"
            ]
            assert pedestrian_ticks[0] == 10
        assert {item["role"] for item in playback["participants"]} <= P1_ROLES
        assert sum(item["role"] == "ego" for item in playback["participants"]) == 1


def test_browser_defaults_to_recorded_ego_follow_and_retains_all_camera_modes(
    browser: Browser,
    service_factory,
) -> None:
    service = service_factory(timeout_seconds=120)
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    page.goto(service.base_url)
    expect(page.locator("#app-status")).to_have_text("Ready")
    page.locator("#studio-template-select").select_option("smarts:highway_merge")
    page.locator("#studio-run").click()
    expect(page.locator("#terminal-panel")).to_be_visible(timeout=120_000)
    expect(page.locator("#playback-panel")).to_be_visible(timeout=30_000)

    canvas = page.locator("#replay-canvas")
    expect(canvas).to_have_attribute("data-evidence-backend", "scenarioforge.smarts")
    expect(canvas).to_have_attribute("data-traffic-rule", "right-hand-traffic")
    expect(canvas).to_have_attribute("data-camera-mode", "ego-follow")
    assert page.locator("#camera-mode option").evaluate_all(
        "options => options.map(option => option.value)"
    ) == ["ego-follow", "overview", "fixed", "free"]

    page.locator("#replay-timeline").evaluate(
        "element => { element.value = '5'; element.dispatchEvent(new Event('input', {bubbles: true})); }"
    )
    first = json.loads(canvas.get_attribute("data-follow-pose") or "{}")
    page.locator("#replay-timeline").evaluate(
        "element => { element.value = '10'; element.dispatchEvent(new Event('input', {bubbles: true})); }"
    )
    second = json.loads(canvas.get_attribute("data-follow-pose") or "{}")
    assert first["source_tick"] == 5
    assert second["source_tick"] == 10
    assert first["position_m"] != second["position_m"]
    assert first["camera_position"] != second["camera_position"]
    assert first["look_at"] != second["look_at"]
    page.close()


def test_pedestrian_late_spawn_reaches_ready_replay_canvas(
    browser: Browser,
    service_factory,
) -> None:
    service = service_factory(timeout_seconds=120)
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    page.goto(service.base_url)
    expect(page.locator("#app-status")).to_have_text("Ready")
    page.locator("#studio-template-select").select_option(
        "smarts:pedestrian_red_light_crossing"
    )
    page.locator("#studio-run").click()
    expect(page.locator("#terminal-panel")).to_be_visible(timeout=120_000)
    expect(page.locator("#playback-panel")).to_be_visible(timeout=30_000)

    replay = page.locator("#replay-canvas")
    expect(replay).to_have_attribute("data-render-state", "ready")
    expect(replay.locator("canvas")).to_have_count(1)
    expect(page.locator("#participant-legend")).to_contain_text("pedestrian")
    page.close()
