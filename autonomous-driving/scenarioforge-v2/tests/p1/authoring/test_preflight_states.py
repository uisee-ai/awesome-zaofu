from __future__ import annotations

import json
from pathlib import Path

import pytest

from scenarioforge.authoring.p1_preflight import PreflightStatus, evaluate_preflight
from scenarioforge.authoring.scenario_spec import normalize_scenario_spec


ROOT = Path(__file__).resolve().parents[3]


def _spec():
    value = json.loads(
        (ROOT / "tests/fixtures/authoring/valid_scenario.json").read_text(
            encoding="utf-8"
        )
    )
    return normalize_scenario_spec(value)


def _capability(status: str, diagnostics: list[dict[str, str]] | None = None):
    return {
        "schema_version": "scenarioforge.capability-report/v1",
        "backend_id": "scenarioforge.smarts",
        "status": status,
        "diagnostics": diagnostics or [],
    }


@pytest.mark.parametrize(
    ("status", "warnings", "expected", "blocked", "confirm"),
    [
        ("exact", [], PreflightStatus.EXACT, False, False),
        ("exact", [{"path": "$.seed", "reason": "seed is reused"}], PreflightStatus.WARNING, False, True),
        ("lossy", [], PreflightStatus.LOSSY, False, True),
        ("unsupported", [], PreflightStatus.UNSUPPORTED, True, False),
    ],
)
def test_preflight_has_explicit_five_state_gate(
    status: str,
    warnings: list[dict[str, str]],
    expected: PreflightStatus,
    blocked: bool,
    confirm: bool,
) -> None:
    diagnostics = []
    if status in {"lossy", "unsupported"}:
        diagnostics = [{
            "path": "$.actors[1].kind",
            "source_semantics": "controlled vehicle",
            "degraded_semantics": "social vehicle",
            "impact": "control ownership changes",
        }]
    report = evaluate_preflight(
        _spec(),
        backend_id="scenarioforge.smarts",
        capability_report=_capability(status, diagnostics),
        warnings=warnings,
    )

    assert report.status is expected
    assert report.blocked is blocked
    assert report.requires_confirmation is confirm
    if status == "lossy":
        assert report.disclosures[0].to_dict() == {
            "path": "$.actors[1].kind",
            "source_semantics": "controlled vehicle",
            "degraded_semantics": "social vehicle",
            "impact": "control ownership changes",
        }


def test_schema_error_is_distinct_and_blocks() -> None:
    value = _spec().to_dict()["content"]
    del value["actors"]

    report = evaluate_preflight(
        normalize_scenario_spec(value),
        backend_id="scenarioforge.smarts",
        capability_report=_capability("exact"),
    )

    assert report.status is PreflightStatus.ERROR
    assert report.blocked is True
    assert report.requires_confirmation is False
    assert any(item["path"] == "$.actors" for item in report.diagnostics)


def test_authoring_semantic_loss_is_disclosed_even_when_backend_reports_exact() -> None:
    value = _spec().to_dict()["content"]
    value["parameters"][0]["value_type"] = "integer"

    report = evaluate_preflight(
        normalize_scenario_spec(value),
        backend_id="scenarioforge.smarts",
        capability_report=_capability("exact"),
    )

    assert report.status is PreflightStatus.LOSSY
    assert report.requires_confirmation is True
    disclosure = report.disclosures[0]
    assert disclosure.path == "$.parameters[0].distribution"
    assert disclosure.source_semantics == "parameter.integer-distribution"
    assert disclosure.degraded_semantics
    assert disclosure.impact
