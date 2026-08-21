from __future__ import annotations

import json
from pathlib import Path

import pytest

from scenarioforge.authoring.actions import AuthoringActionError
from scenarioforge.authoring.library import LocalScenarioLibrary
from scenarioforge.web.api import ScenarioForgeAPI


ROOT = Path(__file__).resolve().parents[3]


def _exact_authoring_spec() -> dict[str, object]:
    value = json.loads(
        (ROOT / "tests/fixtures/authoring/valid_scenario.json").read_text(
            encoding="utf-8"
        )
    )
    value["road"]["topology_kind"] = "corridor"
    value["road"]["conflict_zones"] = []
    value["routes"] = value["routes"][:2]
    value["actors"] = value["actors"][:2]
    value["static_obstacles"] = []
    value["required_capabilities"] = [
        "actor.vehicle",
        "route.stable-id",
    ]
    return value


def test_api_normalizes_json_and_form_and_exposes_offline_draft(tmp_path: Path) -> None:
    api = ScenarioForgeAPI(
        coordinator=object(),
        evidence=object(),
        library=LocalScenarioLibrary(tmp_path / "library"),
    )
    value = _exact_authoring_spec()
    del value["description"]

    normalized = api.normalize_authoring_content(value)
    stored = api.create_authoring_draft(value)
    provider = api.create_authoring_intent_draft(
        "Create a highway merge with social vehicles",
        provider_id="scenarioforge.offline-reference",
    )

    assert normalized["content"]["description"] == ""
    assert stored["content"] == normalized["content"]
    assert provider["intent_id"] == "highway_merge"
    assert "$.constraints.duration_s" in provider["normalized_spec"]["missing_fields"]


def test_api_p1_preflight_confirmation_and_authorization_are_server_controlled(
    tmp_path: Path,
) -> None:
    library = LocalScenarioLibrary(tmp_path / "library")
    draft = library.create_draft(_exact_authoring_spec())
    revision = library.save_draft(draft.scenario_id)
    api = ScenarioForgeAPI(
        coordinator=object(),
        evidence=object(),
        library=library,
    )

    preflight = api.preflight_p1_authoring_revision(
        revision.revision_id,
        backend_id="scenarioforge.metadrive",
    )
    authorization = api.confirm_p1_authoring(preflight["preflight_id"])
    receipt = api.authorize_p1_authoring_run(
        preflight["preflight_id"], authorization
    )

    assert preflight["status"] == "exact"
    assert receipt == {
        "schema_version": "scenarioforge.authoring-action-receipt/v1",
        "action": "run",
        "authorized": True,
        "authorization_id": authorization["authorization_id"],
        "revision_id": revision.revision_id,
        "backend_id": "scenarioforge.metadrive",
    }


def test_uncorrected_provider_draft_can_be_saved_but_never_confirmed(
    tmp_path: Path,
) -> None:
    library = LocalScenarioLibrary(tmp_path / "library")
    api = ScenarioForgeAPI(coordinator=object(), evidence=object(), library=library)
    provider = api.create_authoring_intent_draft(
        "Create a highway merge",
        provider_id="scenarioforge.offline-reference",
    )
    draft = api.create_authoring_draft(provider["normalized_spec"]["content"])
    revision = api.save_authoring_draft(
        draft["scenario_id"], expected_generation=draft["generation"]
    )

    preflight = api.preflight_p1_authoring_revision(
        revision["revision_id"], backend_id="scenarioforge.metadrive"
    )

    assert preflight["status"] == "error"
    assert preflight["blocked"] is True
    with pytest.raises(AuthoringActionError, match="blocks confirmation"):
        api.confirm_p1_authoring(preflight["preflight_id"])


def test_schema_error_preflight_does_not_enter_compiler(tmp_path: Path) -> None:
    library = LocalScenarioLibrary(tmp_path / "library")
    value = _exact_authoring_spec()
    del value["actors"]
    draft = library.create_draft(value)
    revision = library.save_draft(draft.scenario_id)
    api = ScenarioForgeAPI(coordinator=object(), evidence=object(), library=library)

    preflight = api.preflight_p1_authoring_revision(
        revision.revision_id, backend_id="scenarioforge.metadrive"
    )

    assert preflight["status"] == "error"
    assert any(item["path"] == "$.actors" for item in preflight["diagnostics"])
