from __future__ import annotations

import copy
import json
import os
from pathlib import Path

from playwright.sync_api import Browser, Page, expect


ROOT = Path(__file__).resolve().parents[3]


def _evidence_directory(tmp_path: Path) -> Path:
    configured = os.environ.get("SCENARIOFORGE_PHASE_A_EVIDENCE_DIR")
    directory = Path(configured) if configured else tmp_path / "phase-a-browser-evidence"
    if not directory.is_absolute():
        directory = ROOT / directory
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _write_editor(page: Page, value: dict[str, object]) -> None:
    page.locator("#authoring-content").fill(json.dumps(value, indent=2))


def _draft_id(page: Page) -> str:
    value = page.locator("#authoring-draft-id").inner_text()
    assert value != "—"
    return value


def test_phase_a_authoring_to_immutable_metadrive_replay_in_real_chromium(
    browser: Browser,
    service_factory,
    tmp_path: Path,
) -> None:
    service = service_factory(timeout_seconds=120)
    evidence = _evidence_directory(tmp_path)
    context = browser.new_context(viewport={"width": 1500, "height": 1200})
    page = context.new_page()
    browser_errors: list[str] = []
    page.on(
        "console",
        lambda message: browser_errors.append(
            f"console:{message.type}:{message.text}"
        )
        if message.type == "error"
        else None,
    )
    page.on("pageerror", lambda error: browser_errors.append(f"pageerror:{error}"))

    page.goto(service.base_url)
    expect(page.locator("#app-status")).to_have_text("Ready")
    expect(page.locator("#authoring-title")).to_have_text(
        "Author to an immutable revision"
    )
    page.screenshot(path=evidence / "01-authoring-initial.png", full_page=True)

    authoring_value = json.loads(
        (ROOT / "tests/fixtures/authoring/valid_scenario.json").read_text(
            encoding="utf-8"
        )
    )
    _write_editor(page, authoring_value)
    page.get_by_role("button", name="Create draft").click()
    expect(page.locator("#app-status")).to_have_text("Draft created")
    original_draft_id = _draft_id(page)

    invalid = copy.deepcopy(authoring_value)
    invalid["actors"][0]["spawn"]["lane_id"] = "missing-lane"
    _write_editor(page, invalid)
    page.get_by_role("button", name="Validate fields").click()
    expect(page.locator("#app-status")).to_have_text(
        "Field validation found issues"
    )
    expect(page.locator("#authoring-diagnostics")).to_contain_text(
        "spawn.lane_id"
    )
    page.screenshot(path=evidence / "02-field-diagnostic.png", full_page=True)

    _write_editor(page, authoring_value)
    page.get_by_role("button", name="Validate fields").click()
    expect(page.locator("#app-status")).to_have_text("Field validation passed")
    page.get_by_role("button", name="Save immutable revision").click()
    expect(page.locator("#app-status")).to_have_text("Immutable revision saved")
    first_revision_id = page.locator("#active-revision-id").inner_text()
    assert first_revision_id not in {"", "—", "latest"}
    expect(page.locator("#revision-history")).to_contain_text(first_revision_id)
    page.get_by_role("button", name="Preflight revision").click()
    expect(page.locator("#app-status")).to_have_text("Preflight unsupported")
    expect(page.locator("#preflight-status")).to_have_text("unsupported · blocked")

    page.locator("#export-format").select_option("json")
    page.get_by_role("button", name="Export inline").click()
    expect(page.locator("#app-status")).to_have_text("JSON exported inline")
    page.locator("#import-format").select_option("json")
    page.get_by_role("button", name="Import inline").click()
    expect(page.locator("#app-status")).to_have_text("JSON imported")
    json_import_id = _draft_id(page)
    assert json_import_id != original_draft_id

    page.locator("#export-format").select_option("yaml")
    page.get_by_role("button", name="Export inline").click()
    expect(page.locator("#app-status")).to_have_text("YAML exported inline")
    assert "schema_version:" in page.locator("#authoring-content").input_value()
    page.locator("#import-format").select_option("yaml")
    page.get_by_role("button", name="Import inline").click()
    expect(page.locator("#app-status")).to_have_text("YAML imported")

    page.locator("#authoring-preset").select_option("brake_lead")
    page.get_by_role("button", name="Fork preset").click()
    expect(page.locator("#app-status")).to_have_text("Read-only preset forked")
    fork_id = _draft_id(page)
    expect(page.locator("#revision-history")).to_contain_text("r1")
    page.get_by_role("button", name="Preflight revision").click()
    expect(page.locator("#app-status")).to_have_text("Preflight exact")
    expect(page.locator("#preflight-status")).to_have_text("exact · executable")
    page.get_by_role("button", name="Clone draft").click()
    expect(page.locator("#app-status")).to_have_text("Draft cloned")
    clone_id = _draft_id(page)
    assert clone_id != fork_id
    page.get_by_role("button", name="Archive draft").click()
    expect(page.locator("#app-status")).to_have_text("Draft archived")

    page.locator("#authoring-draft").select_option(fork_id)
    expect(page.locator("#authoring-draft-id")).to_have_text(fork_id)
    with page.expect_response(
        lambda response: response.request.method == "POST"
        and "/api/authoring/revisions/" in response.url
        and response.url.endswith("/runs"),
        timeout=120_000,
    ) as response_info:
        page.get_by_role("button", name="Save and run revision").click()
    run_response = response_info.value
    assert run_response.status == 201
    reference = run_response.json()
    assert reference["revision_id"] not in {"", "latest"}
    assert reference["scenario_revision_digest"]
    expect(page.locator("#terminal-status")).to_have_text(
        "completed", timeout=120_000
    )
    expect(page.locator("#playback-panel")).to_be_visible()
    expect(page.locator("#replay-canvas canvas")).to_have_count(1)
    page.screenshot(path=evidence / "03-immutable-replay.png", full_page=True)

    assert all(path.stat().st_size > 10_000 for path in sorted(evidence.glob("*.png")))
    assert browser_errors == []
    context.close()
