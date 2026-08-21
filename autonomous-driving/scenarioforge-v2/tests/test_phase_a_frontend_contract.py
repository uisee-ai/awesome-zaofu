from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src/scenarioforge/web/static"


class _IDs(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.authoring_ids: set[str] = set()

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.ids.add(str(values["id"]))
        if values.get("data-authoring-id"):
            self.authoring_ids.add(str(values["data-authoring-id"]))


def test_phase_a_authoring_controls_are_present_and_accessible() -> None:
    parser = _IDs()
    parser.feed((STATIC / "index.html").read_text(encoding="utf-8"))
    assert {
        "authoring-panel",
        "authoring-content",
        "create-draft",
        "update-draft",
        "validate-draft",
        "save-revision",
        "clone-draft",
        "archive-draft",
        "authoring-diagnostics",
        "revision-history",
        "authoring-preset",
        "fork-preset",
        "import-format",
        "import-draft",
        "export-format",
        "export-draft",
        "preflight-revision",
        "save-and-run-revision",
        "active-revision-id",
    }.issubset(parser.authoring_ids)
    assert parser.ids.isdisjoint(parser.authoring_ids)


def test_frontend_calls_only_explicit_authoring_resources_and_safe_dom_sinks() -> None:
    source = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "/api/authoring/drafts" in source
    assert "/api/authoring/presets" in source
    assert "/api/authoring/import" in source
    assert "/preflight" in source
    assert "encodeURIComponent(revisionId)" in source
    assert "expected_generation" in source
    assert "Idempotency-Key" in source
    assert 'document.querySelectorAll("[data-authoring-button]")' in source
    assert 'document.createElement("button")' in source
    assert "button.textContent = placeholder.textContent" in source
    assert 'document.querySelectorAll("[data-authoring-id]")' in source
    assert 'element.removeAttribute("data-authoring-id")' in source
    for forbidden in (
        "innerHTML",
        "outerHTML",
        "insertAdjacentHTML",
        "eval(",
        "new Function",
        'runAuthoringRevision("latest"',
    ):
        assert forbidden not in source


def test_phase_boundary_copy_does_not_claim_complete_p0_delivery() -> None:
    document = (STATIC / "index.html").read_text(encoding="utf-8")
    assert "Phase A authoring" in document
    assert "Phase B/C, CLI, Python SDK, and the complete P0 Release Gate remain unshipped" in document
    assert "complete P0 delivered" not in document
