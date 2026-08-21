from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import zipfile
from pathlib import Path
from typing import Any

from playwright.sync_api import Browser, Page, expect


ROOT = Path(__file__).resolve().parents[3]
PRESETS = [
    "brake_lead",
    "construction_merge",
    "dangerous_cut_in",
    "highway_merge",
    "unprotected_left_turn",
]
EXPECTED = {
    "brake_lead": ("near_miss", "straight"),
    "construction_merge": ("safe_pass", "lane_closure"),
    "dangerous_cut_in": ("collision_failure", "corridor_merge"),
    "highway_merge": ("safe_pass", "ramp_merge"),
    "unprotected_left_turn": ("near_miss", "intersection"),
}


def _request(page: Page, path: str) -> dict[str, Any]:
    return page.evaluate(
        """
        async (path) => {
          const response = await fetch(path, {credentials: "same-origin"});
          return {status: response.status, body: await response.json()};
        }
        """,
        path,
    )


def _angular_error(left: float, right: float) -> float:
    return abs((left - right + 180.0) % 360.0 - 180.0)


def _assert_heading_tangent_contract(trajectory: list[dict[str, Any]]) -> int:
    tracks: dict[str, list[dict[str, Any]]] = {}
    for point in trajectory:
        tracks.setdefault(point["participant_id"], []).append(point)
    checked = 0
    for points in tracks.values():
        for previous, current in zip(points, points[1:]):
            delta_x = current["position_m"][0] - previous["position_m"][0]
            delta_y = current["position_m"][1] - previous["position_m"][1]
            displacement = math.hypot(delta_x, delta_y)
            if displacement < 0.25:
                continue
            tangent = math.degrees(math.atan2(delta_y, delta_x))
            assert _angular_error(current["heading_deg"], tangent) <= 10.0
            checked += 1
    assert checked > 0
    return checked


def _canvas_is_painted(page: Page) -> bool:
    return bool(
        page.locator("#replay-canvas canvas").evaluate(
            """
            canvas => {
              const probe = document.createElement("canvas");
              probe.width = 32;
              probe.height = 32;
              const context = probe.getContext("2d");
              context.drawImage(canvas, 0, 0, 32, 32);
              const pixels = context.getImageData(0, 0, 32, 32).data;
              let min = 255;
              let max = 0;
              let opaque = 0;
              for (let index = 0; index < pixels.length; index += 4) {
                min = Math.min(min, pixels[index], pixels[index + 1], pixels[index + 2]);
                max = Math.max(max, pixels[index], pixels[index + 1], pixels[index + 2]);
                if (pixels[index + 3] > 0) opaque += 1;
              }
              return opaque > 900 && max - min > 20;
            }
            """
        )
    )


def _evidence_root(tmp_path: Path) -> tuple[Path, bool, str | None]:
    configured = os.environ.get("SCENARIOFORGE_VISUAL_EVIDENCE_DIR")
    candidate = os.environ.get("SCENARIOFORGE_CANDIDATE_COMMIT")
    root = Path(configured) if configured else tmp_path / "visual-evidence"
    if not root.is_absolute():
        root = ROOT / root
    root.mkdir(parents=True, exist_ok=True)
    candidate_bound = candidate is not None
    if candidate_bound:
        assert candidate is not None
        assert len(candidate) in {40, 64}
        assert all(character in "0123456789abcdef" for character in candidate)
    return root, candidate_bound, candidate


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _media_record(
    kind: str,
    path: Path,
    root: Path,
    *,
    chromium_version: str,
    candidate_commit: str,
    run: dict[str, str],
    associated_runs: list[dict[str, str]],
) -> dict[str, object]:
    return {
        "kind": kind,
        "path": path.relative_to(root).as_posix(),
        "sha256": _digest(path),
        "size_bytes": path.stat().st_size,
        "chromium_version": chromium_version,
        "candidate_commit": candidate_commit,
        "run_id": run["run_id"],
        "attempt_id": run["attempt_id"],
        "associated_runs": associated_runs,
    }


def _scan_payloads(path: Path) -> list[bytes]:
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            return [
                archive.read(name)
                for name in archive.namelist()
                if not name.endswith("/")
            ]
    return [path.read_bytes()]


def _write_candidate_receipts(
    root: Path,
    *,
    chromium_version: str,
    candidate_commit: str,
    runs: list[dict[str, str]],
    screenshot: Path,
    trace: Path,
    video: Path,
    secrets: list[str],
) -> None:
    primary_run = runs[-1]
    media = [
        _media_record(
            kind,
            path,
            root,
            chromium_version=chromium_version,
            candidate_commit=candidate_commit,
            run=primary_run,
            associated_runs=runs,
        )
        for kind, path in (
            ("screenshot", screenshot),
            ("trace", trace),
            ("video", video),
        )
    ]
    forbidden = [
        value.encode("utf-8")
        for value in secrets
        if value
    ] + [str(ROOT).encode("utf-8")]
    findings: list[dict[str, str]] = []
    for item, path in zip(media, (screenshot, trace, video), strict=True):
        payloads = _scan_payloads(path)
        for pattern in forbidden:
            if any(pattern in payload for payload in payloads):
                findings.append(
                    {
                        "media_kind": str(item["kind"]),
                        "finding": "sensitive-canary-or-host-path",
                    }
                )
    sanitization = {
        "schema_version": "scenarioforge.media-sanitization-receipt/v1",
        "status": "passed" if not findings else "failed",
        "candidate_commit": candidate_commit,
        "run_id": primary_run["run_id"],
        "attempt_id": primary_run["attempt_id"],
        "scanned_media": [str(item["kind"]) for item in media],
        "checks": [
            "session-token",
            "configured-canary",
            "repository-host-path",
        ],
        "findings": findings,
    }
    assert sanitization["status"] == "passed", findings
    receipt = {
        "schema_version": "scenarioforge.release-gate-media-receipt/v1",
        "scope": "release-gate-sidecar",
        "ordinary_run_artifact": False,
        "ordinary_run_quota_applies": False,
        "candidate_commit": candidate_commit,
        "chromium_version": chromium_version,
        "run_id": primary_run["run_id"],
        "attempt_id": primary_run["attempt_id"],
        "runs": runs,
        "media": media,
        "sanitization_status": "passed",
        "sanitization_receipt": "sanitization-canary-receipt.json",
    }
    (root / "sanitization-canary-receipt.json").write_text(
        json.dumps(sanitization, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (root / "media-sidecar-receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def test_visual_replay_real_metadrive_chromium_and_candidate_sidecars(
    browser: Browser,
    service_factory,
    tmp_path: Path,
) -> None:
    evidence, candidate_bound, candidate_commit = _evidence_root(tmp_path)
    screenshots = evidence / "screenshots"
    traces = evidence / "traces"
    videos = evidence / "videos"
    for directory in (screenshots, traces, videos):
        directory.mkdir(parents=True, exist_ok=True)

    service = service_factory(timeout_seconds=120)
    context = browser.new_context(
        viewport={"width": 1440, "height": 1100},
        record_video_dir=str(videos),
        record_video_size={"width": 1440, "height": 1100},
    )
    page = context.new_page()
    assert page.video is not None
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
    page.screenshot(path=str(screenshots / "visual-replay-initial.png"), full_page=True)

    catalog = _request(page, "/api/scenarios")["body"]
    assert [item["scenario_id"] for item in catalog["scenarios"]] == PRESETS
    runs: list[dict[str, str]] = []
    playback_by_scenario: dict[str, dict[str, Any]] = {}
    tangent_assertions = 0
    csrf_token = _request(page, "/api/session")["body"]["csrf_token"]

    for scenario_id in PRESETS:
        expected_outcome, topology = EXPECTED[scenario_id]
        page.locator("#scenario-select").select_option(scenario_id)
        expect(page.locator("#scenario-description")).not_to_be_empty()
        with page.expect_response(
            lambda response: response.request.method == "POST"
            and response.url.endswith("/api/runs")
        ) as response_info:
            page.get_by_role("button", name="Run scenario").click()
        reference = response_info.value.json()
        run_id = reference["run_id"]
        expect(page.locator("#run-id")).to_have_text(run_id, timeout=120_000)
        expect(page.locator("#terminal-status")).to_have_text("completed")
        terminal = _request(page, f"/api/runs/{run_id}")["body"]
        playback = _request(page, f"/api/runs/{run_id}/artifacts/trajectory")["body"]
        assert terminal["scenario_outcome"] == expected_outcome
        assert playback["road"]["topology_kind"] == topology
        assert terminal["playable"] is True
        assert playback["trajectory"]
        playback_by_scenario[scenario_id] = playback
        runs.append(
            {
                "scenario_id": scenario_id,
                "run_id": run_id,
                "attempt_id": terminal["attempt_id"],
            }
        )
        tangent_assertions += _assert_heading_tangent_contract(playback["trajectory"])

        expect(page.locator("#playback-panel")).to_be_visible()
        expect(page.locator("#replay-canvas canvas")).to_have_count(1)
        assert _canvas_is_painted(page)
        canvas = page.locator("#replay-canvas")
        expect(canvas).to_have_attribute(
            "data-replay-scene-schema", "scenarioforge.replay-scene/v1"
        )
        expect(canvas).to_have_attribute("data-camera-mode", "ego-follow")
        expect(canvas).to_have_attribute(
            "data-heading-interpolation", "shortest-wrapped-arc"
        )
        expect(canvas).to_have_attribute(
            "data-coordinate-contract", "right-handed-x-forward-y-up"
        )
        assert float(canvas.get_attribute("data-camera-offset-rear-m") or "nan") == 8.0
        assert float(canvas.get_attribute("data-camera-offset-height-m") or "nan") == 4.0
        assert float(canvas.get_attribute("data-camera-look-ahead-m") or "nan") == 12.0
        assert float(canvas.get_attribute("data-follow-error-m") or "nan") <= 2.0
        assert float(canvas.get_attribute("data-look-direction-error-deg") or "nan") <= 5.0
        expect(page.locator("#road-legend")).to_contain_text("recorded")
        assert "not applicable" in page.locator("#road-legend").inner_text().lower()

        camera_values = page.locator("#camera-mode option").evaluate_all(
            "options => options.map(option => option.value)"
        )
        assert camera_values[0] == "ego-follow"
        assert "overview" in camera_values
        page.locator("#camera-mode").select_option("overview")
        expect(canvas).to_have_attribute("data-camera-mode", "overview")
        page.locator("#camera-mode").select_option("ego-follow")

        if scenario_id == "brake_lead":
            events = {event["event_id"]: event for event in playback["events"]}
            brake_event = events["lead-hard-brake"]
            page.locator("#event-positions .event-marker").filter(
                has_text="lead-hard-brake"
            ).click()
            expect(
                page.locator("#participant-legend [data-participant-id='lead']")
            ).to_have_attribute("data-brake-state", "on")
            expect(page.locator("#active-events")).to_contain_text("lead hard brake")
            page.screenshot(
                path=str(screenshots / "visual-replay-critical.png"), full_page=True
            )
            lead_speeds = [
                point["speed_mps"]
                for point in playback["trajectory"]
                if point["participant_id"] == "lead"
                and brake_event["effect_state_tick"]
                <= point["tick"]
                <= brake_event["trigger_tick"] + brake_event["duration_ticks"]
            ]
            assert sum(
                current < previous - 0.5
                for previous, current in zip(lead_speeds, lead_speeds[1:])
            ) >= 3

    assert tangent_assertions > 0
    assert [item["scenario_id"] for item in runs] == PRESETS
    assert console_errors == []

    final_playback = playback_by_scenario[PRESETS[-1]]
    page.locator("#replay-speed").select_option("0.25")
    page.locator("#replay-toggle").click()
    expect(page.locator("#replay-toggle")).to_have_text("Pause replay")
    page.locator("#replay-toggle").click()
    for speed in ("0.25", "0.5", "1", "2", "4"):
        page.locator("#replay-speed").select_option(speed)
        assert page.locator("#replay-speed").input_value() == speed
    timeline = page.locator("#replay-timeline")
    assert timeline.get_attribute("data-time-unit") == "seconds"
    stall_start_tick = final_playback["terminal_tick"] - math.ceil(
        5.0 / final_playback["sample_interval_s"]
    )
    timeline.evaluate(
        """
        (element, value) => {
          element.value = String(value);
          element.dispatchEvent(new Event("input", {bubbles: true}));
        }
        """,
        stall_start_tick,
    )
    page.locator("#replay-speed").select_option("4")
    page.locator("#replay-toggle").click()
    expect(page.locator("#replay-toggle")).to_have_text("Pause replay")
    page.evaluate("() => new Promise(requestAnimationFrame)")
    page.evaluate(
        """
        () => {
          const blockedUntil = performance.now() + 1300;
          while (performance.now() < blockedUntil) {
            // Model a real main-thread scheduling gap before the pause click.
          }
        }
        """
    )
    page.evaluate("() => new Promise(requestAnimationFrame)")
    expect(page.locator("#replay-toggle")).to_have_text("Pause replay")
    page.locator("#replay-toggle").click()
    expect(page.locator("#replay-toggle")).to_have_text("Play replay")
    page.locator("#replay-toggle").click()
    expect(page.locator("#replay-toggle")).to_have_text("Play replay")
    page.locator("#replay-toggle").click()
    expect(page.locator("#replay-toggle")).to_have_text("Pause replay")
    page.locator("#replay-toggle").click()
    expect(page.locator("#replay-toggle")).to_have_text("Play replay")

    fractional_time = final_playback["sample_interval_s"] / 2
    timeline.evaluate(
        """
        (element, value) => {
          element.value = String(value);
          element.dispatchEvent(new Event("input", {bubbles: true}));
        }
        """,
        fractional_time,
    )
    assert float(page.locator("#simulation-time").get_attribute("data-time-s") or "nan") == fractional_time
    expect(page.locator("#replay-canvas")).to_have_attribute(
        "data-interpolation-source-ticks", "0,1"
    )
    page.locator("#next-event").click()
    page.locator("#previous-event").click()

    context.tracing.start(screenshots=True, snapshots=True, sources=False)
    page.locator("#replay-restart").click()
    page.locator("#replay-toggle").click()
    page.wait_for_timeout(750)
    page.locator("#replay-toggle").click()
    frame_times = page.evaluate(
        """
        async () => {
          const values = [];
          let previous = performance.now();
          for (let index = 0; index < 120; index += 1) {
            await new Promise(requestAnimationFrame);
            const current = performance.now();
            values.push(current - previous);
            previous = current;
          }
          return values;
        }
        """
    )
    ordered = sorted(float(value) for value in frame_times)
    p95 = ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)]
    assert p95 <= 33.0

    screenshot = screenshots / "visual-replay.png"
    trace = traces / "visual-replay.zip"
    video = videos / "visual-replay.webm"
    page.screenshot(path=str(screenshot), full_page=True)
    context.tracing.stop(path=str(trace))
    video_handle = page.video
    assert video_handle is not None
    page.close()
    raw_video = Path(video_handle.path())
    context.close()
    shutil.move(str(raw_video), video)
    assert screenshot.stat().st_size > 10_000
    assert trace.stat().st_size > 1_000
    assert video.stat().st_size > 1_000

    if candidate_bound:
        assert candidate_commit is not None
        _write_candidate_receipts(
            evidence,
            chromium_version=browser.version,
            candidate_commit=candidate_commit,
            runs=runs,
            screenshot=screenshot,
            trace=trace,
            video=video,
            secrets=[
                csrf_token,
                os.environ.get("SCENARIOFORGE_MEDIA_CANARY", ""),
            ],
        )
        receipt = json.loads(
            (evidence / "media-sidecar-receipt.json").read_text(encoding="utf-8")
        )
        assert [item["kind"] for item in receipt["media"]] == [
            "screenshot",
            "trace",
            "video",
        ]
        assert all(
            item["candidate_commit"] == candidate_commit
            and item["chromium_version"] == browser.version
            and item["run_id"]
            and item["attempt_id"]
            and item["sha256"]
            and item["size_bytes"] > 0
            for item in receipt["media"]
        )

    failure_context = browser.new_context()
    failure_page = failure_context.new_page()
    failure_page.goto(service.base_url)
    failure_page.evaluate(
        "runId => sessionStorage.setItem('scenarioforge.active-run.v1', runId)",
        runs[-1]["run_id"],
    )
    failure_page.add_init_script(
        """
        const original = HTMLCanvasElement.prototype.getContext;
        HTMLCanvasElement.prototype.getContext = function(kind, ...args) {
          if (kind === "webgl" || kind === "webgl2") return null;
          return original.call(this, kind, ...args);
        };
        """
    )
    failure_page.reload()
    expect(failure_page.locator("#replay-canvas")).to_have_attribute(
        "data-render-state", "failed", timeout=30_000
    )
    expect(failure_page.locator(".replay-failure-state")).to_contain_text("WebGL")
    expect(failure_page.locator("#replay-toggle")).to_be_disabled()
    expect(failure_page.locator("#replay-timeline")).to_be_disabled()
    expect(failure_page.locator("#replay-speed")).to_be_disabled()
    assert failure_page.locator("#replay-canvas canvas").count() == 0
    failure_context.close()
