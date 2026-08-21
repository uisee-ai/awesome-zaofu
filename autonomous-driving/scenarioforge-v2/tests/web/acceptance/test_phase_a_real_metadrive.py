from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from scenarioforge.authoring.library import LocalScenarioLibrary, ScenarioRevision
from scenarioforge.authoring.preflight import preflight_revision
from scenarioforge.authoring.presets import PresetCatalog
from scenarioforge.core import (
    CompilationStatus,
    canonical_bytes,
    canonical_digest,
    strict_loads,
)
from scenarioforge.runtime import RunSupervisor
from scenarioforge.runtime.contracts import RunOutcome
from scenarioforge.web.api import RevisionAwareEvidenceReader
from scenarioforge.web.evidence import EvidenceValidationError, PublishedEvidenceReader
from tests.web.acceptance.test_p0c_counterfactuals import (
    COUNTERFACTUALS,
    _apply_counterfactual,
    _observed_axes,
)


ROOT = Path(__file__).resolve().parents[3]
TRACEABILITY_KEYS = {
    "scenario_revision_digest",
    "scenario_instance_digest",
    "compile_bundle_digest",
    "compile_report_digest",
    "execution_plan_digest",
    "policy_digest",
    "code_commit",
    "adapter_digest",
    "metadrive_digest",
    "assets_digest",
    "environment_digest",
    "seed",
}


def _json(path: Path) -> dict[str, Any] | list[Any]:
    value = strict_loads(path.read_bytes())
    assert isinstance(value, (dict, list))
    return value


def _assert_real_backend(outcome: RunOutcome) -> None:
    worker = _json(outcome.published_path / "output" / "worker_result.json")
    assert isinstance(worker, dict)
    assert outcome.worker_exited is True
    assert outcome.worker_exit_code == 0
    assert worker["backend"] == {
        "asset_version": "0.4.3",
        "distribution": "metadrive-simulator",
        "engine_class": "MultiAgentMetaDrive",
        "version": "0.4.3",
    }


def _run_revision(
    revision: ScenarioRevision,
    supervisor: RunSupervisor,
    run_id: str,
) -> RunOutcome:
    preflight = preflight_revision(revision)
    assert preflight.status is CompilationStatus.EXACT
    assert preflight.executable is True
    assert preflight.report.diagnostics == ()
    outcome = supervisor.run(
        preflight.bundle,
        run_id=run_id,
        attempt_id="attempt-0001",
        timeout_seconds=120,
    )
    assert isinstance(outcome, RunOutcome)
    _assert_real_backend(outcome)
    return outcome


def _assert_revision_traceability(
    outcome: RunOutcome,
    revision: ScenarioRevision,
) -> None:
    reader = RevisionAwareEvidenceReader(
        PublishedEvidenceReader(publish_root=outcome.published_path.parents[1])
    )
    terminal = reader.terminal(outcome.run_result.run_id, outcome.run_result.attempt_id)
    playback = reader.playback(outcome.run_result.run_id, outcome.run_result.attempt_id)
    manifest = _json(outcome.published_path / "input" / "run_manifest.json")
    assert isinstance(manifest, dict)
    frozen_revision = manifest["scenario_revision"]
    instance = manifest["scenario_instance"]
    trace = manifest["traceability"]
    assert terminal["scenario_revision"] == frozen_revision
    assert playback["scenario_revision"] == frozen_revision
    assert terminal["revision_traceability"] == trace
    assert playback["traceability_digest"] == canonical_digest(trace)
    assert set(trace) == TRACEABILITY_KEYS
    assert frozen_revision == {
        "scenario_id": revision.scenario_id,
        "revision_id": revision.revision_id,
        "digest": revision.canonical_digest,
        "schema_version": revision.schema_version,
    }
    assert instance["scenario_id"] == frozen_revision["scenario_id"]
    assert instance["revision_id"] == frozen_revision["revision_id"]
    assert instance["revision_digest"] == frozen_revision["digest"]
    assert trace["scenario_revision_digest"] == frozen_revision["digest"]
    assert trace["scenario_instance_digest"] == manifest["scenario_instance_digest"]
    assert trace["compile_bundle_digest"] == manifest["compile_bundle_digest"]
    assert trace["compile_report_digest"] == manifest["compile_report"]["digest"]
    assert trace["execution_plan_digest"] == manifest["execution_plan"]["digest"]
    assert trace["policy_digest"] == canonical_digest(manifest["policy"])
    assert trace["adapter_digest"] == manifest["adapter"]["digest"]
    assert trace["metadrive_digest"] == canonical_digest(manifest["simulator"])
    assert trace["assets_digest"] == manifest["assets"]["digest"]
    assert trace["environment_digest"] == canonical_digest(manifest["environment"])
    assert trace["seed"] == manifest["seed"]
    candidate = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert trace["code_commit"] == candidate
    assert terminal["playable"] is True
    assert playback["trajectory"]


@pytest.mark.parametrize(
    "counterfactual",
    json.loads(COUNTERFACTUALS.read_text(encoding="utf-8"))["counterfactuals"],
    ids=lambda item: item["preset_id"],
)
def test_each_frozen_preset_and_hazard_counterfactual_run_in_real_metadrive(
    counterfactual: dict[str, Any],
    tmp_path: Path,
) -> None:
    preset_id = counterfactual["preset_id"]
    baseline_path = ROOT / "examples" / "p0c" / f"{preset_id}.json"
    baseline_source = json.loads(baseline_path.read_text(encoding="utf-8"))
    assert canonical_digest(baseline_source) == counterfactual["baseline_source_spec_digest"]
    variant_source = _apply_counterfactual(baseline_source, counterfactual)
    catalog = PresetCatalog(ROOT / "examples" / "p0c")
    library = LocalScenarioLibrary(tmp_path / "library", preset_catalog=catalog)
    baseline_revision = library.fork_preset(preset_id)
    variant_revision = library.fork_preset(preset_id, variant_source)
    supervisor = RunSupervisor(workspace=tmp_path / "runs", project_root=ROOT)
    baseline = _run_revision(
        baseline_revision,
        supervisor,
        f"run-phase-a-baseline-{preset_id}",
    )
    variant = _run_revision(
        variant_revision,
        supervisor,
        f"run-phase-a-counterfactual-{preset_id}",
    )
    assert baseline_revision.provenance["kind"] == "preset_fork"
    assert baseline_revision.provenance["template_id"] == preset_id
    assert variant_revision.provenance["template_digest"] == (
        baseline_revision.provenance["template_digest"]
    )
    assert baseline_revision.canonical_digest != variant_revision.canonical_digest
    assert _observed_axes(baseline)["outcome"]["scenario_outcome"] == (
        counterfactual["baseline_outcome"]
    )
    baseline_axes = _observed_axes(baseline)
    variant_axes = _observed_axes(variant)
    changed = [
        axis
        for axis in counterfactual["acceptable_changes"]
        if baseline_axes[axis] != variant_axes[axis]
    ]
    assert counterfactual["required_change"] in changed
    _assert_revision_traceability(baseline, baseline_revision)
    _assert_revision_traceability(variant, variant_revision)


@pytest.fixture(scope="module")
def revision_fork_runs(
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, Any]:
    workspace = tmp_path_factory.mktemp("phase-a-revision-fork")
    catalog = PresetCatalog(ROOT / "examples" / "p0c")
    library = LocalScenarioLibrary(workspace / "library", preset_catalog=catalog)
    counterfactual = next(
        item
        for item in json.loads(COUNTERFACTUALS.read_text(encoding="utf-8"))["counterfactuals"]
        if item["preset_id"] == "brake_lead"
    )
    baseline_content = catalog.editable_copy("brake_lead")
    variant_content = _apply_counterfactual(baseline_content, counterfactual)
    baseline_revision = library.fork_preset("brake_lead")
    variant_revision = library.fork_preset("brake_lead", variant_content)
    supervisor = RunSupervisor(workspace=workspace / "runs", project_root=ROOT)
    outcomes: dict[str, RunOutcome] = {}
    for label, revision in (
        ("baseline", baseline_revision),
        ("counterfactual", variant_revision),
    ):
        outcomes[label] = _run_revision(
            revision,
            supervisor,
            f"run-phase-a-fork-{label}",
        )
    return {
        "workspace": workspace,
        "counterfactual": counterfactual,
        "baseline_revision": baseline_revision,
        "variant_revision": variant_revision,
        "baseline": outcomes["baseline"],
        "counterfactual_outcome": outcomes["counterfactual"],
    }


def test_template_fork_consumes_complete_revision_traceability_and_counterfactual(
    revision_fork_runs: dict[str, Any],
) -> None:
    baseline = revision_fork_runs["baseline"]
    variant = revision_fork_runs["counterfactual_outcome"]
    baseline_revision = revision_fork_runs["baseline_revision"]
    variant_revision = revision_fork_runs["variant_revision"]
    counterfactual = revision_fork_runs["counterfactual"]
    for revision in (baseline_revision, variant_revision):
        assert revision.provenance["kind"] == "preset_fork"
        assert revision.provenance["template_id"] == "brake_lead"
        assert revision.provenance["template_digest"]

    changed = [
        axis
        for axis in counterfactual["acceptable_changes"]
        if _observed_axes(baseline)[axis] != _observed_axes(variant)[axis]
    ]
    assert counterfactual["required_change"] in changed
    _assert_revision_traceability(baseline, baseline_revision)
    _assert_revision_traceability(variant, variant_revision)


def _write_canonical(path: Path, value: dict[str, Any]) -> None:
    path.chmod(0o600)
    path.write_bytes(canonical_bytes(value))
    path.chmod(0o444)


def _rewrite_traceability(
    publication: Path,
    mutate: Any,
) -> None:
    manifest = _json(publication / "input" / "run_manifest.json")
    result = _json(publication / "run_result.json")
    index = _json(publication / "artifact_index.json")
    marker = _json(publication / "SUCCESS")
    assert all(isinstance(item, dict) for item in (manifest, result, index, marker))
    mutate(manifest)
    manifest_payload = canonical_bytes(manifest)
    manifest_digest = hashlib.sha256(manifest_payload).hexdigest()
    traceability_digest = canonical_digest(manifest["traceability"])
    result["run_manifest_digest"] = manifest_digest
    result["traceability_digest"] = traceability_digest
    index["run_manifest_digest"] = manifest_digest
    index["traceability_digest"] = traceability_digest
    manifest_entry = next(
        entry
        for entry in index["artifacts"]
        if entry["path"] == "input/run_manifest.json"
    )
    manifest_entry["size_bytes"] = len(manifest_payload)
    manifest_entry["digest"] = manifest_digest
    result["artifact_index_digest"] = canonical_digest(index)
    marker["run_result_digest"] = hashlib.sha256(canonical_bytes(result)).hexdigest()
    marker["artifact_index_digest"] = hashlib.sha256(canonical_bytes(index)).hexdigest()
    _write_canonical(publication / "input" / "run_manifest.json", manifest)
    _write_canonical(publication / "run_result.json", result)
    _write_canonical(publication / "artifact_index.json", index)
    _write_canonical(publication / "SUCCESS", marker)


@pytest.mark.parametrize(
    ("case", "mutate"),
    [
        ("missing", lambda manifest: manifest["traceability"].pop("assets_digest")),
        (
            "ambiguous",
            lambda manifest: manifest["scenario_revision"].update(
                {"scenario_id": "different-scenario"}
            ),
        ),
        (
            "digest-mismatch",
            lambda manifest: manifest["traceability"].update(
                {"adapter_digest": "0" * 64}
            ),
        ),
    ],
)
def test_revision_reader_rejects_incomplete_ambiguous_or_mismatched_traceability(
    revision_fork_runs: dict[str, Any],
    tmp_path: Path,
    case: str,
    mutate: Any,
) -> None:
    outcome = revision_fork_runs["baseline"]
    publish_root = tmp_path / case / "published"
    publication = publish_root / outcome.run_result.run_id / outcome.run_result.attempt_id
    shutil.copytree(outcome.published_path, publication)
    _rewrite_traceability(publication, mutate)
    reader = RevisionAwareEvidenceReader(PublishedEvidenceReader(publish_root=publish_root))
    with pytest.raises(EvidenceValidationError):
        reader.playback(outcome.run_result.run_id, outcome.run_result.attempt_id)
