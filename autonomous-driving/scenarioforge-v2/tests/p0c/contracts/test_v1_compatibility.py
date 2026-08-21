from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scenarioforge.core import ScenarioCompiler, canonical_bytes, instantiate_scenario, load_scenario
from scenarioforge.runtime.contracts import ArtifactEntry, ArtifactIndex, RunResult


ROOT = Path(__file__).resolve().parents[3]
HISTORICAL_SPEC = ROOT / "examples" / "p0a" / "brake_lead.json"
HISTORICAL_FIXTURES = ROOT / "tests" / "fixtures" / "p0a" / "happy"


def _fixture(name: str) -> dict[str, object]:
    return json.loads((HISTORICAL_FIXTURES / name).read_text(encoding="utf-8"))


def test_historical_v1_source_instance_and_compile_goldens_are_byte_stable() -> None:
    document = load_scenario(HISTORICAL_SPEC)
    instance = instantiate_scenario(document)
    bundle = ScenarioCompiler().compile(instance)

    assert hashlib.sha256(HISTORICAL_SPEC.read_bytes()).hexdigest() == (
        "7ae9e59862227c9423efa6f499d40406e22177f4978a4eaa5c7947577988b961"
    )
    assert document.canonical_digest == (
        "628e8a458de35889fc1fe80e93aa69abd9a43ae25db438cbb56eb5efa4170498"
    )
    assert canonical_bytes(instance) == canonical_bytes(_fixture("scenario_instance.json"))
    assert instance.digest == "463a1a6f9e48df7c81ba7bbc11844d76906744accc437e8852c5735fb165783e"
    assert bundle.report.to_dict() == _fixture("compile_report.json")
    assert bundle.execution_plan is not None
    assert bundle.execution_plan.to_dict() == _fixture("execution_plan.json")


def test_v1_terminal_models_keep_their_complete_legacy_shape() -> None:
    entry = ArtifactEntry(
        path="output/trajectory.json",
        status="present",
        size_bytes=2,
        digest="a" * 64,
        validation="verified",
    )
    index = ArtifactIndex(
        schema_version="scenarioforge.artifact-index/v1",
        run_id="run-v1",
        attempt_id="attempt-v1",
        artifacts=(entry,),
    )
    result = RunResult(
        schema_version="scenarioforge.run-result/v1",
        run_id="run-v1",
        attempt_id="attempt-v1",
        status="success",
        reason="horizon_completed",
        worker_exit_code=0,
        run_manifest_digest="b" * 64,
        compile_report_digest="c" * 64,
        execution_plan_digest="d" * 64,
        artifact_index_digest=index.digest,
    )

    assert index.to_dict() == {
        "schema_version": "scenarioforge.artifact-index/v1",
        "run_id": "run-v1",
        "attempt_id": "attempt-v1",
        "artifacts": [entry.to_dict()],
    }
    assert result.to_dict() == {
        "schema_version": "scenarioforge.run-result/v1",
        "run_id": "run-v1",
        "attempt_id": "attempt-v1",
        "status": "success",
        "reason": "horizon_completed",
        "worker_exit_code": 0,
        "run_manifest_digest": "b" * 64,
        "compile_report_digest": "c" * 64,
        "execution_plan_digest": "d" * 64,
        "artifact_index_digest": index.digest,
    }
