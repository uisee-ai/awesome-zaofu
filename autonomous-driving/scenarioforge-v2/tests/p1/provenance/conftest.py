from __future__ import annotations

from pathlib import Path

import pytest

from scenarioforge.provenance import build_execution_snapshot, build_provenance_chain


ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def execution_snapshot():
    return build_execution_snapshot(
        execution_snapshot_id="snapshot-run-0001-attempt-0001",
        normalized_scenario_spec={
            "schema_version": "scenarioforge.scenario/v3",
            "scenario_id": "highway-merge",
            "traffic_side": "right",
            "participants": [{"id": "ego", "role": "ego"}],
        },
        resolved_defaults={
            "schema_version": "scenarioforge.resolved-defaults/v1",
            "values": {"sample_interval_s": 0.1},
        },
        code={"commit": "a" * 40, "digest": "b" * 64},
        adapter={"id": "scenarioforge.smarts", "version": "2.0.1", "digest": "c" * 64},
        simulator={"distribution": "smarts", "version": "2.0.1", "digest": "d" * 64},
        assets=({"id": "sumo-map-highway-merge", "version": "1", "digest": "e" * 64},),
        policy={"id": "scenarioforge.keep-lane", "version": "1.0.0", "digest": "f" * 64},
        seed=17,
        run_parameters={"duration_steps": 100, "warmup_steps": 10},
        environment={
            "schema_version": "scenarioforge.environment/v1",
            "os": "Linux",
            "architecture": "x86_64",
            "lockfile_digest": "1" * 64,
        },
    )


@pytest.fixture
def provenance_chain(execution_snapshot):
    return build_provenance_chain(
        execution_snapshot,
        run_id="run-0001",
        attempt_id="attempt-0001",
        run_manifest={"schema_version": "scenarioforge.run-manifest/v4"},
        compile_report={
            "schema_version": "scenarioforge.compile-report/v4",
            "status": "exact",
        },
        worker_receipt={
            "schema_version": "scenarioforge.worker-receipt/v1",
            "execution_status": "completed",
        },
        artifact_index={
            "schema_version": "scenarioforge.artifact-index/v4",
            "execution_status": "completed",
            "artifacts": [
                {
                    "path": "output/trajectory.json",
                    "status": "present",
                    "digest": "2" * 64,
                    "validation": "verified",
                }
            ],
        },
        terminal_state={
            "schema_version": "scenarioforge.terminal-state/v1",
            "execution_status": "completed",
            "scenario_outcome": "safe_pass",
        },
        trajectory={
            "schema_version": "scenarioforge.trajectory/v1",
            "samples": [],
        },
        replay={
            "schema_version": "scenarioforge.replay-binding/v1",
            "eligible": True,
        },
    )
