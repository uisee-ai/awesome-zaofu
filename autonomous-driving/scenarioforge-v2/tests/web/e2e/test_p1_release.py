from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import zipfile
from itertools import pairwise
from pathlib import Path
from typing import Any
from urllib.parse import quote

from playwright.sync_api import Browser, Page, expect

ROOT = Path(__file__).resolve().parents[3]
P1_SCENARIOS = (
    "highway_merge",
    "competitive_lane_change",
    "cross_traffic_red_light_violation",
    "unprotected_left_turn",
    "pedestrian_red_light_crossing",
)
ACCEPTANCE_COVERAGE = (
    "AC-P1-005",
    "AC-P1-006",
    "AC-P1-007",
    "AC-P1-008",
    "AC-P1-009",
    "AC-P1-011",
    "AC-P1-014",
    "AC-P1-017",
    "AC-P1-018",
)
HEX_COMMIT = re.compile(r"^[0-9a-f]{40}$")


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


def _source_candidate_commit() -> str:
    configured = os.environ.get("SCENARIOFORGE_CANDIDATE_COMMIT")
    if configured is None:
        configured = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    assert HEX_COMMIT.fullmatch(configured)
    return configured


def _evidence_root(tmp_path: Path) -> Path:
    configured = os.environ.get("SCENARIOFORGE_RELEASE_EVIDENCE_DIR")
    root = Path(configured) if configured else tmp_path.parent / "p1-release-evidence"
    if not root.is_absolute():
        root = ROOT / root
    root.mkdir(parents=True, exist_ok=True)
    root = root.resolve(strict=True)
    try:
        root.relative_to(ROOT.resolve(strict=True))
    except ValueError:
        pass
    else:
        raise AssertionError("release evidence must use a repository-external sidecar")
    for name in ("screenshots", "traces", "videos"):
        directory = root / name
        if directory.exists():
            shutil.rmtree(directory)
        directory.mkdir()
    (root / "p1-release-browser-report.json").unlink(missing_ok=True)
    return root


def _marked_secret() -> str:
    value = os.environ.get("SCENARIOFORGE_MARKED_SECRET", "[REDACTED_SECRET]")
    assert len(value) >= 8
    return value


def _canaries() -> dict[str, str]:
    marked = _marked_secret()
    return {
        "environment": marked,
        "request_token": f"{marked}:request-token",
        "cookie": f"{marked}:cookie",
        "authorization": f"{marked}:authorization",
        "controlled_file": f"{marked}:controlled-file",
        "rejected_field": f"{marked}:rejected-field",
    }


def _sanitized_variants(values: tuple[str, ...]) -> tuple[bytes, ...]:
    variants: set[bytes] = set()
    for value in values:
        if not value:
            continue
        encoded = value.encode("utf-8")
        variants.update(
            {
                encoded,
                quote(value, safe="").encode("utf-8"),
                base64.b64encode(encoded),
                encoded.hex().encode("ascii"),
            }
        )
    return tuple(sorted(variants, key=len, reverse=True))


def _sanitize_trace_archive(path: Path, *, sensitive_values: tuple[str, ...]) -> None:
    replacement = b"<redacted>"
    variants = _sanitized_variants(sensitive_values)
    sanitized = path.with_name(f".{path.name}.sanitized")
    with (
        zipfile.ZipFile(path) as source,
        zipfile.ZipFile(
            sanitized,
            "w",
            compression=zipfile.ZIP_DEFLATED,
        ) as destination,
    ):
        for info in source.infolist():
            payload = b"" if info.is_dir() else source.read(info)
            name = info.filename.encode("utf-8")
            for variant in variants:
                payload = payload.replace(variant, replacement)
                name = name.replace(variant, replacement)
            destination.writestr(name.decode("utf-8"), payload)
    sanitized.replace(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _media_item(path: Path, evidence: Path) -> dict[str, object]:
    return {
        "byte_count": path.stat().st_size,
        "path": path.relative_to(evidence).as_posix(),
        "sha256": _sha256(path),
    }


def _media_package(scenarios: list[dict[str, Any]]) -> dict[str, object]:
    manifest = [
        {
            "byte_count": scenario["media"][kind]["byte_count"],
            "path": scenario["media"][kind]["path"],
            "sha256": scenario["media"][kind]["sha256"],
        }
        for scenario in scenarios
        for kind in ("screenshot", "video", "trace")
    ]
    payload = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    digest = hashlib.sha256(payload).hexdigest()
    return {
        "schema_version": "scenarioforge.p1-media-package/v1",
        "artifact_count": len(manifest),
        "content_digest": digest,
        "content_ref": f"sha256:{digest}",
    }


def _angular_error(left: float, right: float) -> float:
    return abs((left - right + 180.0) % 360.0 - 180.0)


def _assert_recorded_headings(playback: dict[str, Any]) -> int:
    tracks: dict[str, list[dict[str, Any]]] = {}
    for point in playback["trajectory"]:
        tracks.setdefault(point["participant_id"], []).append(point)
    checked = 0
    for points in tracks.values():
        for previous, current in pairwise(points):
            delta_x = current["position_m"][0] - previous["position_m"][0]
            delta_y = current["position_m"][1] - previous["position_m"][1]
            if math.hypot(delta_x, delta_y) < 0.25:
                continue
            tangent = math.degrees(math.atan2(delta_y, delta_x))
            assert _angular_error(current["heading_deg"], tangent) <= 10.0
            checked += 1
    assert checked > 0
    return checked


def _assert_canvas_painted(page: Page) -> None:
    painted = page.locator("#replay-canvas canvas").evaluate(
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
    assert painted is True


def _assert_visual_realism(page: Page, playback: dict[str, Any]) -> None:
    surface = page.locator("#replay-canvas")
    vehicle_count = sum(
        participant["role"] != "pedestrian"
        for participant in playback["participants"]
    )
    expect(surface).to_have_attribute(
        "data-vehicle-model-asset",
        "scenarioforge.original-sedan",
    )
    expect(surface).to_have_attribute("data-vehicle-model-version", "1.0.0")
    assert int(surface.get_attribute("data-vehicle-model-count") or "-1") == vehicle_count
    assert set(
        (surface.get_attribute("data-vehicle-model-features") or "").split(",")
    ) == {
        "front",
        "rear",
        "body",
        "windows",
        "wheels",
        "headlights",
        "brake_lights",
    }
    assert float(surface.get_attribute("data-model-scale-error-max") or "nan") <= 0.02
    assert {
        "road-surface",
        "curbs",
        "lane-lines",
        "stop-lines",
        "traffic-signals",
        "intersection",
        "conflict-zones",
    } <= set((surface.get_attribute("data-road-elements") or "").split(","))
    assert int(surface.get_attribute("data-curb-segment-count") or "0") > 0
    if playback["road"]["geometry"]["conflict_zones"]:
        assert int(surface.get_attribute("data-stop-line-count") or "0") > 0
    signal_ids = {
        signal["signal_id"]
        for sample in playback["trajectory"]
        for signal in sample.get("signals", [])
    }
    assert int(surface.get_attribute("data-traffic-signal-count") or "0") == len(signal_ids)


def _seek_follow_pose(page: Page, tick: int) -> dict[str, Any]:
    page.locator("#replay-timeline").evaluate(
        """
        (element, tick) => {
          element.value = String(tick);
          element.dispatchEvent(new Event("input", {bubbles: true}));
        }
        """,
        tick,
    )
    pose = json.loads(
        page.locator("#replay-canvas").get_attribute("data-follow-pose") or "{}"
    )
    assert pose["source_tick"] == tick
    assert all(
        math.isfinite(float(value))
        for key in ("position_m", "camera_position", "look_at")
        for value in pose[key]
    )
    return pose


def _exercise_real_camera_modes(page: Page) -> None:
    camera = page.locator("#camera-mode")
    assert camera.locator("option").evaluate_all(
        "options => options.map(option => option.value)"
    ) == ["ego-follow", "overview", "fixed", "free"]
    for mode in ("overview", "fixed", "free"):
        camera.select_option(mode)
        expect(page.locator("#replay-canvas")).to_have_attribute(
            "data-camera-mode",
            mode,
        )
        _assert_canvas_painted(page)
    surface = page.locator("#replay-canvas")
    box = surface.bounding_box()
    assert box is not None
    page.mouse.move(box["x"] + 80, box["y"] + 80)
    page.mouse.down()
    page.mouse.move(box["x"] + 140, box["y"] + 110, steps=4)
    page.mouse.up()
    surface.press("w")
    page.mouse.wheel(0, -120)
    _assert_canvas_painted(page)
    camera.select_option("ego-follow")
    expect(surface).to_have_attribute("data-camera-mode", "ego-follow")


def _inject_rejected_secret_request(page: Page, canaries: dict[str, str]) -> None:
    session = _request(page, "/api/session")["body"]
    response = page.context.request.post(
        f"{page.url.rstrip('/')}/api/p1/runs",
        headers={
            "Idempotency-Key": "redaction-counterfactual",
            "Origin": page.url.rstrip("/"),
            "X-CSRF-Token": session["csrf_token"],
        },
        data={
            "scenario_id": "highway_merge",
            "rejected_field": canaries["rejected_field"],
        },
    )
    assert response.status == 400
    assert response.json() == {"detail": "request JSON fields are invalid"}


def test_five_real_p1_web_runs_emit_candidate_bound_media(
    browser: Browser,
    service_factory,
    tmp_path: Path,
) -> None:
    evidence = _evidence_root(tmp_path)
    source_candidate = _source_candidate_commit()
    canaries = _canaries()
    controlled_file = tmp_path / "controlled-secret.txt"
    controlled_file.write_text(canaries["controlled_file"], encoding="utf-8")
    assert controlled_file.read_text(encoding="utf-8") == canaries["controlled_file"]
    service = service_factory(timeout_seconds=120)
    scenarios: list[dict[str, Any]] = []
    console_errors: list[str] = []
    page_errors: list[str] = []
    heading_assertions = 0

    for scenario_id in P1_SCENARIOS:
        raw_videos = tmp_path / f"raw-video-{scenario_id}"
        raw_videos.mkdir()
        context = browser.new_context(
            viewport={"width": 1440, "height": 1000},
            record_video_dir=str(raw_videos),
            record_video_size={"width": 1440, "height": 1000},
            extra_http_headers={
                "Authorization": f"Bearer {canaries['authorization']}",
                "X-ScenarioForge-Test-Token": canaries["request_token"],
            },
        )
        context.add_cookies(
            [
                {
                    "name": "scenarioforge_gate_cookie",
                    "value": canaries["cookie"],
                    "url": service.base_url,
                }
            ]
        )
        context.tracing.start(screenshots=True, snapshots=True, sources=False)
        page = context.new_page()
        assert page.video is not None
        scenario_console_errors: list[str] = []
        scenario_page_errors: list[str] = []
        page.on(
            "console",
            lambda message, errors=scenario_console_errors: (
                errors.append(message.text) if message.type == "error" else None
            ),
        )
        page.on(
            "pageerror",
            lambda error, errors=scenario_page_errors: errors.append(str(error)),
        )
        page.goto(service.base_url)
        expect(page.locator("#app-status")).to_have_text("Ready")
        _inject_rejected_secret_request(page, canaries)

        catalog = _request(page, "/api/p1/scenarios")
        assert catalog["status"] == 200
        assert tuple(item["scenario_id"] for item in catalog["body"]["scenarios"]) == (
            P1_SCENARIOS
        )
        page.locator("#p1-scenario-select").select_option(scenario_id)
        expect(page.locator("#p1-scenario-name")).not_to_be_empty()
        expect(page.locator("#p1-scenario-description")).not_to_be_empty()
        with page.expect_response(
            lambda response: (
                response.request.method == "POST"
                and response.url.endswith("/api/p1/runs")
            ),
            timeout=120_000,
        ) as response_info:
            page.locator("#run-p1-scenario").click()
        reference = response_info.value.json()
        assert reference["scenario_id"] == scenario_id
        assert reference["backend"] == {
            "id": "scenarioforge.smarts",
            "version": "2.0.1",
        }
        run_id = reference["run_id"]
        expect(page.locator("#run-id")).to_have_text(run_id, timeout=120_000)
        expect(page.locator("#terminal-status")).to_have_text("completed")

        terminal_response = _request(page, f"/api/p1/runs/{run_id}")
        playback_response = _request(
            page,
            f"/api/p1/runs/{run_id}/artifacts/trajectory",
        )
        assert terminal_response["status"] == playback_response["status"] == 200
        terminal = terminal_response["body"]
        playback = playback_response["body"]
        assert terminal["schema_version"] == "scenarioforge.p1-terminal-evidence/v1"
        assert terminal["immutable"] is terminal["playable"] is True
        assert terminal["backend"] == {
            "id": "scenarioforge.smarts",
            "version": "2.0.1",
            "engine_class": "SMARTS",
        }
        assert playback["schema_version"] == "scenarioforge.p1-playback/v1"
        assert playback["scenario_id"] == terminal["scenario_id"] == scenario_id
        assert playback["run_id"] == terminal["run_id"] == run_id
        assert playback["attempt_id"] == terminal["attempt_id"]
        assert terminal["logical_ref"] == reference["published_ref"]
        assert playback["logical_ref"].startswith(f"{terminal['logical_ref']}/")
        assert playback["trajectory_digest"] == terminal["digests"]["trajectory"]
        assert playback["traffic_rule"] == "right-hand-traffic"
        assert playback["road"]["geometry"]["source"] == (
            "scenarioforge.smarts/2.0.1:road-map"
        )
        assert playback["road"]["geometry"]["lanes"]
        assert playback["camera"] == {
            "default_mode": "ego-follow",
            "available_modes": ["ego-follow", "overview", "fixed", "free"],
            "target_participant_id": "ego",
            "pose_source": "recorded-trajectory",
        }
        participant_ids = {item["id"] for item in playback["participants"]}
        recorded_participant_ids = {
            item["participant_id"] for item in playback["trajectory"]
        }
        assert recorded_participant_ids == participant_ids, (
            f"{scenario_id} has participants without recorded trajectory samples: "
            f"{sorted(participant_ids - recorded_participant_ids)}"
        )
        projection_error = page.evaluate(
            """
            async (playback) => {
              const {projectReplayScene} = await import("/static/replay_scene.js");
              const projected = {
                ...playback,
                schema_version: "scenarioforge.playback/v2",
                participants: playback.participants.map((participant) => ({
                  ...participant,
                  role: participant.role === "ego" ? "ego" : "social",
                })),
              };
              try {
                projectReplayScene(projected);
                return null;
              } catch (error) {
                return String(error instanceof Error ? error.message : error);
              }
            }
            """,
            playback,
        )
        assert projection_error is None, (
            f"{scenario_id} replay projection rejected real evidence: {projection_error}"
        )
        heading_assertions += _assert_recorded_headings(playback)

        expect(page.locator("#playback-panel")).to_be_visible()
        replay_surface = page.locator("#replay-canvas")
        try:
            expect(replay_surface.locator("canvas")).to_have_count(1)
        except AssertionError as error:
            raise AssertionError(
                f"{scenario_id} replay rendering failed: "
                f"render_state={replay_surface.get_attribute('data-render-state')!r}, "
                f"failure_reason={replay_surface.get_attribute('data-failure-reason')!r}"
            ) from error
        expect(replay_surface).to_have_attribute(
            "data-evidence-backend",
            "scenarioforge.smarts",
        )
        expect(replay_surface).to_have_attribute(
            "data-traffic-rule",
            "right-hand-traffic",
        )
        visible_ids = page.locator("#participant-legend li").evaluate_all(
            "items => items.map(item => item.dataset.participantId)"
        )
        assert visible_ids == [item["id"] for item in playback["participants"]]
        assert all(
            "m/s" in value
            for value in page.locator("#participant-legend li").all_inner_texts()
        )
        _assert_canvas_painted(page)
        _assert_visual_realism(page, playback)
        follow_5 = _seek_follow_pose(page, 5)
        follow_10 = _seek_follow_pose(page, 10)
        assert follow_5["position_m"] != follow_10["position_m"]
        assert follow_5["camera_position"] != follow_10["camera_position"]
        assert follow_5["look_at"] != follow_10["look_at"]
        assert (
            float(
                page.locator("#replay-canvas").get_attribute("data-follow-error-m")
                or "nan"
            )
            <= 2.0
        )
        assert (
            float(
                page.locator("#replay-canvas").get_attribute(
                    "data-look-direction-error-deg"
                )
                or "nan"
            )
            <= 5.0
        )
        expect(replay_surface).to_have_attribute("data-camera-within-tolerance", "true")
        _exercise_real_camera_modes(page)

        page.locator("#replay-restart").click()
        page.locator("#replay-speed").select_option("2")
        page.locator("#replay-toggle").click()
        expect(page.locator("#replay-toggle")).to_have_text("Pause replay")
        page.wait_for_timeout(900)
        page.locator("#replay-toggle").click()
        expect(page.locator("#replay-toggle")).to_have_text("Play replay")
        animated_pose = json.loads(
            page.locator("#replay-canvas").get_attribute("data-follow-pose") or "{}"
        )
        assert animated_pose["source_tick"] > 0
        _assert_canvas_painted(page)

        page.locator("#next-event").click()
        page.locator(".viewport-shell").scroll_into_view_if_needed()
        _assert_canvas_painted(page)

        screenshot = evidence / "screenshots" / f"{scenario_id}.png"
        trace = evidence / "traces" / f"{scenario_id}.zip"
        video = evidence / "videos" / f"{scenario_id}.webm"
        page.locator(".viewport-shell").screenshot(path=str(screenshot))
        context.tracing.stop(path=str(trace))
        video_handle = page.video
        assert video_handle is not None
        page.close()
        raw_video = Path(video_handle.path())
        context.close()
        shutil.move(str(raw_video), video)
        _sanitize_trace_archive(
            trace,
            sensitive_values=(
                *canaries.values(),
                str(ROOT),
                str(tmp_path),
                str(service.workspace),
                str(evidence),
                "/workspace",
                "/tmp/scenarioforge-pw",
            ),
        )
        assert screenshot.stat().st_size > 10_000
        assert trace.stat().st_size > 1_000
        assert video.stat().st_size > 1_000
        assert scenario_console_errors == []
        assert scenario_page_errors == []
        console_errors.extend(
            f"{scenario_id}: {message}" for message in scenario_console_errors
        )
        page_errors.extend(
            f"{scenario_id}: {message}" for message in scenario_page_errors
        )

        scenarios.append(
            {
                "scenario_id": scenario_id,
                "run_id": run_id,
                "attempt_id": terminal["attempt_id"],
                "execution_snapshot_id": terminal["logical_ref"],
                "execution_snapshot_digest": terminal["digests"]["run_manifest"],
                "backend": reference["backend"],
                "terminal_status": terminal["execution_status"],
                "camera": playback["camera"],
                "follow_pose_samples": [follow_5, follow_10],
                "media": {
                    "screenshot": _media_item(screenshot, evidence),
                    "trace": _media_item(trace, evidence),
                    "video": _media_item(video, evidence),
                },
            }
        )

    assert heading_assertions > 0
    assert (
        len(
            {
                item["media"][kind]["sha256"]
                for item in scenarios
                for kind in ("screenshot", "trace", "video")
            }
        )
        == 15
    )
    assert console_errors == []
    assert page_errors == []
    report = {
        "schema_version": "scenarioforge.p1-candidate-media/v3",
        "acceptance_coverage": list(ACCEPTANCE_COVERAGE),
        "source_candidate_bound": True,
        "source_candidate_commit": source_candidate,
        "evidence_package": _media_package(scenarios),
        "browser": {"name": "chromium", "version": browser.version},
        "service_url": service.base_url,
        "scenarios": scenarios,
        "assertion_summary": {
            "status": "passed",
            "scenario_count": len(scenarios),
            "media_count": 15,
            "heading_tangent_assertion_count": heading_assertions,
        },
        "console_errors": console_errors,
        "page_errors": page_errors,
    }
    (evidence / "p1-release-browser-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
