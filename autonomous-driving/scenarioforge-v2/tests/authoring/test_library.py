from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from scenarioforge.authoring.library import (
    ArchivedScenarioError,
    DraftConflictError,
    ImmutableRevisionError,
    LocalScenarioLibrary,
)
from scenarioforge.authoring.storage import SQLiteLibraryStorage
from scenarioforge.core.canonical import canonical_bytes


ROOT = Path(__file__).resolve().parents[2]
VALID_SCENARIO = ROOT / "tests" / "fixtures" / "authoring" / "valid_scenario.json"
FIXED_TIME = "2026-08-14T10:00:00.000000Z"


@pytest.fixture
def valid_scenario() -> dict[str, Any]:
    value = json.loads(VALID_SCENARIO.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _deterministic_library(tmp_path: Path) -> LocalScenarioLibrary:
    counters = {"scenario": 0, "revision": 0, "tombstone": 0}

    def mint(kind: str) -> str:
        counters[kind] += 1
        return f"{kind}-{counters[kind]:04d}"

    return LocalScenarioLibrary(
        tmp_path,
        id_factory=mint,
        clock=lambda: FIXED_TIME,
    )


def test_save_mints_complete_immutable_revision_chain(
    tmp_path: Path,
    valid_scenario: dict[str, Any],
) -> None:
    library = _deterministic_library(tmp_path)
    caller_value = copy.deepcopy(valid_scenario)

    draft = library.create_draft(caller_value, actor="local_operator")
    caller_value["title"] = "caller mutation must not leak"
    first = library.save_draft(draft.scenario_id, actor="local_operator")

    assert draft.to_dict() == {
        "scenario_id": "scenario-0001",
        "generation": 0,
        "schema_version": "scenarioforge.authoring/v1",
        "content": valid_scenario,
        "provenance": {
            "kind": "user_draft",
            "actor": "local_operator",
            "created_at": FIXED_TIME,
        },
        "latest_revision_id": None,
        "archived": False,
    }
    assert first.to_dict() == {
        "scenario_id": "scenario-0001",
        "revision_id": "revision-0001",
        "parent_revision_id": None,
        "revision_number": 1,
        "schema_version": "scenarioforge.authoring/v1",
        "canonical_digest": hashlib.sha256(
            canonical_bytes(valid_scenario)
        ).hexdigest(),
        "content": valid_scenario,
        "provenance": {
            "kind": "user_draft",
            "actor": "local_operator",
            "created_at": FIXED_TIME,
            "draft_generation": 0,
        },
        "created_at": FIXED_TIME,
    }

    edited = copy.deepcopy(valid_scenario)
    edited["title"] = "Second immutable revision"
    updated = library.update_draft(
        draft.scenario_id,
        edited,
        expected_generation=0,
        actor="local_operator",
    )
    second = library.save_draft(
        draft.scenario_id,
        expected_generation=updated.generation,
        actor="local_operator",
    )

    assert second.parent_revision_id == first.revision_id
    assert second.revision_number == 2
    assert second.canonical_digest == hashlib.sha256(
        canonical_bytes(edited)
    ).hexdigest()
    assert library.get_revision(first.revision_id).to_dict() == first.to_dict()
    assert [revision.revision_id for revision in library.history(draft.scenario_id)] == [
        "revision-0001",
        "revision-0002",
    ]
    assert library.latest_revision(draft.scenario_id).to_dict() == second.to_dict()


def test_stale_draft_update_fails_without_overwriting_newer_content(
    tmp_path: Path,
    valid_scenario: dict[str, Any],
) -> None:
    library = _deterministic_library(tmp_path)
    draft = library.create_draft(valid_scenario)
    first_edit = copy.deepcopy(valid_scenario)
    first_edit["title"] = "accepted edit"
    stale_edit = copy.deepcopy(valid_scenario)
    stale_edit["title"] = "stale edit"

    library.update_draft(
        draft.scenario_id,
        first_edit,
        expected_generation=0,
    )
    with pytest.raises(DraftConflictError, match="draft generation conflict"):
        library.update_draft(
            draft.scenario_id,
            stale_edit,
            expected_generation=0,
        )

    assert library.get_draft(draft.scenario_id).to_dict()["content"] == first_edit


def test_concurrent_saves_form_one_append_only_parent_chain(
    tmp_path: Path,
    valid_scenario: dict[str, Any],
) -> None:
    library = LocalScenarioLibrary(tmp_path)
    draft = library.create_draft(valid_scenario)

    with ThreadPoolExecutor(max_workers=8) as executor:
        revisions = list(
            executor.map(
                lambda _: library.save_draft(draft.scenario_id),
                range(8),
            )
        )

    history = library.history(draft.scenario_id)
    assert len(history) == 8
    assert len({revision.revision_id for revision in revisions}) == 8
    assert [revision.revision_number for revision in history] == list(range(1, 9))
    assert history[0].parent_revision_id is None
    assert [revision.parent_revision_id for revision in history[1:]] == [
        revision.revision_id for revision in history[:-1]
    ]
    assert library.latest_revision(draft.scenario_id).revision_id == history[-1].revision_id


def test_failed_transaction_publishes_neither_revision_nor_latest_pointer(
    tmp_path: Path,
    valid_scenario: dict[str, Any],
) -> None:
    armed = True

    def fail_after_insert(stage: str) -> None:
        nonlocal armed
        if armed and stage == "after_revision_insert":
            armed = False
            raise RuntimeError("injected storage failure")

    storage = SQLiteLibraryStorage(
        tmp_path / "library.sqlite3",
        fault_injector=fail_after_insert,
    )
    library = LocalScenarioLibrary(storage=storage)
    draft = library.create_draft(valid_scenario)

    with pytest.raises(RuntimeError, match="injected storage failure"):
        library.save_draft(draft.scenario_id)

    assert library.history(draft.scenario_id) == ()
    assert library.latest_revision(draft.scenario_id) is None
    recovered = library.save_draft(draft.scenario_id)
    assert recovered.parent_revision_id is None
    assert recovered.revision_number == 1


def test_archive_hides_catalog_entry_but_preserves_frozen_history(
    tmp_path: Path,
    valid_scenario: dict[str, Any],
) -> None:
    library = _deterministic_library(tmp_path)
    draft = library.create_draft(valid_scenario)
    revision = library.save_draft(draft.scenario_id)
    before = revision.to_dict()

    tombstone = library.archive_scenario(draft.scenario_id, actor="local_operator")

    assert tombstone.to_dict() == {
        "tombstone_id": "tombstone-0001",
        "scenario_id": "scenario-0001",
        "latest_revision_id": "revision-0001",
        "archived_at": FIXED_TIME,
        "provenance": {
            "kind": "scenario_archive",
            "actor": "local_operator",
            "created_at": FIXED_TIME,
        },
    }
    assert library.list_scenarios() == ()
    assert [item.scenario_id for item in library.list_scenarios(include_archived=True)] == [
        draft.scenario_id
    ]
    assert library.get_revision(revision.revision_id).to_dict() == before

    with pytest.raises(ArchivedScenarioError, match="scenario is archived"):
        library.update_draft(
            draft.scenario_id,
            valid_scenario,
            expected_generation=0,
        )
    with pytest.raises(ImmutableRevisionError, match="revisions are append-only"):
        library.overwrite_revision(revision.revision_id, valid_scenario)
    with pytest.raises(ImmutableRevisionError, match="revisions are append-only"):
        library.delete_revision(revision.revision_id)
    with pytest.raises(ImmutableRevisionError, match="scenarios cannot be hard-deleted"):
        library.delete_scenario(draft.scenario_id)

    connection = sqlite3.connect(storage_path := tmp_path / "library.sqlite3")
    try:
        with pytest.raises(sqlite3.DatabaseError, match="immutable revision"):
            connection.execute(
                "UPDATE revisions SET canonical_digest = 'changed' WHERE revision_id = ?",
                (revision.revision_id,),
            )
        connection.rollback()
        with pytest.raises(sqlite3.DatabaseError, match="immutable revision"):
            connection.execute(
                "DELETE FROM revisions WHERE revision_id = ?",
                (revision.revision_id,),
            )
    finally:
        connection.close()
    assert storage_path.is_file()


def test_library_reopens_persisted_drafts_revisions_and_tombstones(
    tmp_path: Path,
    valid_scenario: dict[str, Any],
) -> None:
    first_process = LocalScenarioLibrary(tmp_path)
    draft = first_process.create_draft(valid_scenario)
    revision = first_process.save_draft(draft.scenario_id)
    tombstone = first_process.archive_scenario(draft.scenario_id)

    reopened = LocalScenarioLibrary(tmp_path)

    assert reopened.get_draft(draft.scenario_id).archived is True
    assert reopened.get_revision(revision.revision_id).to_dict() == revision.to_dict()
    assert reopened.tombstones(draft.scenario_id)[0].to_dict() == tombstone.to_dict()
