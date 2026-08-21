from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
STATIC = ROOT / "src/scenarioforge/web/static"


def test_p1_authoring_surface_loads_dedicated_module_and_shared_editor_controls() -> None:
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    module = (STATIC / "p1_authoring.js").read_text(encoding="utf-8")

    for identity in (
        "p1-intent",
        "p1-generate-draft",
        "p1-form-title",
        "p1-form-seed",
        "p1-form-duration",
        "p1-apply-form",
        "p1-source-annotations",
        "p1-confirm-run",
    ):
        assert f'id="{identity}"' in index
        assert f'"#{identity}"' in module
    assert '<script type="module" src="/static/p1_authoring.js"></script>' in index
    assert "/api/authoring/provider-drafts" in module
    assert "/api/authoring/normalize" in module
    assert "p1-preflights" in module
    assert "source_semantics" in module
    assert "degraded_semantics" in module
    assert "impact" in module
