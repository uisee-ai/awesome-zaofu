from __future__ import annotations

import json
from pathlib import Path

import pytest

from scenarioforge.authoring.library import LocalScenarioLibrary
from scenarioforge.authoring.preflight import preflight_revision
from scenarioforge.authoring.presets import PresetCatalog
from scenarioforge.core import (
    ScenarioCompiler,
    canonical_digest,
    instantiate_scenario,
    load_scenario,
)
from scenarioforge.runtime import RunSupervisor


ROOT = Path(__file__).resolve().parents[2]


def _read(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_revision_aware_success_chain_publishes_complete_v3_traceability(
    tmp_path: Path,
) -> None:
    catalog = PresetCatalog(ROOT / "examples" / "p0c")
    library = LocalScenarioLibrary(tmp_path / "library", preset_catalog=catalog)
    revision = library.fork_preset("brake_lead")
    preflight = preflight_revision(revision)

    outcome = RunSupervisor(
        workspace=tmp_path / "runs",
        project_root=ROOT,
    ).run(
        preflight.bundle,
        run_id="run-revision-aware",
        attempt_id="attempt-0001",
        timeout_seconds=120,
    )

    manifest = _read(outcome.input_snapshot_path / "run_manifest.json")
    request = _read(outcome.input_snapshot_path / "run_request.json")
    result = _read(outcome.published_path / "run_result.json")
    index = _read(outcome.published_path / "artifact_index.json")
    traceability_digest = canonical_digest(manifest["traceability"])

    assert manifest["schema_version"] == "scenarioforge.run-manifest/v3"
    assert request["schema_version"] == "scenarioforge.run-request/v3"
    assert result["schema_version"] == "scenarioforge.run-result/v3"
    assert index["schema_version"] == "scenarioforge.artifact-index/v3"
    assert result == outcome.run_result.to_dict()
    assert index == outcome.artifact_index.to_dict()
    for published_contract in (result, index):
        assert published_contract["traceability_digest"] == traceability_digest
        assert published_contract["scenario_revision_digest"] == revision.canonical_digest
    assert result["run_manifest_digest"] == request["run_manifest_digest"]
    assert index["run_manifest_digest"] == request["run_manifest_digest"]
    assert result["artifact_index_digest"] == canonical_digest(index)


@pytest.mark.parametrize(
    ("scenario_path", "contract_version"),
    [
        (ROOT / "examples" / "p0a" / "brake_lead.json", "v1"),
        (
            ROOT / "tests" / "fixtures" / "p0c" / "contracts" / "prototype_v2.json",
            "v2",
        ),
    ],
)
def test_success_publish_preserves_legacy_contract_versions(
    tmp_path: Path,
    scenario_path: Path,
    contract_version: str,
) -> None:
    bundle = ScenarioCompiler().compile(
        instantiate_scenario(load_scenario(scenario_path))
    )

    outcome = RunSupervisor(
        workspace=tmp_path / "runs",
        project_root=ROOT,
    ).run(
        bundle,
        run_id=f"run-legacy-{contract_version}",
        attempt_id="attempt-0001",
        timeout_seconds=120,
    )

    assert outcome.run_request.schema_version == (
        f"scenarioforge.run-request/{contract_version}"
    )
    assert outcome.run_result.schema_version == (
        f"scenarioforge.run-result/{contract_version}"
    )
    assert outcome.artifact_index.schema_version == (
        f"scenarioforge.artifact-index/{contract_version}"
    )
    assert "traceability_digest" not in outcome.run_result.to_dict()
    assert "scenario_revision_digest" not in outcome.run_result.to_dict()
    assert "traceability_digest" not in outcome.artifact_index.to_dict()
    assert "scenario_revision_digest" not in outcome.artifact_index.to_dict()
