from __future__ import annotations

import hashlib
import json
import os
import shutil
import zipfile
from pathlib import Path
from typing import Any

from playwright.sync_api import Browser, Page, expect


ROOT = Path(__file__).resolve().parents[3]


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


def _evidence_root(tmp_path: Path) -> tuple[Path, str | None]:
    configured = os.environ.get("SCENARIOFORGE_RELEASE_EVIDENCE_DIR")
    root = Path(configured) if configured else tmp_path / "release-browser-evidence"
    if not root.is_absolute():
        root = ROOT / root
    root.mkdir(parents=True, exist_ok=True)
    candidate = os.environ.get("SCENARIOFORGE_CANDIDATE_COMMIT")
    if candidate is not None:
        assert len(candidate) in {40, 64}
        assert all(character in "0123456789abcdef" for character in candidate)
    return root, candidate


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _payloads(path: Path) -> list[bytes]:
    if not zipfile.is_zipfile(path):
        return [path.read_bytes()]
    with zipfile.ZipFile(path) as archive:
        return [
            archive.read(name)
            for name in archive.namelist()
            if not name.endswith("/")
        ]


def _write_candidate_receipts(
    root: Path,
    *,
    candidate: str,
    chromium_version: str,
    run_id: str,
    attempt_id: str,
    media: list[tuple[str, Path]],
    secrets: list[str],
) -> None:
    records = [
        {
            "kind": kind,
            "path": path.relative_to(root).as_posix(),
            "sha256": _digest(path),
            "size_bytes": path.stat().st_size,
            "chromium_version": chromium_version,
            "candidate_commit": candidate,
            "run_id": run_id,
            "attempt_id": attempt_id,
        }
        for kind, path in media
    ]
    forbidden = [
        value.encode("utf-8")
        for value in [*secrets, str(ROOT)]
        if value
    ]
    findings = [
        {"media_kind": kind, "finding": "sensitive-canary-or-host-path"}
        for kind, path in media
        if any(
            pattern in payload
            for pattern in forbidden
            for payload in _payloads(path)
        )
    ]
    sanitization = {
        "schema_version": "scenarioforge.media-sanitization-receipt/v1",
        "status": "passed" if not findings else "failed",
        "candidate_commit": candidate,
        "run_id": run_id,
        "attempt_id": attempt_id,
        "scanned_media": [kind for kind, _path in media],
        "checks": ["session-token", "configured-canary", "repository-host-path"],
        "findings": findings,
    }
    assert sanitization["status"] == "passed", findings
    receipt = {
        "schema_version": "scenarioforge.release-gate-media-receipt/v1",
        "scope": "complete-p0-release-browser",
        "ordinary_run_artifact": False,
        "ordinary_run_quota_applies": False,
        "candidate_commit": candidate,
        "chromium_version": chromium_version,
        "run_id": run_id,
        "attempt_id": attempt_id,
        "media": records,
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


def _mount_experiment_controls(page: Page) -> None:
    page.evaluate(
        """
        async () => {
          const module = await import('/static/experiment_controls.js');
          await module.mountExperimentControls({pollIntervalMs: 50});
        }
        """
    )


def test_complete_p0_browser_closes_experiment_replay_and_sidecar_loop(
    browser: Browser,
    service_factory,
    tmp_path: Path,
) -> None:
    evidence, candidate = _evidence_root(tmp_path)
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
    page_errors: list[str] = []
    page.on(
        "console",
        lambda message: console_errors.append(message.text)
        if message.type == "error"
        else None,
    )
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.goto(service.base_url)
    expect(page.locator("#app-status")).to_have_text("Ready")
    session = _request(page, "/api/session")["body"]

    _mount_experiment_controls(page)
    page.get_by_role("button", name="Create experiment").click()
    expect(page.locator("#experiment-state")).to_have_text("Queued")
    experiment_id = page.locator("#experiment-id").inner_text()
    assert experiment_id.startswith("experiment-")
    page.reload()
    expect(page.locator("#app-status")).to_have_text("Ready")
    _mount_experiment_controls(page)
    expect(page.locator("#experiment-id")).to_have_text(experiment_id)
    expect(page.locator("#experiment-state")).to_have_text("Queued")

    page.get_by_role("button", name="Start experiment").click()
    expect(page.locator("#experiment-state")).to_have_text("Completed", timeout=120_000)
    experiment = _request(page, f"/api/experiments/{experiment_id}")["body"]
    assert experiment["state"] == "completed"
    assert experiment["cardinality"] == 1
    job = experiment["jobs"][0]
    assert job["state"] == "completed"
    assert job["logical_run_id"].startswith(f"run-{experiment_id}-")
    assert job["attempt_id"].startswith("attempt-")
    assert job["attempts"][-1]["state"] == "completed"
    assert job["attempts"][-1]["published_ref"].startswith("published/")

    page.locator("#scenario-select").select_option("brake_lead")
    with page.expect_response(
        lambda response: response.request.method == "POST"
        and response.url.endswith("/api/runs")
    ) as response_info:
        page.get_by_role("button", name="Run scenario").click()
    run_id = response_info.value.json()["run_id"]
    expect(page.locator("#run-id")).to_have_text(run_id, timeout=120_000)
    expect(page.locator("#terminal-status")).to_have_text("completed")
    terminal = _request(page, f"/api/runs/{run_id}")["body"]
    playback = _request(page, f"/api/runs/{run_id}/artifacts/trajectory")["body"]
    assert terminal["execution_status"] == "completed"
    assert terminal["playable"] is True
    assert playback["scenario_id"] == "brake_lead"
    assert playback["road"]["geometry"]["source"] == "metadrive-road-network"
    expect(page.locator("#playback-panel")).to_be_visible()
    expect(page.locator("#replay-canvas canvas")).to_have_count(1)
    expect(page.locator("#replay-canvas")).to_have_attribute(
        "data-camera-mode", "ego-follow"
    )
    page.locator("#event-positions .event-marker").filter(
        has_text="lead-hard-brake"
    ).click()
    expect(
        page.locator("#participant-legend [data-participant-id='lead']")
    ).to_have_attribute("data-brake-state", "on")
    expect(page.locator("#active-events")).to_contain_text("lead hard brake")
    expect(
        page.locator("#participant-legend [data-participant-id='lead']")
    ).to_contain_text("m/s")

    context.tracing.start(screenshots=True, snapshots=True, sources=False)
    page.locator("#replay-restart").click()
    page.locator("#replay-speed").select_option("2")
    page.locator("#replay-toggle").click()
    expect(page.locator("#replay-toggle")).to_have_text("Pause replay")
    page.wait_for_timeout(750)
    page.locator("#replay-toggle").click()
    expect(page.locator("#replay-toggle")).to_have_text("Play replay")

    screenshot = screenshots / "p0-release.png"
    trace = traces / "p0-release.zip"
    video = videos / "p0-release.webm"
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
    assert console_errors == []
    assert page_errors == []

    report = {
        "schema_version": "scenarioforge.complete-p0-browser-evidence/v1",
        "candidate_bound": candidate is not None,
        "browser_version": browser.version,
        "experiment_id": experiment_id,
        "experiment_job_id": job["job_id"],
        "experiment_attempt_id": job["attempt_id"],
        "run_id": run_id,
        "attempt_id": terminal["attempt_id"],
        "assertions": [
            "persistent_experiment_identity_across_refresh",
            "real_experiment_completion_and_publication",
            "real_metadrive_terminal_and_replay",
            "ego_follow_and_hard_brake_speed_readout",
            "screenshot_trace_video_sidecars",
            "zero_console_and_page_errors",
        ],
    }
    (evidence / "release-browser-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if candidate is not None:
        _write_candidate_receipts(
            evidence,
            candidate=candidate,
            chromium_version=browser.version,
            run_id=run_id,
            attempt_id=terminal["attempt_id"],
            media=[
                ("screenshot", screenshot),
                ("trace", trace),
                ("video", video),
            ],
            secrets=[
                session["csrf_token"],
                os.environ.get("SCENARIOFORGE_MEDIA_CANARY", ""),
            ],
        )
