from __future__ import annotations

import json
from pathlib import Path

from scenarioforge.authoring.scenario_spec import (
    ScenarioSpecEditor,
    ValueSource,
    normalize_scenario_spec,
)


ROOT = Path(__file__).resolve().parents[3]


def _valid_spec() -> dict[str, object]:
    return json.loads(
        (ROOT / "tests/fixtures/authoring/valid_scenario.json").read_text(
            encoding="utf-8"
        )
    )


def test_form_and_json_share_one_normalized_spec_without_dual_source() -> None:
    value = _valid_spec()
    del value["description"]
    del value["seed"]

    json_model = ScenarioSpecEditor.from_json(json.dumps(value))
    form_model = ScenarioSpecEditor.from_form(value)

    assert json_model.digest == form_model.digest
    assert json_model.content == form_model.content
    assert json_model.content["description"] == ""
    assert json_model.content["seed"] == 0
    sources = {item.path: item.source for item in json_model.annotations}
    assert sources["$.description"] is ValueSource.DEFAULT
    assert sources["$.seed"] is ValueSource.DEFAULT
    assert not json_model.missing_fields

    edited = ScenarioSpecEditor.apply_form_patch(
        json_model,
        {"$.seed": 41, "$.constraints.duration_s": 45.0},
    )
    reopened = ScenarioSpecEditor.from_json(edited.canonical_json)
    assert reopened.content == edited.content
    assert reopened.digest == edited.digest


def test_normalization_reports_missing_semantic_fields_without_inventing_values() -> None:
    value = _valid_spec()
    del value["actors"]

    model = normalize_scenario_spec(value)

    assert "$.actors" in model.missing_fields
    assert "actors" not in model.content
    assert model.ready_for_confirmation is False
    annotations = {(item.path, item.source) for item in model.annotations}
    assert ("$.actors", ValueSource.MISSING) in annotations


def test_normalization_reports_required_fields_inside_a_selected_union_shape() -> None:
    value = _valid_spec()
    del value["events"][0]["action"]["throttle_brake"]

    model = normalize_scenario_spec(value)

    assert "$.events[0].action.throttle_brake" in model.missing_fields
