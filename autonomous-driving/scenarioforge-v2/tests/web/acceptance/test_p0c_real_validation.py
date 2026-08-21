from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
from pathlib import Path
from typing import Any

import pytest

from scenarioforge.core import (
    CompilationStatus,
    ScenarioCompiler,
    canonical_digest,
    instantiate_scenario,
    load_scenario,
    strict_loads,
)
from scenarioforge.repro import ToleranceProfile, compare_trajectory_series
from scenarioforge.runtime import RunSupervisor
from scenarioforge.runtime.contracts import RunOutcome
from scenarioforge.web.evidence import PublishedEvidenceReader


ROOT = Path(__file__).resolve().parents[3]
GOLDEN = (
    ROOT / "tests" / "fixtures" / "p0c" / "validation" / "real-metadrive.json"
)


def _json(path: Path) -> Any:
    return strict_loads(path.read_bytes())


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _metric_values(metrics: dict[str, Any]) -> dict[str, Any]:
    return {item["metric"]: item["value"] for item in metrics["metric_values"]}


@pytest.fixture(scope="module")
def real_validation(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[dict[str, Any], dict[str, Any]]:
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    tolerance = golden["tolerance_profile"]
    profile = ToleranceProfile(
        schema_version="scenarioforge.tolerance-profile/v1",
        tolerances_version=tolerance["version"],
        position_m=tolerance["position_abs_m"],
        speed_mps=tolerance["speed_abs_mps"],
        heading_deg=tolerance["heading_abs_deg"],
        min_ttc_s=tolerance["min_ttc_abs_s"],
        completed_steps=tolerance["completed_steps"],
    )
    results: dict[str, Any] = {}
    workspace = tmp_path_factory.mktemp("p0c-real-validation")

    for preset in golden["presets"]:
        preset_id = preset["preset_id"]
        document = load_scenario(ROOT / "examples" / "p0c" / f"{preset_id}.json")
        assert document.canonical_digest == preset["source_spec_digest"]
        bundle = ScenarioCompiler().compile(instantiate_scenario(document))
        assert bundle.report.overall_status is CompilationStatus.EXACT
        assert bundle.report.executable is True
        assert bundle.report.diagnostics == ()
        assert all(
            mapping.status is CompilationStatus.EXACT
            for mapping in bundle.report.mappings
        )
        assert bundle.execution_plan is not None
        assert bundle.execution_plan.tolerances_version == preset["plan_tolerances"]

        supervisor = RunSupervisor(
            workspace=workspace / preset_id,
            project_root=ROOT,
        )
        runs = tuple(
            supervisor.run(
                bundle,
                run_id=f"run-p0c-real-{preset_id}-{run_index:04d}",
                attempt_id="attempt-0001",
                timeout_seconds=120,
            )
            for run_index in range(1, 4)
        )
        assert all(isinstance(run, RunOutcome) for run in runs)
        trajectories = [
            _json(run.published_path / "output" / "trajectory.json")
            for run in runs
        ]
        metrics = [
            _json(run.published_path / "output" / "metrics.json") for run in runs
        ]
        results[preset_id] = {
            "runs": runs,
            "continuous": compare_trajectory_series(trajectories, metrics, profile),
            "action_digests": [
                canonical_digest(
                    _json(run.published_path / "output" / "actions.json")
                )
                for run in runs
            ],
            "event_sequences": [
                _json(run.published_path / "output" / "events.json") for run in runs
            ],
        }
    return golden, results


def test_real_metadrive_validation_uses_a_versioned_exact_golden_contract() -> None:
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))

    assert golden["schema_version"] == "scenarioforge.p0c-real-validation/v1"
    assert golden["environment"] == {
        "os": "Linux",
        "architecture": "x86_64",
        "python": "3.11.15",
        "simulator_distribution": "metadrive-simulator",
        "simulator_version": "0.4.3",
        "headless": True,
    }
    assert golden["reproduction_runs"] == 3
    assert [item["preset_id"] for item in golden["presets"]] == [
        "construction_merge",
        "highway_merge",
        "brake_lead",
        "dangerous_cut_in",
        "unprotected_left_turn",
    ]


def test_each_exact_preset_completes_three_independent_real_metadrive_runs(
    real_validation: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    golden, results = real_validation

    assert (platform.system(), platform.machine()) == ("Linux", "x86_64")
    assert platform.python_version() == "3.11.15"
    assert importlib.metadata.version("metadrive-simulator") == "0.4.3"
    for preset in golden["presets"]:
        result = results[preset["preset_id"]]
        assert result["continuous"].passed is True
        assert result["continuous"].violations == ()
        assert len(set(result["action_digests"])) == 1
        assert result["event_sequences"][1:] == [result["event_sequences"][0]] * 2
        assert len({run.run_result.run_id for run in result["runs"]}) == 3
        assert all(run.worker_exited and run.worker_exit_code == 0 for run in result["runs"])
        assert all(
            not (run.input_snapshot_path / "actions.json").exists()
            for run in result["runs"]
        )
        assert all(
            _json(run.published_path / "output" / "worker_result.json")["backend"]
            == {
                "asset_version": "0.4.3",
                "distribution": "metadrive-simulator",
                "engine_class": "MultiAgentMetaDrive",
                "version": "0.4.3",
            }
            for run in result["runs"]
        )


def test_all_runs_preserve_ordered_events_outcome_metrics_and_trajectory_tolerances(
    real_validation: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    golden, results = real_validation

    for preset in golden["presets"]:
        result = results[preset["preset_id"]]
        for run in result["runs"]:
            events = _json(run.published_path / "output" / "events.json")
            metrics = _json(run.published_path / "output" / "metrics.json")
            values = _metric_values(metrics)
            assert [event["event_id"] for event in events] == preset["event_ids"]
            assert [event["sequence"] for event in events] == list(
                range(len(preset["event_ids"]))
            )
            assert metrics["scenario_outcome"] == preset["scenario_outcome"]
            assert metrics["target_outcome_match"] is True
            assert metrics["termination_reason"] == preset["termination_reason"]
            for metric, bounds in preset["metric_ranges"].items():
                if bounds is None:
                    assert values[metric] is None
                else:
                    assert bounds["minimum"] <= values[metric] <= bounds["maximum"]

        maximums = result["continuous"].max_deltas
        tolerance = golden["tolerance_profile"]
        assert maximums["position_m"] <= tolerance["position_abs_m"]
        assert maximums["speed_mps"] <= tolerance["speed_abs_mps"]
        assert maximums["heading_deg"] <= tolerance["heading_abs_deg"]


def test_every_published_run_is_complete_digest_bound_and_reader_verified(
    real_validation: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    golden, results = real_validation

    for result in results.values():
        for run in result["runs"]:
            published = run.published_path
            index = _json(published / "artifact_index.json")
            assert [entry["path"] for entry in index["artifacts"]] == golden[
                "required_artifacts"
            ]
            for entry in index["artifacts"]:
                artifact = published.joinpath(*entry["path"].split("/"))
                assert entry == {
                    "path": entry["path"],
                    "status": "present",
                    "size_bytes": artifact.stat().st_size,
                    "digest": _digest(artifact),
                    "validation": "verified",
                }

            reader = PublishedEvidenceReader(publish_root=published.parents[1])
            terminal = reader.terminal(
                run.run_result.run_id,
                run.run_result.attempt_id,
            )
            playback = reader.playback(
                run.run_result.run_id,
                run.run_result.attempt_id,
            )
            assert terminal["schema_version"] == "scenarioforge.terminal-evidence/v2"
            assert terminal["playable"] is True
            assert terminal["digests"]["artifact_index"] == _digest(
                published / "artifact_index.json"
            )
            assert playback["trajectory_digest"] == _digest(
                published / "output" / "trajectory.json"
            )
