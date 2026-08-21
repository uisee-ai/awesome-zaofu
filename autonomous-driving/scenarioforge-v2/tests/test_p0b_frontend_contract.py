from __future__ import annotations

import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "scenarioforge" / "web" / "static"


class ContractHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.elements: list[tuple[str, dict[str, str | None]]] = []
        self.inline_event_attributes: list[str] = []
        self.script_text: list[str] = []
        self._inside_script = False

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        attributes = dict(attrs)
        self.elements.append((tag, attributes))
        self.inline_event_attributes.extend(
            name for name in attributes if name.lower().startswith("on")
        )
        if tag == "script":
            self._inside_script = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._inside_script = False

    def handle_data(self, data: str) -> None:
        if self._inside_script and data.strip():
            self.script_text.append(data)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _relative_files() -> list[str]:
    return sorted(
        path.relative_to(STATIC).as_posix()
        for path in STATIC.rglob("*")
        if path.is_file()
    )


def test_static_bundle_inventory_and_pinned_threejs_are_exact() -> None:
    assert _relative_files() == [
        "app.js",
        "index.html",
        "p1_authoring.js",
        "p1_replay.js",
        "styles.css",
        "vendor/LICENSE.threejs.txt",
        "vendor/manifest.json",
        "vendor/three.core.min.js",
        "vendor/three.module.min.js",
    ]

    manifest = json.loads((STATIC / "vendor" / "manifest.json").read_text("utf-8"))
    assert manifest == {
        "schema_version": "scenarioforge.frontend-assets/v1",
        "threejs": {
            "package": "three",
            "version": "0.185.1",
            "revision": "185",
            "source_tag": "three.js@r185",
            "license": "MIT",
            "module": "vendor/three.module.min.js",
            "dependencies": ["vendor/three.core.min.js"],
            "files": [
                {
                    "path": "vendor/three.module.min.js",
                    "size_bytes": 365552,
                    "sha256": "86bcee248b64f44bcfc23c331ae74619061957d59cab040171dcb6fb5900beb6",
                },
                {
                    "path": "vendor/three.core.min.js",
                    "size_bytes": 385386,
                    "sha256": "05b2609338c76cd65daf74f3ac515bc9a5045e1b3b33edc07d8c9bd55250fa90",
                },
                {
                    "path": "vendor/LICENSE.threejs.txt",
                    "size_bytes": 1081,
                    "sha256": "8b378ebe60e2fe500158cb0ac71cb5e8b7d92953c2abcc63a0eb90499653b5bc",
                },
            ],
        },
    }
    for item in manifest["threejs"]["files"]:
        path = STATIC / item["path"]
        assert path.stat().st_size == item["size_bytes"]
        assert _sha256(path) == item["sha256"]

    module = (STATIC / "vendor" / "three.module.min.js").read_text("utf-8")
    license_text = (STATIC / "vendor" / "LICENSE.threejs.txt").read_text("utf-8")
    assert module.startswith("/**\n * @license\n")
    assert 'from"./three.core.min.js"' in module
    assert license_text.startswith("The MIT License\n\nCopyright © 2010-2026 three.js authors")


def test_html_is_an_exact_local_non_inline_application_shell() -> None:
    html = (STATIC / "index.html").read_text("utf-8")
    parser = ContractHTMLParser()
    parser.feed(html)

    ids = {
        attributes["id"]: tag
        for tag, attributes in parser.elements
        if attributes.get("id") is not None
    }
    assert ids == {
        "app-status": "p",
        "studio-natural-panel": "section",
        "p1-intent": "textarea",
        "p1-generate-draft": "button",
        "p1-provider-status": "p",
        "studio-json-panel": "section",
        "studio-template-panel": "section",
        "studio-template-select": "select",
        "studio-template-backend": "span",
        "studio-template-name": "h3",
        "studio-template-description": "p",
        "studio-template-participants": "ul",
        "studio-document-panel": "section",
        "p1-form-title": "input",
        "p1-form-seed": "input",
        "p1-form-duration": "input",
        "p1-backend": "select",
        "p1-apply-form": "button",
        "p1-preflight": "button",
        "p1-confirm-run": "button",
        "p1-source-annotations": "ol",
        "studio-run-title": "strong",
        "studio-run-summary": "p",
        "studio-run": "button",
        "internal-catalogs": "div",
        "p1-canonical-panel": "section",
        "p1-scenario-name": "h2",
        "p1-scenario-description": "p",
        "p1-scenario-select": "select",
        "run-p1-scenario": "button",
        "catalog-panel": "section",
        "scenario-name": "h2",
        "scenario-description": "p",
        "run-scenario": "button",
        "live-panel": "section",
        "live-state": "strong",
        "live-run-id": "span",
        "terminal-panel": "section",
        "scenario-id": "dd",
        "run-id": "dd",
        "terminal-status": "dd",
        "terminal-reason": "dd",
        "failure-stage": "dd",
        "seed": "dd",
        "policy-id": "dd",
        "manifest-digest": "dd",
        "artifact-index-digest": "dd",
        "evidence-ref": "dd",
        "collision": "dd",
        "collision-participants": "dd",
        "min-ttc": "dd",
        "completion-time": "dd",
        "terminal-tick": "dd",
        "evidence-list": "ul",
        "terminal-events": "ol",
        "non-playable": "p",
        "playback-panel": "section",
            "replay-canvas": "div",
            "participant-legend": "ul",
            "road-legend": "div",
            "replay-outcome": "strong",
            "active-events": "span",
            "replay-toggle": "button",
        "replay-timeline": "input",
        "replay-speed": "select",
        "current-tick": "output",
        "event-positions": "ol",
    }
    scripts = [attributes for tag, attributes in parser.elements if tag == "script"]
    stylesheets = [
        attributes
        for tag, attributes in parser.elements
        if tag == "link" and attributes.get("rel") == "stylesheet"
    ]
    assert scripts == [
        {"type": "module", "src": "/static/app.js"},
        {"type": "module", "src": "/static/p1_authoring.js"},
    ]
    assert stylesheets == [{"rel": "stylesheet", "href": "/static/styles.css"}]
    assert parser.script_text == []
    assert parser.inline_event_attributes == []
    assert "<style" not in html.lower()
    assert "http://" not in html.lower()
    assert "https://" not in html.lower()

    buttons = {
        attributes["id"]: attributes
        for tag, attributes in parser.elements
        if tag == "button" and attributes.get("id") is not None
    }
    assert buttons == {
        "p1-generate-draft": {
            "id": "p1-generate-draft",
            "type": "button",
            "class": "secondary-action",
        },
        "p1-apply-form": {
            "id": "p1-apply-form",
            "type": "button",
            "class": "secondary-action",
        },
        "studio-run": {"id": "studio-run", "type": "button", "disabled": None},
        "p1-preflight": {"id": "p1-preflight", "type": "button"},
        "p1-confirm-run": {
            "id": "p1-confirm-run",
            "type": "button",
            "disabled": None,
        },
        "run-p1-scenario": {
            "id": "run-p1-scenario",
            "type": "button",
            "disabled": None,
        },
        "run-scenario": {"id": "run-scenario", "type": "button", "disabled": None},
        "replay-toggle": {
            "id": "replay-toggle",
            "type": "button",
            "data-scope": "immutable-replay",
            "disabled": None,
        },
    }
    timeline = next(
        attributes
        for tag, attributes in parser.elements
        if tag == "input" and attributes.get("id") == "replay-timeline"
    )
    assert timeline == {
        "id": "replay-timeline",
        "type": "range",
        "min": "0",
        "max": "0",
        "step": "1",
        "value": "0",
        "disabled": None,
        "aria-label": "Replay timeline",
    }


def test_live_surface_has_no_client_run_control_and_replay_pause_is_scoped() -> None:
    html = (STATIC / "index.html").read_text("utf-8")
    app = (STATIC / "app.js").read_text("utf-8")
    live_panel = html.split('id="live-panel"', 1)[1].split("</section>", 1)[0].lower()

    assert "stop" not in live_panel
    assert "pause" not in live_panel
    assert "step" not in live_panel
    assert "reset" not in live_panel
    assert "cancel" not in live_panel
    assert "data-live-control" not in html
    assert 'data-scope="immutable-replay"' in html
    assert 'replayToggle.textContent = state.playing ? "Pause replay" : "Play replay"' in app
    assert 'terminal.status !== "success" || terminal.playable !== true' in app
    assert "return;" in app.split('terminal.status !== "success" || terminal.playable !== true', 1)[1]


def test_application_consumes_only_local_assets_and_same_origin_api() -> None:
    app = (STATIC / "app.js").read_text("utf-8")

    assert app.startswith('import * as THREE from "./vendor/three.module.min.js";\n')
    assert 'catalog: "/api/scenarios"' in app
    assert 'session: "/api/session"' in app
    assert 'runs: "/api/runs"' in app
    assert 'return `/api/runs/${encodeURIComponent(runId)}`;' in app
    assert 'return `${runStatus(runId)}/artifacts/trajectory`;' in app
    assert 'credentials: "same-origin"' in app
    assert '"X-CSRF-Token": session.csrfToken' in app
    assert '"Idempotency-Key": idempotencyKey' in app
    assert "crypto.randomUUID()" in app
    assert 'sessionStorage.setItem(ACTIVE_RUN_KEY, reference.run_id)' in app
    assert "sessionStorage.getItem(ACTIVE_RUN_KEY)" in app

    lowered = app.lower()
    for forbidden in (
        "http://",
        "https://",
        "innerhtml",
        "insertadjacenthtml",
        "document.write",
        "eval(",
        "new function",
        "/stop",
        "/pause",
        "/step",
        "/reset",
        "/cancel",
    ):
        assert forbidden not in lowered


def test_success_player_covers_road_participants_seek_speed_tick_and_events() -> None:
    app = (STATIC / "app.js").read_text("utf-8")

    expected_three_symbols = (
        "THREE.Scene",
        "THREE.PerspectiveCamera",
        "THREE.WebGLRenderer",
        "THREE.PlaneGeometry",
        "THREE.BoxGeometry",
        "THREE.Mesh",
    )
    assert all(symbol in app for symbol in expected_three_symbols)
    assert "function renderRoad(" in app
    assert "function renderParticipants(" in app
    assert "vehicle.userData.participantId = participant.id" in app
    assert "function renderKeyEvents(" in app
    assert "function setReplayTick(" in app
    assert "function animateReplay(" in app
    assert "requestAnimationFrame(animateReplay)" in app
    assert 'replayTimeline.addEventListener("input"' in app
    assert 'replaySpeed.addEventListener("change"' in app
    assert 'replayToggle.addEventListener("click"' in app
    assert 'marker.dataset.tick = String(event.trigger_tick)' in app
    assert "state.speed = Number.parseFloat(replaySpeed.value)" in app
    assert "currentTick.value = String(tick)" in app


def test_terminal_allow_list_and_failure_projection_are_complete() -> None:
    app = (STATIC / "app.js").read_text("utf-8")

    field_bindings = re.findall(
        r'\["([a-z-]+)",\s*\(terminal\)\s*=>',
        app,
    )
    assert field_bindings == [
        "scenario-id",
        "run-id",
        "terminal-status",
        "terminal-reason",
        "failure-stage",
        "seed",
        "policy-id",
        "manifest-digest",
        "artifact-index-digest",
        "evidence-ref",
        "collision",
        "collision-participants",
        "min-ttc",
        "completion-time",
        "terminal-tick",
    ]
    assert "terminal.evidence.forEach" in app
    assert "terminal.events.forEach" in app
    assert "nonPlayable.textContent = `Playback unavailable:" in app
    assert 'terminal.playback_reason ?? "terminal evidence is not a fully verified success"' in app
    assert "terminal.failure_stage ?? \"—\"" in app
    assert "terminal.metrics.collision_participants.join(\", \")" in app
    assert "terminal.metrics.min_ttc_s" in app
    assert "terminal.metrics.completion_time_s" in app
    assert "terminal.metrics.terminal_tick" in app
    assert "event.trigger_tick" in app
    assert "event.effect_state_tick" in app


def test_styles_are_local_responsive_and_do_not_fetch_resources() -> None:
    css = (STATIC / "styles.css").read_text("utf-8")

    assert "@media (max-width: 760px)" in css
    assert "#replay-canvas canvas" in css
    assert ".participant-swatch" in css
    assert ".event-marker" in css
    assert "@import" not in css
    assert "url(" not in css.lower()
    assert "http://" not in css.lower()
    assert "https://" not in css.lower()
