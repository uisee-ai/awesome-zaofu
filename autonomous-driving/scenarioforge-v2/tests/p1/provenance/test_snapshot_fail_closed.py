from __future__ import annotations

import json
from pathlib import Path

import pytest

from scenarioforge.provenance import (
    ExecutionSnapshotError,
    validate_execution_snapshot,
    validate_provenance_chain,
)


ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "tests/fixtures/p1/provenance/tamper-matrix.json"


def _apply_case(value: dict[str, object], case: dict[str, object]) -> None:
    parts = str(case["path"]).split(".")
    target: object = value
    for part in parts[:-1]:
        target = target[int(part)] if isinstance(target, list) else target[part]  # type: ignore[index]
    last = parts[-1]
    if case["operation"] == "remove":
        assert isinstance(target, dict)
        del target[last]
    elif isinstance(target, list):
        target[int(last)] = case["value"]
    else:
        assert isinstance(target, dict)
        target[last] = case["value"]


def test_tamper_matrix_is_complete_and_every_case_fails_closed(provenance_chain) -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert fixture == {
        "schema_version": "scenarioforge.provenance-tamper-matrix/v1",
        "cases": fixture["cases"],
    }
    assert [case["case_id"] for case in fixture["cases"]] == [
        "missing-defaults",
        "spec-digest-tamper",
        "code-digest-invalid",
        "backend-identity-spoof",
        "simulator-version-drift",
        "receipt-digest-tamper",
        "partial-artifact",
        "terminal-partial",
        "terminal-snapshot-mismatch",
        "trajectory-snapshot-mismatch",
        "replay-index-mismatch",
    ]

    for case in fixture["cases"]:
        tampered = json.loads(json.dumps(provenance_chain.to_dict()))
        _apply_case(tampered, case)
        with pytest.raises(ExecutionSnapshotError, match=str(case["error"])):
            validate_provenance_chain(tampered)


def test_expected_code_backend_and_simulator_drift_fail_closed(execution_snapshot) -> None:
    with pytest.raises(ExecutionSnapshotError, match="code digest drift"):
        validate_execution_snapshot(execution_snapshot, expected_code_digest="0" * 64)
    with pytest.raises(ExecutionSnapshotError, match="adapter identity drift"):
        validate_execution_snapshot(
            execution_snapshot,
            expected_adapter={
                "id": "scenarioforge.metadrive",
                "version": "0.4.3",
                "digest": "9" * 64,
            },
        )
    with pytest.raises(ExecutionSnapshotError, match="simulator identity drift"):
        validate_execution_snapshot(
            execution_snapshot,
            expected_simulator={
                "distribution": "smarts",
                "version": "2.1.0",
                "digest": "d" * 64,
            },
        )
