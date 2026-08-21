from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scenarioforge.authoring.library import LocalScenarioLibrary
from scenarioforge.authoring.preflight import preflight_revision
from scenarioforge.core import CompilationStatus
from scenarioforge.runtime.confirmation import (
    ConfirmationMismatch,
    ConfirmationReplay,
    ConfirmationStale,
    LossyConfirmationAuthority,
)
from scenarioforge.runtime.snapshot import prepare_run


ROOT = Path(__file__).resolve().parents[2]


def _lossy(tmp_path: Path, width: float = 3.6):
    value = json.loads((ROOT / "examples/p0a/brake_lead.json").read_text(encoding="utf-8"))
    value["road"]["lane_width_m"] = width
    library = LocalScenarioLibrary(tmp_path)
    revision = library.save_draft(library.create_draft(value).scenario_id)
    return preflight_revision(revision)


def test_lossy_confirmation_is_explicit_local_and_single_use(tmp_path: Path) -> None:
    now = datetime(2026, 8, 14, 10, 0, tzinfo=timezone.utc)
    result = _lossy(tmp_path)
    authority = LossyConfirmationAuthority(clock=lambda: now, id_factory=lambda: "confirm-1")

    assert result.status is CompilationStatus.LOSSY
    confirmation = authority.issue(result, run_id="run-1", attempt_id="attempt-1")
    bound = authority.consume(
        confirmation, preflight=result, run_id="run-1", attempt_id="attempt-1"
    )
    assert bound.confirmation == confirmation.to_dict()
    prepared = prepare_run(
        bound,
        workspace=tmp_path / "runs",
        project_root=ROOT,
        run_id="run-1",
        attempt_id="attempt-1",
    )
    manifest = json.loads(
        (prepared.input_snapshot_path / "run_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["lossy_confirmation"] == confirmation.to_dict()
    assert manifest["traceability"]["scenario_revision_digest"] == (
        result.revision.canonical_digest
    )
    with pytest.raises(ConfirmationReplay):
        authority.consume(
            confirmation, preflight=result, run_id="run-1", attempt_id="attempt-1"
        )


def test_lossy_confirmation_rejects_mismatch_stale_and_non_local_actor(tmp_path: Path) -> None:
    now = datetime(2026, 8, 14, 10, 0, tzinfo=timezone.utc)
    current = [now]
    result = _lossy(tmp_path / "one")
    other = _lossy(tmp_path / "two", 3.7)
    authority = LossyConfirmationAuthority(clock=lambda: current[0], ttl_seconds=30)
    confirmation = authority.issue(result, run_id="run-2", attempt_id="attempt-1")

    with pytest.raises(ConfirmationMismatch):
        authority.consume(
            confirmation, preflight=other, run_id="run-2", attempt_id="attempt-1"
        )
    with pytest.raises(ConfirmationMismatch, match="local_operator"):
        authority.issue(
            result, run_id="run-2", attempt_id="attempt-1", actor="remote_operator"
        )
    current[0] = now + timedelta(seconds=31)
    with pytest.raises(ConfirmationStale):
        authority.consume(
            confirmation, preflight=result, run_id="run-2", attempt_id="attempt-1"
        )
