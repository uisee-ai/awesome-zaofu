from __future__ import annotations

import json
from pathlib import Path

import pytest

from scenarioforge.core import canonical_digest
from scenarioforge.provenance import (
    CHAIN_LINK_FIELDS,
    REQUIRED_IDENTITY_FIELDS,
    REQUIRED_SNAPSHOT_FIELDS,
    validate_execution_snapshot,
    validate_provenance_chain,
)


ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "tests/fixtures/p1/provenance/required-fields.json"


def test_required_field_fixture_is_an_exact_golden_contract() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))

    assert fixture == {
        "schema_version": "scenarioforge.provenance-required-fields/v1",
        "execution_snapshot": list(REQUIRED_SNAPSHOT_FIELDS),
        "identity_fields": {
            key: list(value) for key, value in REQUIRED_IDENTITY_FIELDS.items()
        },
        "chain_links": {key: list(value) for key, value in CHAIN_LINK_FIELDS.items()},
    }


def test_execution_snapshot_contains_every_required_identity_and_digest(
    execution_snapshot,
) -> None:
    value = execution_snapshot.to_dict()

    assert tuple(value) == REQUIRED_SNAPSHOT_FIELDS
    assert value["normalized_scenario_spec_digest"] == canonical_digest(
        value["normalized_scenario_spec"]
    )
    assert value["resolved_defaults_digest"] == canonical_digest(value["resolved_defaults"])
    assert value["run_parameters_digest"] == canonical_digest(value["run_parameters"])
    assert value["environment_digest"] == canonical_digest(value["environment"])
    assert validate_execution_snapshot(
        execution_snapshot,
        expected_code_digest="b" * 64,
        expected_adapter={"id": "scenarioforge.smarts", "version": "2.0.1", "digest": "c" * 64},
        expected_simulator={"distribution": "smarts", "version": "2.0.1", "digest": "d" * 64},
    ) == execution_snapshot.digest

    with pytest.raises(TypeError):
        execution_snapshot.normalized_scenario_spec["traffic_side"] = "left"


def test_manifest_receipt_index_and_consumers_bind_one_verified_snapshot(
    provenance_chain,
) -> None:
    value = provenance_chain.to_dict()
    snapshot = provenance_chain.execution_snapshot
    snapshot_digest = snapshot.digest

    assert validate_provenance_chain(provenance_chain) == snapshot_digest
    assert value["run_manifest"]["execution_snapshot"] == snapshot.to_dict()
    for name in (
        "run_manifest",
        "compile_report",
        "worker_receipt",
        "artifact_index",
        "terminal_state",
        "trajectory",
        "replay",
    ):
        assert value[name]["execution_snapshot_id"] == snapshot.execution_snapshot_id
        assert value[name]["execution_snapshot_digest"] == snapshot_digest

    assert value["worker_receipt"]["run_manifest_digest"] == canonical_digest(
        value["run_manifest"]
    )
    assert value["artifact_index"]["worker_receipt_digest"] == canonical_digest(
        value["worker_receipt"]
    )
    artifact_index_digest = canonical_digest(value["artifact_index"])
    assert value["terminal_state"]["artifact_index_digest"] == artifact_index_digest
    assert value["trajectory"]["artifact_index_digest"] == artifact_index_digest
    assert value["replay"]["artifact_index_digest"] == artifact_index_digest
