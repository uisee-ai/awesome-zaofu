from __future__ import annotations

import json
from pathlib import Path

import pytest

from scenarioforge.authoring.providers import (
    OfflineReferenceProvider,
    ProviderIntentError,
    ProviderRegistry,
)
from scenarioforge.authoring.scenario_spec import ScenarioSpecEditor, ValueSource
from scenarioforge.authoring.validation import validate_authoring_spec
from scenarioforge.core.canonical import thaw_json


ROOT = Path(__file__).resolve().parents[3]
CASES = json.loads(
    (ROOT / "tests/fixtures/p1/provider/offline_intents.json").read_text(encoding="utf-8")
)


@pytest.mark.parametrize("case", CASES, ids=[item["intent_id"] for item in CASES])
def test_offline_provider_covers_supported_benchmark_intents_without_credentials(
    case: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    draft = OfflineReferenceProvider().create_draft(case["prompt"])

    assert draft.provider_id == "scenarioforge.offline-reference"
    assert draft.intent_id == case["intent_id"]
    assert draft.normalized_spec.content["road"]["topology_kind"] == case["topology_kind"]
    assert draft.status == "needs_correction"
    assert "$.constraints.duration_s" in draft.normalized_spec.missing_fields
    sources = {annotation.source for annotation in draft.normalized_spec.annotations}
    assert {
        ValueSource.EXPLICIT,
        ValueSource.INFERRED,
        ValueSource.DEFAULT,
        ValueSource.MISSING,
    } <= sources
    corrected = ScenarioSpecEditor.apply_form_patch(
        draft.normalized_spec,
        {"$.constraints.duration_s": 30.0},
    )
    assert corrected.ready_for_confirmation is True
    assert validate_authoring_spec(thaw_json(corrected.content)).valid is True


def test_unknown_intent_fails_closed() -> None:
    with pytest.raises(ProviderIntentError, match="supported benchmark intent"):
        OfflineReferenceProvider().create_draft("make something surprising")


def test_provider_interface_is_registry_selected_and_unknown_ids_fail_closed() -> None:
    registry = ProviderRegistry((OfflineReferenceProvider(),))

    assert registry.provider_ids == ("scenarioforge.offline-reference",)
    assert registry.create_draft(
        "scenarioforge.offline-reference", "Create a highway merge"
    ).intent_id == "highway_merge"
    with pytest.raises(ProviderIntentError, match="not registered"):
        registry.create_draft("python.module:Provider", "Create a highway merge")
