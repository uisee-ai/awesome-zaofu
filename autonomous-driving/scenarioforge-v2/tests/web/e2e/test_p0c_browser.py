from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Browser, Page, expect


ROOT = Path(__file__).resolve().parents[3]
EXPECTED_PRESETS = [
    "brake_lead",
    "construction_merge",
    "dangerous_cut_in",
    "highway_merge",
    "unprotected_left_turn",
]
SCENARIO_EXPECTATIONS = {
    "brake_lead": ("near_miss", "straight", 1, 0),
    "construction_merge": ("safe_pass", "lane_closure", 3, 1),
    "dangerous_cut_in": ("collision_failure", "corridor_merge", 2, 1),
    "highway_merge": ("safe_pass", "ramp_merge", 3, 1),
    "unprotected_left_turn": ("near_miss", "intersection", 6, 1),
}


def _request(
    page: Page,
    path: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    payload: dict[str, object] | None = None,
) -> dict[str, Any]:
    return page.evaluate(
        """
        async ({path, method, headers, payload}) => {
          const response = await fetch(path, {
            method,
            headers,
            credentials: "same-origin",
            body: payload === null ? undefined : JSON.stringify(payload),
          });
          const text = await response.text();
          let body;
          try {
            body = JSON.parse(text);
          } catch (_error) {
            body = text;
          }
          return {status: response.status, body};
        }
        """,
        {
            "path": path,
            "method": method,
            "headers": headers or {},
            "payload": payload,
        },
    )


def _assert_catalog_is_bounded(catalog: dict[str, Any]) -> None:
    assert catalog["schema_version"] == "scenarioforge.scenario-catalog/v2"
    assert catalog["default_scenario_id"] == "brake_lead"
    assert [item["scenario_id"] for item in catalog["scenarios"]] == EXPECTED_PRESETS
    forbidden = {
        "path",
        "url",
        "spec",
        "raw_spec",
        "source",
        "secret",
        "executable",
        "seed",
        "policy",
    }

    def visit(value: object) -> None:
        if isinstance(value, dict):
            assert forbidden.isdisjoint(value)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(catalog)


def _angular_error(left: float, right: float) -> float:
    return abs((left - right + 180.0) % 360.0 - 180.0)


def _assert_heading_follows_motion(trajectory: list[dict[str, Any]]) -> None:
    by_participant: dict[str, list[dict[str, Any]]] = {}
    for point in trajectory:
        by_participant.setdefault(point["participant_id"], []).append(point)
    checked = 0
    for points in by_participant.values():
        for previous, current in zip(points, points[1:]):
            delta_x = current["position_m"][0] - previous["position_m"][0]
            delta_y = current["position_m"][1] - previous["position_m"][1]
            if math.hypot(delta_x, delta_y) < 0.05 or current["speed_mps"] < 1.0:
                continue
            movement_heading = math.degrees(math.atan2(delta_y, delta_x))
            assert _angular_error(current["heading_deg"], movement_heading) < 45.0
            checked += 1
    assert checked > 0


def _evidence_directory(tmp_path: Path) -> Path:
    configured = os.environ.get("SCENARIOFORGE_P0C_EVIDENCE_DIR")
    directory = Path(configured) if configured else tmp_path / "browser-evidence"
    if not directory.is_absolute():
        directory = ROOT / directory
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def test_p0c_catalog_and_negative_requests_use_the_real_product_entry(
    browser: Browser,
    service_factory,
) -> None:
    service = service_factory(timeout_seconds=120)
    context = browser.new_context()
    page = context.new_page()
    page.goto(service.base_url)

    expect(page.locator("#app-status")).to_have_text("Ready")
    expect(page.locator(".eyebrow")).to_have_text("ScenarioForge / P0-C")
    catalog = _request(page, "/api/scenarios")["body"]
    _assert_catalog_is_bounded(catalog)
    selector = page.locator("#scenario-select")
    assert selector.locator("option").evaluate_all(
        "options => options.map(option => option.value)"
    ) == EXPECTED_PRESETS

    selector.select_option("unprotected_left_turn")
    expect(page.locator("#scenario-name")).to_have_text("Unprotected Left Turn")
    expect(page.locator("#scenario-danger")).to_contain_text("conflict zone")
    expect(page.locator("#scenario-reaction")).to_contain_text("yields first")

    session = _request(page, "/api/session")["body"]
    request_headers = {
        "Content-Type": "application/json",
        "X-CSRF-Token": session["csrf_token"],
        "Idempotency-Key": "p0c-browser-negative",
    }
    assert _request(
        page,
        "/api/runs",
        method="POST",
        headers=request_headers,
        payload={"scenario_id": "unknown"},
    ) == {"status": 404, "body": {"detail": "unknown scenario_id"}}
    request_headers["Idempotency-Key"] = "p0c-browser-xss"
    assert _request(
        page,
        "/api/runs",
        method="POST",
        headers=request_headers,
        payload={"scenario_id": "<script>alert(1)</script>"},
    ) == {"status": 400, "body": {"detail": "invalid scenario_id"}}
    assert "<script>alert(1)</script>" not in page.locator("body").inner_text()
    context.close()


@pytest.mark.parametrize("scenario_id", EXPECTED_PRESETS)
def test_each_p0c_scenario_runs_in_real_metadrive_and_replays_in_chromium(
    browser: Browser,
    service_factory,
    tmp_path: Path,
    scenario_id: str,
) -> None:
    expected_outcome, topology, lane_count, conflict_count = SCENARIO_EXPECTATIONS[
        scenario_id
    ]
    evidence_directory = _evidence_directory(tmp_path)
    service = service_factory(timeout_seconds=120)
    context = browser.new_context(viewport={"width": 1440, "height": 1100})
    page = context.new_page()
    console_errors: list[str] = []
    page.on(
        "console",
        lambda message: console_errors.append(
            f"console:{message.type}:{message.text}"
        )
        if message.type == "error"
        else None,
    )
    page.on("pageerror", lambda error: console_errors.append(f"pageerror:{error}"))
    page.goto(service.base_url)
    expect(page.locator("#app-status")).to_have_text("Ready")
    page.locator("#scenario-select").select_option(scenario_id)

    with page.expect_response(
        lambda response: response.request.method == "POST"
        and response.url.endswith("/api/runs")
    ) as response_info:
        page.get_by_role("button", name="Run scenario").click()
    reference = response_info.value.json()
    worker_pid = service.wait_for_worker_pid()
    assert worker_pid > 1
    run_id = reference["run_id"]
    expect(page.locator("#terminal-status")).to_have_text(
        "completed",
        timeout=120_000,
    )

    terminal = _request(page, f"/api/runs/{run_id}")["body"]
    playback = _request(page, f"/api/runs/{run_id}/artifacts/trajectory")["body"]
    assert terminal["schema_version"] == "scenarioforge.terminal-evidence/v2"
    assert playback["schema_version"] == "scenarioforge.playback/v2"
    assert terminal["scenario_id"] == playback["scenario_id"] == scenario_id
    assert terminal["execution_status"] == "completed"
    assert terminal["scenario_outcome"] == expected_outcome
    assert terminal["playable"] is True
    assert playback["trajectory"]
    assert playback["events"]
    assert playback["road"]["topology_kind"] == topology
    geometry = playback["road"]["geometry"]
    assert geometry["schema_version"] == "scenarioforge.road-geometry/v1"
    assert geometry["source"] == "metadrive-road-network"
    assert len(geometry["lanes"]) == lane_count
    assert len(geometry["conflict_zones"]) == conflict_count
    assert [lane["lane_id"] for lane in geometry["lanes"]] == [
        lane["id"] for lane in playback["road"]["lanes"]
    ]
    assert all(
        len(lane["centerline_m"])
        == len(lane["left_boundary_m"])
        == len(lane["right_boundary_m"])
        >= 2
        for lane in geometry["lanes"]
    )
    _assert_heading_follows_motion(playback["trajectory"])

    expect(page.locator("#playback-panel")).to_be_visible()
    expect(page.locator("#replay-canvas canvas")).to_have_count(1)
    expect(page.locator("#replay-canvas")).to_have_attribute(
        "data-topology-kind", topology
    )
    expect(page.locator("#replay-canvas")).to_have_attribute(
        "data-geometry-source", "metadrive-road-network"
    )
    expect(page.locator("#road-legend")).to_contain_text("recorded MetaDrive geometry")
    expect(page.locator("#replay-outcome")).to_have_text(
        f"Recorded result: {expected_outcome.replace('_', ' ')}"
    )
    body_text = page.locator("body").inner_text()
    assert "[object Object]" not in body_text
    assert "ScenarioForge / P0-B" not in body_text
    assert page.locator("#participant-legend li").count() == len(
        playback["participants"]
    )
    assert all(
        "m/s" in text for text in page.locator("#participant-legend li").all_inner_texts()
    )

    first_event = playback["events"][0]
    page.locator("#event-positions .event-marker").first.click()
    expect(page.locator("#current-tick")).to_have_text(str(first_event["trigger_tick"]))
    if first_event["action"]["throttle_brake"] < 0:
        event_participant = first_event["participant_id"]
        expect(
            page.locator(
                f'#participant-legend .participant-swatch--{event_participant}'
            ).locator("xpath=..").locator(".participant-state")
        ).to_contain_text("BRAKING")

    page.locator("#replay-restart").click()
    page.locator("#next-event").click()
    assert int(page.locator("#current-tick").inner_text()) > 0
    page.locator("#replay-speed").select_option("2")
    before_play = int(page.locator("#current-tick").inner_text())
    page.locator("#replay-toggle").click()
    expect(page.locator("#replay-toggle")).to_have_text("Pause replay")
    page.wait_for_function(
        "tick => Number(document.querySelector('#current-tick').value) > tick",
        arg=before_play,
        timeout=10_000,
    )
    page.locator("#replay-toggle").click()
    expect(page.locator("#replay-toggle")).to_have_text("Play replay")

    timeline = page.locator("#replay-timeline")
    timeline.evaluate(
        "(element, tick) => { element.value = tick; element.dispatchEvent(new Event('input', {bubbles: true})); }",
        str(playback["terminal_tick"]),
    )
    expect(page.locator("#current-tick")).to_have_text(str(playback["terminal_tick"]))
    if conflict_count:
        page.locator("#camera-mode").select_option("conflict")
        expect(page.locator("#replay-canvas")).to_have_attribute(
            "data-camera-scope", "verified-conflict-geometry"
        )
        expect(page.locator("#road-legend")).to_contain_text("Red hatch")

    if scenario_id == "brake_lead":
        events = {event["event_id"]: event for event in playback["events"]}
        assert events["lead-hard-brake"]["duration_ticks"] == 6
        assert events["ego-avoidance-brake"]["duration_ticks"] == 6
        by_tick = {
            (point["participant_id"], point["tick"]): point
            for point in playback["trajectory"]
        }
        for participant_id, start_tick in (("lead", 35), ("ego", 40)):
            speeds = [
                by_tick[(participant_id, tick)]["speed_mps"]
                for tick in range(start_tick, start_tick + 7)
            ]
            assert sum(
                current < previous - 0.5
                for previous, current in zip(speeds, speeds[1:])
            ) >= 3
    if scenario_id == "unprotected_left_turn":
        events = {event["event_id"]: event for event in playback["events"]}
        assert events["yield-started"]["trigger_tick"] == 20
        assert events["yield-started"]["duration_ticks"] == 19
        ego = [
            point
            for point in playback["trajectory"]
            if point["participant_id"] == "ego"
        ]
        oncoming_conflict = [
            point["tick"]
            for point in playback["trajectory"]
            if point["participant_id"] == "oncoming"
            and point["lane_id"] == "oncoming-through"
        ]
        ego_conflict = [point["tick"] for point in ego if point["lane_id"] == "ego-left-turn"]
        assert max(oncoming_conflict) < min(ego_conflict)
        assert max(point["speed_mps"] for point in ego if 28 <= point["tick"] <= 39) < 0.5
        assert ego[-1]["route_completed"] is True
    if scenario_id == "dangerous_cut_in":
        assert terminal["metrics"]["collision"] is True
        expect(page.locator("#recorded-evidence-badge")).to_have_text(
            "Recorded collision evidence"
        )

    screenshot_path = evidence_directory / f"{scenario_id}.png"
    page.screenshot(path=str(screenshot_path), full_page=True)
    assert screenshot_path.is_file() and screenshot_path.stat().st_size > 10_000
    assert console_errors == []
    report = {
        "schema_version": "scenarioforge.playwright-evidence/v1",
        "role": "fix-lane-0-development",
        "browser": "playwright-chromium",
        "url": service.base_url,
        "scenario_id": scenario_id,
        "run_id": run_id,
        "attempt_id": terminal["attempt_id"],
        "worker_pid_observed": worker_pid,
        "execution_status": terminal["execution_status"],
        "scenario_outcome": terminal["scenario_outcome"],
        "topology_kind": topology,
        "road_geometry_source": geometry["source"],
        "assertions": [
            "real_worker_observed",
            "immutable_terminal_and_playback_bound",
            "real_lane_and_conflict_geometry_rendered",
            "heading_matches_motion",
            "play_pause_speed_timeline_event_navigation",
            "result_summary_and_participant_state_visible",
        ],
        "console_errors": console_errors,
        "screenshot": screenshot_path.name,
    }
    (evidence_directory / f"{scenario_id}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    context.close()
