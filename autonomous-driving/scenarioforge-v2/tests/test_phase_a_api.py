from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from scenarioforge.authoring.library import LocalScenarioLibrary
from scenarioforge.authoring.preflight import preflight_revision
from scenarioforge.authoring.presets import BUILTIN_PRESET_IDS, PresetCatalog
from scenarioforge.authoring.save_and_run import SaveAndRunBlocked
from scenarioforge.runtime import RunSupervisor
from scenarioforge.web.api import RevisionAwareEvidenceReader, ScenarioForgeAPI
from scenarioforge.web.coordinator import ExecutionState, RunReference, UnknownRunError
from scenarioforge.web.evidence import EvidenceValidationError, PublishedEvidenceReader


ROOT = Path(__file__).resolve().parents[1]


class Coordinator:
    def start(self, scenario_id: str, *, idempotency_key: str) -> RunReference:
        raise AssertionError("authoring must not run a mutable catalog alias")

    def active_state(self, run_id: str) -> ExecutionState | None:
        raise UnknownRunError("unknown run_id")

    def reference(self, run_id: str) -> RunReference:
        raise UnknownRunError("unknown run_id")


class Evidence:
    def terminal(self, run_id: str, attempt_id: str) -> dict[str, object]:
        return {"run_id": run_id, "attempt_id": attempt_id, "terminal": True}

    def playback(self, run_id: str, attempt_id: str) -> dict[str, object]:
        return {"run_id": run_id, "attempt_id": attempt_id, "trajectory": []}


class RecordingRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, str, str, float]] = []

    def run(
        self,
        bundle: Any,
        *,
        run_id: str,
        attempt_id: str,
        timeout_seconds: float,
    ) -> dict[str, object]:
        self.calls.append((bundle, run_id, attempt_id, timeout_seconds))
        return {"run_id": run_id, "attempt_id": attempt_id}


def _api(tmp_path: Path, *, runner: RecordingRunner | None = None) -> ScenarioForgeAPI:
    return ScenarioForgeAPI(
        coordinator=Coordinator(),
        evidence=Evidence(),
        catalog_profile="p0c",
        library=LocalScenarioLibrary(
            tmp_path / "library",
            preset_catalog=PresetCatalog(ROOT / "examples" / "p0c"),
        ),
        authoring_runner=runner,
        authoring_timeout_seconds=17,
    )


def test_draft_field_validation_immutable_save_and_revision_history(
    tmp_path: Path,
) -> None:
    value: dict[str, Any] = json.loads(
        (ROOT / "tests/fixtures/authoring/valid_scenario.json").read_text(
            encoding="utf-8"
        )
    )
    api = _api(tmp_path)

    draft = api.create_authoring_draft(value)
    scenario_id = draft["scenario_id"]
    assert draft["generation"] == 0
    assert api.validate_authoring_draft(scenario_id)["valid"] is True

    invalid = copy.deepcopy(value)
    invalid["actors"][0]["spawn"]["lane_id"] = "missing-lane"
    edited = api.update_authoring_draft(
        scenario_id,
        invalid,
        expected_generation=draft["generation"],
    )
    validation = api.validate_authoring_draft(scenario_id)
    assert edited["generation"] == 1
    assert validation["valid"] is False
    assert any(
        diagnostic["path"].endswith("spawn.lane_id")
        for diagnostic in validation["diagnostics"]
    )

    restored = api.update_authoring_draft(
        scenario_id,
        value,
        expected_generation=edited["generation"],
    )
    revision = api.save_authoring_draft(
        scenario_id,
        expected_generation=restored["generation"],
    )
    assert revision["scenario_id"] == scenario_id
    assert revision["revision_id"] != "latest"
    assert revision["canonical_digest"]
    assert api.get_authoring_history(scenario_id) == {
        "schema_version": "scenarioforge.authoring-history/v1",
        "scenario_id": scenario_id,
        "revisions": [revision],
    }


def test_clone_archive_and_five_read_only_preset_forks(tmp_path: Path) -> None:
    api = _api(tmp_path)
    catalog = api.get_authoring_presets()
    assert tuple(item["template_id"] for item in catalog["templates"]) == BUILTIN_PRESET_IDS

    original = copy.deepcopy(catalog["templates"][0]["content"])
    edited = copy.deepcopy(original)
    edited["title"] = "Operator-owned fork"
    revision = api.fork_authoring_preset("brake_lead", edited)
    assert revision["content"]["title"] == "Operator-owned fork"
    assert revision["provenance"]["kind"] == "preset_fork"
    assert revision["provenance"]["template_id"] == "brake_lead"
    assert api.get_authoring_presets()["templates"][0]["content"] == original

    clone = api.clone_authoring_draft(revision["scenario_id"])
    assert clone["scenario_id"] != revision["scenario_id"]
    assert clone["content"] == revision["content"]
    tombstone = api.archive_authoring_scenario(clone["scenario_id"])
    assert tombstone["scenario_id"] == clone["scenario_id"]
    assert clone["scenario_id"] not in {
        item["scenario_id"] for item in api.list_authoring_scenarios()["scenarios"]
    }


@pytest.mark.parametrize("format", ("json", "yaml"))
def test_inline_import_export_round_trip(
    tmp_path: Path,
    format: str,
) -> None:
    api = _api(tmp_path)
    value = json.loads(
        (ROOT / "tests/fixtures/authoring/valid_scenario.json").read_text(
            encoding="utf-8"
        )
    )
    source = json.dumps(value)
    if format == "yaml":
        source = api.export_authoring_content(value, format="yaml")["content"]

    imported = api.import_authoring_draft(source, format=format)
    exported = api.export_authoring_draft(
        imported["draft"]["scenario_id"], format=format
    )
    round_trip = api.import_authoring_draft(exported["content"], format=format)
    assert imported["validation"]["valid"] is True
    assert round_trip["validation"]["valid"] is True
    assert exported["format"] == format


def test_preflight_and_run_use_only_an_explicit_immutable_revision(
    tmp_path: Path,
) -> None:
    runner = RecordingRunner()
    api = _api(tmp_path, runner=runner)
    value = json.loads(
        (ROOT / "examples/p0a/brake_lead.json").read_text(encoding="utf-8")
    )
    draft = api.create_authoring_draft(value)
    revision = api.save_authoring_draft(
        draft["scenario_id"], expected_generation=draft["generation"]
    )

    preflight = api.preflight_authoring_revision(revision["revision_id"])
    assert preflight["revision_id"] == revision["revision_id"]
    assert preflight["scenario_revision_digest"] == revision["canonical_digest"]
    assert preflight["status"] == "exact"
    assert preflight["executable"] is True

    started = api.run_authoring_revision(
        revision["revision_id"], idempotency_key="authoring-run-0001"
    )
    assert started["revision_id"] == revision["revision_id"]
    assert started["scenario_revision_digest"] == revision["canonical_digest"]
    assert runner.calls[0][0].scenario_instance.revision_id == revision["revision_id"]
    assert api.run_status(started["run_id"])["terminal"] is True
    assert api.run_artifact(started["run_id"], "trajectory")["run_id"] == started["run_id"]

    with pytest.raises(SaveAndRunBlocked, match="immutable revision_id"):
        api.run_authoring_revision("latest", idempotency_key="authoring-run-latest")


def test_import_failure_is_sanitized(tmp_path: Path) -> None:
    api = _api(tmp_path)
    payload = "!!python/object/apply:os.system ['echo PWNED >/tmp/phase-a-secret']"
    with pytest.raises(ValueError) as raised:
        api.import_authoring_draft(payload, format="yaml")
    assert "PWNED" not in str(raised.value)
    assert "/tmp" not in str(raised.value)


def test_revision_aware_v3_terminal_and_playback_are_strictly_consumed(
    tmp_path: Path,
) -> None:
    library = LocalScenarioLibrary(
        tmp_path / "library",
        preset_catalog=PresetCatalog(ROOT / "examples/p0c"),
    )
    revision = library.fork_preset("brake_lead")
    outcome = RunSupervisor(
        workspace=tmp_path / "runs",
        project_root=ROOT,
    ).run(
        preflight_revision(revision).bundle,
        run_id="run-v3-web-consumer",
        attempt_id="attempt-0001",
        timeout_seconds=120,
    )
    legacy = PublishedEvidenceReader(publish_root=tmp_path / "runs/published")
    with pytest.raises(EvidenceValidationError, match="RunResult fields are invalid"):
        legacy.terminal("run-v3-web-consumer", "attempt-0001")
    with pytest.raises(EvidenceValidationError, match="RunResult fields are invalid"):
        legacy.playback("run-v3-web-consumer", "attempt-0001")

    reader = RevisionAwareEvidenceReader(legacy)
    terminal = reader.terminal("run-v3-web-consumer", "attempt-0001")
    playback = reader.playback("run-v3-web-consumer", "attempt-0001")
    assert terminal["schema_version"] == "scenarioforge.terminal-evidence/v2"
    assert playback["schema_version"] == "scenarioforge.playback/v2"
    assert terminal["scenario_revision"] == playback["scenario_revision"]
    assert terminal["scenario_revision"]["revision_id"] == revision.revision_id
    assert terminal["scenario_revision"]["digest"] == revision.canonical_digest
    assert terminal["traceability_digest"] == playback["traceability_digest"]
    assert terminal["revision_traceability"]["code_commit"]
    assert outcome.published_path.is_dir()
