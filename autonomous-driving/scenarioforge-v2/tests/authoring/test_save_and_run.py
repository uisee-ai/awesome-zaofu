from __future__ import annotations

import json
from pathlib import Path

import pytest

from scenarioforge.authoring.library import LocalScenarioLibrary
from scenarioforge.authoring.presets import PresetCatalog
from scenarioforge.authoring.save_and_run import SaveAndRunBlocked, SaveAndRunService


ROOT = Path(__file__).resolve().parents[2]


class RecordingRunner:
    def __init__(self) -> None:
        self.calls = []

    def run(self, bundle, *, run_id: str, attempt_id: str, timeout_seconds: float):
        self.calls.append((bundle, run_id, attempt_id, timeout_seconds))
        return {"run_id": run_id, "attempt_id": attempt_id}


def test_dirty_save_and_run_uses_only_the_published_revision(tmp_path: Path) -> None:
    catalog = PresetCatalog(ROOT / "examples/p0c")
    library = LocalScenarioLibrary(tmp_path / "library", preset_catalog=catalog)
    draft = library.create_draft(catalog.editable_copy("brake_lead"))
    runner = RecordingRunner()
    service = SaveAndRunService(library=library, runner=runner)

    result = service.save_and_run(
        draft.scenario_id,
        expected_generation=draft.generation,
        run_id="run-1",
        attempt_id="attempt-1",
        timeout_seconds=120,
    )

    assert result.revision.revision_id == library.latest_revision(draft.scenario_id).revision_id
    bundle = runner.calls[0][0]
    frozen_digest = bundle.digest
    edited = catalog.editable_copy("brake_lead")
    edited["seed"] += 1
    library.update_draft(draft.scenario_id, edited, expected_generation=draft.generation)
    library.archive_scenario(draft.scenario_id)
    assert bundle.digest == frozen_digest
    assert bundle.scenario_instance.revision_id == result.revision.revision_id
    assert bundle.scenario_instance.revision_digest == result.revision.canonical_digest


def test_unsupported_revision_is_saved_but_never_started(tmp_path: Path) -> None:
    value = json.loads((ROOT / "examples/p0a/brake_lead.json").read_text(encoding="utf-8"))
    value["required_capabilities"].append("backend.unsupported")
    library = LocalScenarioLibrary(tmp_path / "library")
    draft = library.create_draft(value)
    runner = RecordingRunner()

    with pytest.raises(SaveAndRunBlocked, match="unsupported"):
        SaveAndRunService(library=library, runner=runner).save_and_run(
            draft.scenario_id,
            expected_generation=draft.generation,
            run_id="run-2",
            attempt_id="attempt-1",
            timeout_seconds=120,
        )

    assert len(library.history(draft.scenario_id)) == 1
    assert runner.calls == []


def test_run_revision_rejects_mutable_latest_alias(tmp_path: Path) -> None:
    catalog = PresetCatalog(ROOT / "examples/p0c")
    library = LocalScenarioLibrary(tmp_path / "library", preset_catalog=catalog)
    service = SaveAndRunService(library=library, runner=RecordingRunner())
    revision = library.fork_preset("brake_lead")

    service.run_revision(
        revision.revision_id, run_id="run-3", attempt_id="attempt-1", timeout_seconds=120
    )
    with pytest.raises(SaveAndRunBlocked, match="immutable revision_id"):
        service.run_revision(
            "latest", run_id="run-4", attempt_id="attempt-1", timeout_seconds=120
        )
