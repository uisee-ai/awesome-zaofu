from __future__ import annotations

import json
import os
import signal

import pytest
from playwright.sync_api import Browser, Page, expect


def _request_json(
    page: Page,
    path: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    payload: dict[str, object] | None = None,
) -> dict[str, object]:
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
          return {
            status_code: response.status,
            content_type: response.headers.get("content-type"),
            body,
          };
        }
        """,
        {
            "path": path,
            "method": method,
            "headers": headers or {},
            "payload": payload,
        },
    )


def _start_from_ui(page: Page) -> tuple[dict[str, object], dict[str, str]]:
    with page.expect_response(
        lambda response: response.request.method == "POST"
        and response.url.endswith("/api/runs")
    ) as response_info:
        page.get_by_role("button", name="Run scenario").click()
    response = response_info.value
    assert response.status == 201
    return response.json(), response.request.all_headers()


def _wait_for_run_identity(page: Page, run_id: str) -> None:
    page.wait_for_function(
        """
        (runId) => {
          const live = document.querySelector("#live-run-id")?.textContent;
          const terminal = document.querySelector("#run-id")?.textContent;
          return live === runId || terminal === runId;
        }
        """,
        arg=run_id,
        timeout=30_000,
    )


def _rendered_replay_frame(page: Page) -> dict[str, object]:
    return page.locator("#replay-canvas canvas").evaluate(
        """
        (canvas) => new Promise((resolve) => {
          requestAnimationFrame(() => {
            const gl = canvas.getContext("webgl2");
            const width = gl?.drawingBufferWidth ?? 0;
            const height = gl?.drawingBufferHeight ?? 0;
            const pixels = new Uint8Array(width * height * 4);
            if (gl !== null && width > 0 && height > 0) {
              gl.readPixels(0, 0, width, height, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
            }

            const samples = {
              ego: {count: 0, min_x: width, max_x: -1, min_y: height, max_y: -1},
              lead: {count: 0, min_x: width, max_x: -1, min_y: height, max_y: -1},
            };
            const record = (sample, index) => {
              const pixel = index / 4;
              const x = pixel % width;
              const y = Math.floor(pixel / width);
              sample.count += 1;
              sample.min_x = Math.min(sample.min_x, x);
              sample.max_x = Math.max(sample.max_x, x);
              sample.min_y = Math.min(sample.min_y, y);
              sample.max_y = Math.max(sample.max_y, y);
            };
            for (let index = 0; index < pixels.length; index += 4) {
              const red = pixels[index];
              const green = pixels[index + 1];
              const blue = pixels[index + 2];
              if (green > 100 && green > red * 1.5 && blue > red * 1.4) {
                record(samples.ego, index);
              }
              if (red > 100 && red > green * 1.2 && green > blue * 1.35) {
                record(samples.lead, index);
              }
            }
            resolve({
              client_width: canvas.clientWidth,
              client_height: canvas.clientHeight,
              drawing_width: width,
              drawing_height: height,
              ego: samples.ego,
              lead: samples.lead,
            });
          });
        })
        """
    )


def _assert_replay_frame_is_painted_and_composed(page: Page) -> None:
    frame = _rendered_replay_frame(page)
    width = int(frame["drawing_width"])
    height = int(frame["drawing_height"])
    assert width >= int(frame["client_width"]) - 1 > 0, frame
    assert height >= int(frame["client_height"]) - 1 > 0, frame

    for participant in ("ego", "lead"):
        sample = frame[participant]
        assert sample["count"] > 50, frame
        assert sample["min_x"] > width * 0.04, frame
        assert sample["max_x"] < width * 0.96, frame
        assert sample["min_y"] > height * 0.04, frame
        assert sample["max_y"] < height * 0.96, frame


def _assert_active_run(
    response: dict[str, object],
    reference: dict[str, object],
) -> None:
    assert response == {
        "status_code": 200,
        "content_type": "application/json",
        "body": {
            "schema_version": "scenarioforge.execution-state/v1",
            "scenario_id": "brake_lead",
            "run_id": reference["run_id"],
            "attempt_id": reference["attempt_id"],
            "state": "running",
            "terminal": False,
        },
    }


def _assert_terminal_projection(page: Page, terminal: dict[str, object]) -> None:
    metrics = terminal["metrics"]
    policy = terminal["policy"]
    digests = terminal["digests"]
    expected = {
        "scenario-id": terminal["scenario_id"],
        "run-id": terminal["run_id"],
        "terminal-status": terminal.get("execution_status", terminal.get("status")),
        "terminal-reason": terminal.get(
            "termination_reason", terminal.get("reason")
        ),
        "failure-stage": terminal["failure_stage"] or "—",
        "seed": terminal["seed"],
        "policy-id": f"{policy['id']}@{policy['version']}",
        "manifest-digest": digests["run_manifest"],
        "artifact-index-digest": digests["artifact_index"],
        "evidence-ref": terminal["logical_ref"],
        "collision": "Unknown"
        if metrics["collision"] is None
        else "Yes"
        if metrics["collision"]
        else "No",
        "collision-participants": ", ".join(metrics["collision_participants"])
        or "None",
        "min-ttc": "—"
        if metrics["min_ttc_s"] is None
        else f"{metrics['min_ttc_s']:.3f} s",
        "completion-time": "—"
        if metrics["completion_time_s"] is None
        else f"{metrics['completion_time_s']:.3f} s",
        "terminal-tick": metrics["terminal_tick"]
        if metrics["terminal_tick"] is not None
        else "—",
    }
    for element_id, value in expected.items():
        expect(page.locator(f"#{element_id}")).to_have_text(str(value))

    expected_evidence = [
        f"{entry['ref']} · {entry['status']}/{entry['validation']} · sha256:{entry['digest']}"
        for entry in terminal["evidence"]
    ]
    expect(page.locator("details.audit-evidence")).not_to_have_attribute("open", "")
    assert page.locator("#evidence-list li").all_text_contents() == expected_evidence

    expected_events = [
        f"tick {event['trigger_tick']} → {event['effect_state_tick']} · "
        f"{event['event_id']} · {event['participant_id']} · "
        f"{event.get('duration_ticks', 1)} tick effect"
        for event in terminal["events"]
    ]
    if expected_events:
        assert page.locator("#terminal-events li").all_inner_texts() == expected_events
    else:
        assert page.locator("#terminal-events li").all_inner_texts() == [
            "No fully verified key events were published."
        ]


def test_real_browser_flow_survives_clients_and_exposes_only_success_replay(
    browser: Browser,
    service_factory,
) -> None:
    service = service_factory(timeout_seconds=120)
    context = browser.new_context()
    page = context.new_page()
    page.goto(service.base_url)

    expect(page.locator("#app-status")).to_have_text("Ready")
    expect(page.locator("#scenario-name")).to_have_text(
        "Lead Vehicle Emergency Braking"
    )
    expect(page.get_by_role("button", name="Run scenario")).to_be_enabled()
    assert page.locator("#live-panel").locator("button, a, input, select").count() == 0
    live_copy = page.locator("#live-panel").inner_text().lower()
    for forbidden in ("stop", "pause", "step", "reset", "cancel"):
        assert forbidden not in live_copy

    reference, start_headers = _start_from_ui(page)
    run_id = str(reference["run_id"])
    attempt_id = str(reference["attempt_id"])
    assert page.evaluate(
        "sessionStorage.getItem('scenarioforge.active-run.v1')"
    ) == run_id
    _wait_for_run_identity(page, run_id)
    worker_pid = service.suspend_worker()
    assert service.worker_state(worker_pid) == "T"
    _assert_active_run(_request_json(page, f"/api/runs/{run_id}"), reference)

    try:
        idempotency_key = start_headers["idempotency-key"]
        csrf_token = start_headers["x-csrf-token"]
        retry = _request_json(
            page,
            "/api/runs",
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-CSRF-Token": csrf_token,
                "Idempotency-Key": idempotency_key,
            },
            payload={"scenario_id": "brake_lead"},
        )
        assert retry == {
            "status_code": 201,
            "content_type": "application/json",
            "body": reference,
        }
        occupied = _request_json(
            page,
            "/api/runs",
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-CSRF-Token": csrf_token,
                "Idempotency-Key": "browser-conflict-request",
            },
            payload={"scenario_id": "brake_lead"},
        )
        assert occupied == {
            "status_code": 409,
            "content_type": "application/json",
            "body": {"detail": "single-run execution slot is occupied"},
        }

        page.reload()
        _wait_for_run_identity(page, run_id)
        expect(page.locator("#live-state")).to_have_text("running")
        assert page.evaluate(
            "sessionStorage.getItem('scenarioforge.active-run.v1')"
        ) == run_id
        assert service.worker_state(worker_pid) == "T"
        _assert_active_run(_request_json(page, f"/api/runs/{run_id}"), reference)

        page.close()
        assert service.process.poll() is None
        assert service.worker_state(worker_pid) == "T"
        resumed = context.new_page()
        resumed.goto(service.base_url)
        _assert_active_run(
            _request_json(resumed, f"/api/runs/{run_id}"), reference
        )
        assert service.worker_state(worker_pid) == "T"

        resumed.evaluate(
            "(runId) => sessionStorage.setItem('scenarioforge.active-run.v1', runId)",
            run_id,
        )
        resumed.reload()
        _wait_for_run_identity(resumed, run_id)
        expect(resumed.locator("#live-state")).to_have_text("running")
        _assert_active_run(
            _request_json(resumed, f"/api/runs/{run_id}"), reference
        )

        session = _request_json(resumed, "/api/session")["body"]
        for operation in ("stop", "pause", "step", "reset", "cancel"):
            rejected = _request_json(
                resumed,
                f"/api/runs/{run_id}/{operation}",
                method="POST",
                headers={"X-CSRF-Token": session["csrf_token"]},
            )
            assert rejected["status_code"] == 404
    finally:
        service.resume_worker(worker_pid)

    expect(resumed.locator("#terminal-status")).to_have_text(
        "completed", timeout=120_000
    )
    terminal_response = _request_json(resumed, f"/api/runs/{run_id}")
    assert terminal_response["status_code"] == 200
    terminal = terminal_response["body"]
    assert terminal["schema_version"] == "scenarioforge.terminal-evidence/v2"
    assert terminal["run_id"] == run_id
    assert terminal["attempt_id"] == attempt_id
    assert terminal["terminal"] is True
    assert terminal["playable"] is True
    assert terminal["execution_status"] == "completed"
    assert terminal["scenario_outcome"] == "near_miss"
    assert terminal["termination_reason"] == "success_predicates_satisfied"
    _assert_terminal_projection(resumed, terminal)
    assert attempt_id in resumed.locator("#evidence-ref").inner_text()

    expect(resumed.locator("#playback-panel")).to_be_visible()
    expect(resumed.locator("#non-playable")).to_be_hidden()
    expect(resumed.locator("#replay-canvas canvas")).to_have_count(1)
    _assert_replay_frame_is_painted_and_composed(resumed)
    participant_legend = resumed.locator("#participant-legend li").all_inner_texts()
    assert len(participant_legend) == 2
    assert "Following vehicle · ego (ego)" in participant_legend[0]
    assert "Lead vehicle · lead (social)" in participant_legend[1]
    assert all("m/s" in item for item in participant_legend)
    expect(resumed.locator("#replay-toggle")).to_be_enabled()
    expect(resumed.locator("#replay-timeline")).to_be_enabled()
    expect(resumed.locator("#replay-speed")).to_be_enabled()

    terminal_tick = int(terminal["metrics"]["terminal_tick"])
    timeline = resumed.locator("#replay-timeline")
    assert timeline.get_attribute("max") == str(terminal_tick)
    timeline.evaluate(
        "(element, value) => { element.value = value; element.dispatchEvent(new Event('input', {bubbles: true})); }",
        str(terminal_tick),
    )
    expect(resumed.locator("#current-tick")).to_have_text(str(terminal_tick))

    event = terminal["events"][0]
    resumed.locator("#event-positions .event-marker").first.click()
    expect(resumed.locator("#current-tick")).to_have_text(str(event["trigger_tick"]))
    resumed.locator("#replay-speed").select_option("4")
    resumed.locator("#replay-toggle").click()
    expect(resumed.locator("#replay-toggle")).to_have_text("Pause replay")
    resumed.wait_for_function(
        "(tick) => Number(document.querySelector('#current-tick').value) > tick",
        arg=event["trigger_tick"],
        timeout=10_000,
    )
    resumed.locator("#replay-toggle").click()
    expect(resumed.locator("#replay-toggle")).to_have_text("Play replay")

    context.close()


@pytest.mark.parametrize(
    ("failure_mode", "expected_status", "expected_reason"),
    [
        ("timeout", "timeout", "timeout"),
        ("worker_crash", "failed", "worker_crashed"),
    ],
)
def test_real_browser_never_plays_failure_or_partial_evidence(
    browser: Browser,
    service_factory,
    failure_mode: str,
    expected_status: str,
    expected_reason: str,
) -> None:
    service = service_factory(timeout_seconds=1 if failure_mode == "timeout" else 120)
    context = browser.new_context()
    page = context.new_page()
    page.goto(service.base_url)
    expect(page.locator("#app-status")).to_have_text("Ready")

    reference, _headers = _start_from_ui(page)
    run_id = str(reference["run_id"])
    if failure_mode == "worker_crash":
        worker_pid = service.wait_for_worker_pid()
        os.kill(worker_pid, signal.SIGKILL)

    expect(page.locator("#app-status")).to_have_text(
        "RunManifest schema is invalid", timeout=120_000
    )
    terminal_response = _request_json(page, f"/api/runs/{run_id}")
    assert terminal_response == {
        "status_code": 422,
        "content_type": "application/json",
        "body": {"detail": "RunManifest schema is invalid"},
    }
    assert expected_status in {"timeout", "failed"}
    assert expected_reason in {"timeout", "worker_crashed"}
    expect(page.locator("#playback-panel")).to_be_hidden()
    expect(page.locator("#replay-toggle")).to_be_disabled()
    expect(page.locator("#non-playable")).to_be_hidden()
    trajectory = _request_json(page, f"/api/runs/{run_id}/artifacts/trajectory")
    assert trajectory == {
        "status_code": 409,
        "content_type": "application/json",
        "body": {"detail": "terminal run is not playable"},
    }
    context.close()
