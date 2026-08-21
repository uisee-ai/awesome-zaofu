from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

from playwright.sync_api import Browser, Page, expect


ROOT = Path(__file__).resolve().parents[3]


def _mount(page: Page) -> None:
    page.evaluate(
        """
        async () => {
          const module = await import('/static/experiment_controls.js');
          await module.mountExperimentControls({pollIntervalMs: 50});
        }
        """
    )


def _job(page: Page) -> dict[str, object]:
    return page.evaluate(
        """
        async () => {
          const id = document.querySelector('#experiment-id').textContent;
          const response = await fetch(`/api/experiments/${encodeURIComponent(id)}`);
          const experiment = await response.json();
          return experiment.jobs[0];
        }
        """
    )


def _wait_for_job(
    page: Page,
    predicate: Callable[[dict[str, object]], bool],
    *,
    timeout: float = 30.0,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    latest: dict[str, object] = {}
    while time.monotonic() < deadline:
        latest = _job(page)
        if predicate(latest):
            return latest
        time.sleep(0.05)
    raise AssertionError(f"Experiment job did not reach the expected state: {latest!r}")


def _restart_service(service: object, *, timeout_seconds: int = 120) -> None:
    service.stop()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        port = int(listener.getsockname()[1])
    log_path = service.workspace / "service-restarted.log"
    log_stream = log_path.open("wb")
    environment = dict(os.environ)
    inherited_python_path = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = str(ROOT / "src") + (
        os.pathsep + inherited_python_path if inherited_python_path else ""
    )
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "scenarioforge",
            "--project-root",
            str(ROOT),
            "--workspace",
            str(service.workspace),
            "web",
            "--port",
            str(port),
            "--timeout-seconds",
            str(timeout_seconds),
        ],
        cwd=ROOT,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=log_stream,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    service.process = process
    service.port = port
    service.log_path = log_path
    service._log_stream = log_stream
    service._stopped = False
    service._suspended_workers.clear()
    service.wait_until_ready()


def test_actual_browser_controls_persist_identity_and_cleanup(
    browser: Browser,
    service_factory,
) -> None:
    service = service_factory(timeout_seconds=120)
    context = browser.new_context()
    page = context.new_page()
    console_errors: list[str] = []
    page_errors: list[str] = []
    page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.goto(service.base_url)
    _mount(page)

    page.get_by_role("button", name="Create experiment").click()
    expect(page.locator("#experiment-state")).to_have_text("Queued")
    experiment_id = page.locator("#experiment-id").text_content()
    assert experiment_id and experiment_id.startswith("experiment-")

    page.get_by_role("button", name="Start experiment").click()
    _wait_for_job(
        page,
        lambda job: int(job["attempts"][0].get("process_group_id", 0)) > 0,
    )
    with page.expect_response(
        lambda response: response.request.method == "POST"
        and response.url.endswith("/commands")
    ) as pause_response:
        page.get_by_role("button", name="Pause experiment").click()
    response = pause_response.value
    assert response.status == 200, response.text()
    expect(page.locator("#experiment-state")).to_have_text("Paused")

    page.reload()
    _mount(page)
    expect(page.locator("#experiment-id")).to_have_text(experiment_id)
    expect(page.locator("#experiment-state")).to_have_text("Paused")
    before_recovery = _job(page)
    prior_attempt_id = before_recovery["attempt_id"]
    prior_process_group_id = before_recovery["attempts"][0]["process_group_id"]

    page.evaluate("clearInterval(globalThis.__scenarioforgeExperimentPoll)")
    page.wait_for_timeout(100)
    _restart_service(service)
    page.goto(service.base_url)
    _mount(page)
    expect(page.locator("#experiment-id")).to_have_text(experiment_id)
    recovered = _wait_for_job(
        page,
        lambda job: len(job["attempts"]) == 2
        and int(job["attempts"][1].get("process_group_id", 0)) > 0,
    )
    assert recovered["attempt_id"] != prior_attempt_id
    assert recovered["attempts"][0]["state"] == "failed"
    assert recovered["attempts"][0]["reason"] == "infrastructure_interrupted"
    assert recovered["attempts"][0]["cleanup"]["process_group_id"] == prior_process_group_id
    assert recovered["attempts"][0]["cleanup"]["complete"] is True
    assert recovered["attempts"][0]["cleanup"]["remaining_pids"] == []
    page.get_by_role("button", name="Pause experiment").click()
    expect(page.locator("#experiment-state")).to_have_text("Paused")

    page.get_by_role("button", name="Step experiment").click()
    expect(page.locator("#experiment-state")).to_have_text("Paused")
    page.get_by_role("button", name="Resume experiment").click()
    expect(page.locator("#experiment-state")).to_have_text("Running")
    page.get_by_role("button", name="Stop experiment").click()
    expect(page.locator("#experiment-state")).to_have_text("Cancelled")
    _wait_for_job(
        page,
        lambda job: bool(
            job["attempts"][-1].get("process_tree_cleanup", {}).get("complete")
        ),
    )
    cancelled = _job(page)
    assert cancelled["state"] == "cancelled"
    assert cancelled["attempts"][-1]["process_tree_cleanup"]["remaining_pids"] == []

    labels = page.evaluate(
        """
        async () => {
          const module = await import('/static/experiment_controls.js');
          return ['queued', 'running', 'completed', 'failed', 'timeout', 'cancelled']
            .map((state) => module.experimentStateLabel(state));
        }
        """
    )
    assert labels == ["Queued", "Running", "Completed", "Failed", "Timed out", "Cancelled"]
    assert console_errors == []
    assert page_errors == []

    configured_evidence_root = os.environ.get("SCENARIOFORGE_PHASE_B_EVIDENCE_DIR")
    evidence_root = (
        Path(configured_evidence_root)
        if configured_evidence_root is not None
        else service.workspace / "evidence" / "phase-b"
    )
    evidence_root.mkdir(parents=True, exist_ok=True)
    screenshot = evidence_root / "phase-b-controls.png"
    page.screenshot(path=str(screenshot), full_page=True)
    (evidence_root / "phase-b-controls.json").write_text(
        json.dumps(
            {
                "schema_version": "scenarioforge.phase-b-browser-evidence/v1",
                "experiment_id": experiment_id,
                "attempt_id": cancelled["attempt_id"],
                "prior_attempt_id": prior_attempt_id,
                "recovery_cleanup_complete": True,
                "states": labels,
                "cleanup_complete": True,
                "console_errors": console_errors,
                "page_errors": page_errors,
                "browser_version": browser.version,
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    context.close()
