from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

import pytest

from scenarioforge.core import (
    ScenarioCompiler,
    StrictJSONError,
    canonical_bytes,
    canonical_digest,
    instantiate_scenario,
    load_scenario,
    strict_loads,
)
from scenarioforge.runtime import RunSupervisor
from scenarioforge.runtime.contracts import RunOutcome
from scenarioforge.web.catalog import scenario_catalog, scenario_metadata
from scenarioforge.web.coordinator import InvalidIdentifierError, UnknownScenarioError
from scenarioforge.web.evidence import (
    EvidenceValidationError,
    PublishedEvidenceReader,
    UnknownArtifactError,
    UnknownPublishedRunError,
    validate_artifact_key,
)


ROOT = Path(__file__).resolve().parents[3]
MATRIX = ROOT / "tests" / "fixtures" / "p0c" / "validation" / "security-matrix.json"
SCENARIO = ROOT / "examples" / "p0c" / "dangerous_cut_in.json"
RUN_ID = "run-p0c-security-matrix"
ATTEMPT_ID = "attempt-0001"


def _json(path: Path) -> Any:
    return strict_loads(path.read_bytes())


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: Any) -> None:
    path.chmod(0o600)
    path.write_bytes(canonical_bytes(value))


def _resign_controls(published: Path, index: dict[str, Any]) -> None:
    index_path = published / "artifact_index.json"
    result_path = published / "run_result.json"
    marker_path = published / "SUCCESS"
    _write(index_path, index)
    result = _json(result_path)
    result["artifact_index_digest"] = canonical_digest(index)
    _write(result_path, result)
    marker = _json(marker_path)
    marker["artifact_index_digest"] = _digest(index_path)
    marker["run_result_digest"] = _digest(result_path)
    _write(marker_path, marker)


def _reindex_artifact(published: Path, relative: str) -> None:
    artifact = published.joinpath(*relative.split("/"))
    index = _json(published / "artifact_index.json")
    entry = next(item for item in index["artifacts"] if item["path"] == relative)
    entry["size_bytes"] = artifact.stat().st_size
    entry["digest"] = _digest(artifact)
    _resign_controls(published, index)


def _rewrite_artifact(published: Path, relative: str, value: Any) -> None:
    artifact = published.joinpath(*relative.split("/"))
    _write(artifact, value)
    _reindex_artifact(published, relative)


@pytest.fixture(scope="module")
def trusted_publication(tmp_path_factory: pytest.TempPathFactory) -> Path:
    bundle = ScenarioCompiler().compile(
        instantiate_scenario(load_scenario(SCENARIO))
    )
    outcome = RunSupervisor(
        workspace=tmp_path_factory.mktemp("p0c-security-source"),
        project_root=ROOT,
    ).run(
        bundle,
        run_id=RUN_ID,
        attempt_id=ATTEMPT_ID,
        timeout_seconds=120,
    )
    assert isinstance(outcome, RunOutcome)
    reader = PublishedEvidenceReader(publish_root=outcome.published_path.parents[1])
    assert reader.terminal(RUN_ID, ATTEMPT_ID)["playable"] is True
    assert reader.playback(RUN_ID, ATTEMPT_ID)["trajectory"]
    return outcome.published_path


def _clone_publication(source: Path, destination: Path) -> Path:
    published = destination / "published" / RUN_ID / ATTEMPT_ID
    shutil.copytree(source, published)
    return published


def _reader(published: Path) -> PublishedEvidenceReader:
    return PublishedEvidenceReader(publish_root=published.parents[1])


def test_security_matrix_freezes_every_required_fail_closed_category() -> None:
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))

    assert matrix == {
        "schema_version": "scenarioforge.p0c-security-matrix/v1",
        "categories": [
            "unknown_ids",
            "traversal",
            "absolute_paths",
            "urls",
            "symlinks",
            "special_files",
            "oversize",
            "nan_inf",
            "participant_mismatch",
            "tick_gaps",
            "xss",
            "partial",
            "digest_tampering",
        ],
        "policy": "all cases fail closed without host-path or payload disclosure",
    }


@pytest.mark.parametrize(
    ("scenario_id", "error_type"),
    [
        pytest.param("unknown", UnknownScenarioError, id="unknown-id"),
        pytest.param("../dangerous_cut_in", InvalidIdentifierError, id="traversal"),
        pytest.param("/tmp/dangerous_cut_in", InvalidIdentifierError, id="absolute"),
        pytest.param(
            "https://example.invalid/scenario",
            InvalidIdentifierError,
            id="url",
        ),
        pytest.param("<script>alert(1)</script>", InvalidIdentifierError, id="xss"),
    ],
)
def test_untrusted_catalog_identifiers_fail_before_source_resolution_without_echo(
    scenario_id: str,
    error_type: type[Exception],
) -> None:
    with pytest.raises(error_type) as raised:
        scenario_metadata(scenario_id, profile="p0c")

    assert str(raised.value) == (
        "unknown scenario_id" if scenario_id == "unknown" else "invalid scenario_id"
    )
    if scenario_id != "unknown":
        assert scenario_id not in str(raised.value)
    assert "<script" not in repr(scenario_catalog(profile="p0c")).lower()


def test_unknown_run_and_artifact_ids_fail_closed(tmp_path: Path) -> None:
    (tmp_path / "published").mkdir()
    reader = PublishedEvidenceReader(publish_root=tmp_path / "published")

    with pytest.raises(UnknownPublishedRunError, match="unknown published run"):
        reader.terminal("run-does-not-exist", ATTEMPT_ID)
    with pytest.raises(UnknownArtifactError, match="unknown artifact key"):
        validate_artifact_key("metrics")


@pytest.mark.parametrize("kind", ["symlink", "special-file", "oversize"])
def test_scenario_source_boundary_rejects_non_regular_or_oversize_inputs(
    kind: str,
    tmp_path: Path,
) -> None:
    source = tmp_path / "scenario.json"
    if kind == "symlink":
        source.symlink_to(SCENARIO)
        expected_code = "not_regular_file"
    elif kind == "special-file":
        os.mkfifo(source)
        expected_code = "not_regular_file"
    else:
        source.write_bytes(b"{}" + b" " * 65_536)
        expected_code = "byte_limit_exceeded"

    with pytest.raises(StrictJSONError) as raised:
        load_scenario(source)
    assert raised.value.code == expected_code
    assert str(source) not in str(raised.value)


@pytest.mark.parametrize("token", [b"NaN", b"Infinity", b"-Infinity"])
def test_non_finite_json_numbers_are_rejected(token: bytes) -> None:
    with pytest.raises(StrictJSONError) as raised:
        strict_loads(b'{"speed_mps":' + token + b"}")

    assert raised.value.code == "non_finite_number"


@pytest.mark.parametrize(
    "corruption",
    ["participant-mismatch", "tick-gap", "partial", "oversize", "nan"],
)
def test_semantically_corrupt_or_incomplete_real_evidence_fails_closed(
    corruption: str,
    trusted_publication: Path,
    tmp_path: Path,
) -> None:
    published = _clone_publication(trusted_publication, tmp_path)
    trajectory_path = published / "output" / "trajectory.json"
    if corruption == "participant-mismatch":
        trajectory = _json(trajectory_path)
        trajectory[0]["participant_id"] = "intruder"
        _rewrite_artifact(published, "output/trajectory.json", trajectory)
    elif corruption == "tick-gap":
        trajectory = _json(trajectory_path)
        for point in trajectory:
            if point["tick"] >= 1:
                point["tick"] += 1
        _rewrite_artifact(published, "output/trajectory.json", trajectory)
    elif corruption == "partial":
        index = _json(published / "artifact_index.json")
        entry = next(
            item
            for item in index["artifacts"]
            if item["path"] == "output/trajectory.json"
        )
        entry["validation"] = "verified_partial"
        _resign_controls(published, index)
    elif corruption == "oversize":
        index = _json(published / "artifact_index.json")
        entry = next(
            item
            for item in index["artifacts"]
            if item["path"] == "output/trajectory.json"
        )
        entry["size_bytes"] = 10_485_761
        _resign_controls(published, index)
    else:
        trajectory_path.chmod(0o600)
        payload = trajectory_path.read_bytes()
        payload, replacements = re.subn(
            rb'"speed_mps":-?[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?',
            b'"speed_mps":NaN',
            payload,
            count=1,
        )
        assert replacements == 1
        trajectory_path.write_bytes(payload)
        _reindex_artifact(published, "output/trajectory.json")

    with pytest.raises(EvidenceValidationError):
        _reader(published).terminal(RUN_ID, ATTEMPT_ID)
    with pytest.raises(EvidenceValidationError):
        _reader(published).playback(RUN_ID, ATTEMPT_ID)


def test_symlinked_real_evidence_member_is_never_followed(
    trusted_publication: Path,
    tmp_path: Path,
) -> None:
    published = _clone_publication(trusted_publication, tmp_path)
    trajectory = published / "output" / "trajectory.json"
    outside = tmp_path / "outside.json"
    outside.write_bytes(trajectory.read_bytes())
    trajectory.parent.chmod(0o755)
    trajectory.unlink()
    trajectory.symlink_to(outside)

    with pytest.raises(EvidenceValidationError, match="unavailable|regular") as raised:
        _reader(published).terminal(RUN_ID, ATTEMPT_ID)
    assert str(outside) not in str(raised.value)


@pytest.mark.parametrize(
    "relative",
    ["artifact_index.json", "run_result.json", "output/trajectory.json"],
)
def test_digest_tampering_of_controls_or_artifacts_fails_closed(
    relative: str,
    trusted_publication: Path,
    tmp_path: Path,
) -> None:
    published = _clone_publication(trusted_publication, tmp_path)
    target = published.joinpath(*relative.split("/"))
    target.chmod(0o600)
    target.write_bytes(target.read_bytes() + b" ")

    with pytest.raises(EvidenceValidationError, match="digest|canonical|size"):
        _reader(published).terminal(RUN_ID, ATTEMPT_ID)
