from __future__ import annotations

import json
from pathlib import Path

from scenarioforge.authoring.library import LocalScenarioLibrary
from scenarioforge.authoring.preflight import preflight_revision
from scenarioforge.authoring.presets import PresetCatalog
from scenarioforge.core import CompilationStatus, canonical_digest


ROOT = Path(__file__).resolve().parents[2]


def test_preflight_binds_revision_compiler_capabilities_and_adapter(tmp_path: Path) -> None:
    catalog = PresetCatalog(ROOT / "examples" / "p0c")
    library = LocalScenarioLibrary(tmp_path, preset_catalog=catalog)
    revision = library.fork_preset("brake_lead")

    result = preflight_revision(revision)

    assert result.status is CompilationStatus.EXACT
    assert result.scenario_instance.scenario_id == revision.scenario_id
    assert result.scenario_instance.revision_id == revision.revision_id
    assert result.scenario_instance.revision_digest == revision.canonical_digest
    assert result.report.capability_descriptor_digest == result.capabilities.digest
    assert result.report.adapter_id == result.capabilities.adapter_id
    assert result.report.adapter_version == result.capabilities.adapter_version
    assert result.report.adapter_digest == canonical_digest(
        {"id": result.capabilities.adapter_id, "version": result.capabilities.adapter_version}
    )


def test_full_authoring_revision_has_field_and_scenario_fidelity_mapping(tmp_path: Path) -> None:
    content = json.loads(
        (ROOT / "tests/fixtures/authoring/valid_scenario.json").read_text(encoding="utf-8")
    )
    library = LocalScenarioLibrary(tmp_path)
    revision = library.save_draft(library.create_draft(content).scenario_id)

    result = preflight_revision(revision)

    assert result.status is CompilationStatus.UNSUPPORTED
    paths = {item.path for item in result.report.mappings}
    assert {
        "$.title", "$.description", "$.seed", "$.road", "$.routes", "$.actors",
        "$.static_obstacles", "$.environment", "$.events", "$.constraints",
        "$.parameters", "$.policy", "$.required_capabilities",
    } <= paths
    assert any(
        item.path == "$.actors[2].kind" and item.status is CompilationStatus.UNSUPPORTED
        for item in result.report.diagnostics
    )
