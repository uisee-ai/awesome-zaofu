from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from scenarioforge.core import (
    EnvironmentFingerprint,
    ScenarioCompiler,
    canonical_bytes,
    canonical_digest,
    instantiate_scenario,
    load_scenario,
    strict_loads,
)
from scenarioforge.runtime.artifact_publish import publish_success
from scenarioforge.runtime.snapshot import prepare_run

ROOT = Path(__file__).resolve().parents[3]
SCENARIO = ROOT / "examples" / "p0c" / "dangerous_cut_in.json"


def read_json(path: Path) -> Any:
    return strict_loads(path.read_bytes())


def write_json(path: Path, value: Any) -> None:
    path.chmod(0o600)
    path.write_bytes(canonical_bytes(value))


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resign_controls(published: Path, index: dict[str, Any]) -> None:
    index_path = published / "artifact_index.json"
    result_path = published / "run_result.json"
    marker_path = published / "SUCCESS"
    write_json(index_path, index)
    result = read_json(result_path)
    result["artifact_index_digest"] = canonical_digest(index)
    write_json(result_path, result)
    marker = read_json(marker_path)
    marker["artifact_index_digest"] = _digest(index_path)
    marker["run_result_digest"] = _digest(result_path)
    write_json(marker_path, marker)


def rewrite_artifact(
    published: Path,
    relative: str,
    transform: Callable[[Any], Any],
) -> None:
    artifact = published.joinpath(*relative.split("/"))
    write_json(artifact, transform(read_json(artifact)))
    rewrite_index_entry(published, relative)


def rewrite_raw_artifact(published: Path, relative: str, payload: bytes) -> None:
    artifact = published.joinpath(*relative.split("/"))
    artifact.chmod(0o600)
    artifact.write_bytes(payload)
    rewrite_index_entry(published, relative)


def rewrite_index_entry(published: Path, relative: str) -> None:
    artifact = published.joinpath(*relative.split("/"))
    index = read_json(published / "artifact_index.json")
    entry = next(item for item in index["artifacts"] if item["path"] == relative)
    entry["size_bytes"] = artifact.stat().st_size
    entry["digest"] = _digest(artifact)
    resign_controls(published, index)


@pytest.fixture
def v2_publication(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    fingerprint = EnvironmentFingerprint(
        schema_version="scenarioforge.environment-fingerprint/v1",
        os="Linux",
        architecture="x86_64",
        python={"implementation": "CPython", "version": "3.11.15"},
        simulator={
            "distribution": "metadrive-simulator",
            "version": "0.4.3",
            "asset_version": "0.4.3",
            "asset_digest": "a" * 64,
        },
        rendering={"headless": True, "gpu_required": False},
        dependency_lock={"format": "uv.lock", "digest": "b" * 64},
    )
    monkeypatch.setattr(
        "scenarioforge.runtime.snapshot.environment_fingerprint",
        lambda _lockfile: fingerprint,
    )
    monkeypatch.setattr(
        "scenarioforge.runtime.snapshot.importlib.metadata.version",
        lambda name: {
            "jsonschema": "4.25.1",
            "metadrive-simulator": "0.4.3",
        }[name],
    )
    bundle = ScenarioCompiler().compile(instantiate_scenario(load_scenario(SCENARIO)))
    prepared = prepare_run(
        bundle,
        workspace=tmp_path,
        project_root=ROOT,
        run_id="run-v2-evidence",
        attempt_id="attempt-0001",
    )
    plan = bundle.execution_plan
    assert plan is not None
    plan_value = plan.to_dict()
    participants = plan_value["participants"]

    trajectory: list[dict[str, Any]] = []
    lane_by_participant = {"ego": "ego-lane", "cutter": "adjacent-lane"}
    route_by_participant = {"ego": "ego-mainline", "cutter": "cutter-cut-in"}
    for tick in range(13):
        for participant in participants:
            participant_id = participant["id"]
            lane_id = lane_by_participant[participant_id]
            lane_index = 1 if participant_id == "ego" else 0
            trajectory.append(
                {
                    "schema_version": "scenarioforge.trajectory-point/v2",
                    "tick": tick,
                    "participant_id": participant_id,
                    "position_m": [float(20 + tick), float(lane_index) * 3.5],
                    "speed_mps": 21.0,
                    "heading_deg": 0.0,
                    "collision": tick == 12,
                    "lane_id": lane_id,
                    "engine_lane_index": [">>", ">>>", lane_index],
                    "lane_longitudinal_m": float(20 + tick),
                    "route_id": route_by_participant[participant_id],
                    "route_destination_lane_id": "ego-lane",
                    "route_destination_engine_lane_index": [">>", ">>>", 1],
                    "route_destination_matches": True,
                    "route_checkpoints": [">>", ">>>"],
                    "route_completed": False,
                    "boundary_violation": False,
                    "wrong_route": False,
                }
            )

    events = [
        {
            "schema_version": "scenarioforge.event/v2",
            "event_id": event["id"],
            "sequence": event["sequence"],
            "type": "trigger_fired",
            "participant_id": event["participant_id"],
            "trigger_tick": event["trigger"]["tick"],
            "effect_state_tick": event["trigger"]["tick"] + 1,
            "priority_contract": "scenarioforge.trigger-priority/v2",
            "action": {
                "steering": event["action"]["steering"],
                "throttle_brake": event["action"]["throttle_brake"],
            },
        }
        for event in plan_value["events"]
    ]
    definitions = plan_value["constraints"]["metric_definitions"]
    raw_by_metric = {
        "collision": True,
        "hard_braking": -7.0,
        "minimum_ttc": 0.5,
        "completion_time": None,
        "termination_reason": "collision",
    }
    values = [
        {
            **definition,
            "value": raw_by_metric[definition["metric"]],
            "raw_evidence_value": raw_by_metric[definition["metric"]],
            "threshold_met": None,
        }
        for definition in definitions
    ]
    terminal = {
        "execution_status": "completed",
        "scenario_outcome": "collision_failure",
        "termination_reason": "collision",
    }
    road_geometry = {
        "schema_version": "scenarioforge.road-geometry/v1",
        "coordinate_system": "right-handed-x-forward-y-left",
        "source": "metadrive-road-network",
        "lanes": [
            {
                "lane_id": "adjacent-lane",
                "kind": "travel",
                "centerline_m": [[0.0, 0.0], [220.0, 0.0]],
                "left_boundary_m": [[0.0, 1.75], [220.0, 1.75]],
                "right_boundary_m": [[0.0, -1.75], [220.0, -1.75]],
            },
            {
                "lane_id": "ego-lane",
                "kind": "merge",
                "centerline_m": [[0.0, 3.5], [220.0, 3.5]],
                "left_boundary_m": [[0.0, 5.25], [220.0, 5.25]],
                "right_boundary_m": [[0.0, 1.75], [220.0, 1.75]],
            },
        ],
        "conflict_zones": [
            {
                "zone_id": "cut-in-conflict",
                "start_m": 35.0,
                "end_m": 80.0,
                "lane_regions": [
                    {
                        "lane_id": "adjacent-lane",
                        "left_boundary_m": [[35.0, 1.75], [80.0, 1.75]],
                        "right_boundary_m": [[35.0, -1.75], [80.0, -1.75]],
                    },
                    {
                        "lane_id": "ego-lane",
                        "left_boundary_m": [[35.0, 5.25], [80.0, 5.25]],
                        "right_boundary_m": [[35.0, 1.75], [80.0, 1.75]],
                    },
                ],
            }
        ],
    }
    metrics = {
        "schema_version": "scenarioforge.metrics/v2",
        **terminal,
        "target_scenario_outcome": "collision_failure",
        "target_outcome_match": True,
        "collision": True,
        "collision_participants": ["cutter", "ego"],
        "min_ttc_s": 0.5,
        "minimum_acceleration_mps2": -7.0,
        "completion_time_s": None,
        "completed_steps": 12,
        "sample_interval_s": 0.1,
        "predicate_results": {
            "success": [
                {
                    "predicate_id": "routes-completed",
                    "kind": "route_completed",
                    "satisfied": False,
                }
            ],
            "failure": [
                {
                    "predicate_id": "collision-observed",
                    "kind": "collision",
                    "satisfied": True,
                },
                {
                    "predicate_id": "cutter-boundary-violation",
                    "kind": "boundary_violation",
                    "satisfied": False,
                },
                {
                    "predicate_id": "route-timeout",
                    "kind": "timeout",
                    "satisfied": False,
                },
            ],
        },
        "metric_definitions": definitions,
        "metric_values": values,
    }
    worker_result = {
        "schema_version": "scenarioforge.worker-result/v2",
        "run_id": "run-v2-evidence",
        "attempt_id": "attempt-0001",
        "worker_pid": 4321,
        "backend": {
            "distribution": "metadrive-simulator",
            "version": "0.4.3",
            "asset_version": "0.4.3",
            "engine_class": "MultiAgentMetaDrive",
        },
        "execution_plan_digest": prepared.run_request.execution_plan_digest,
        "completed_steps": 12,
        "collision": True,
        "road_geometry": road_geometry,
        **terminal,
    }
    outputs = {
        "actions.json": [],
        "events.json": events,
        "metrics.json": metrics,
        "trajectory.json": trajectory,
        "worker_result.json": worker_result,
    }
    for name, value in outputs.items():
        (prepared.output_staging_path / name).write_bytes(canonical_bytes(value))
    publish_success(prepared, worker_exit_code=0)
    return prepared.published_path
