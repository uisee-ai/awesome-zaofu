from __future__ import annotations

import json
from pathlib import Path

import pytest

from scenarioforge.bundle import load_bundle_json, verify_bundle
from scenarioforge.compiler import compile_scenario
from scenarioforge.runtime import JobManager, RuntimePreflightError, check_metadrive_runtime, run_bundle
from scenarioforge.spec import RunRequest, canonical_scenario, load_scenario


def _compiled_bundle(
    scenario_payload: dict[str, object],
    run_request_payload: dict[str, object],
    *,
    seeds: list[int],
    workers: int = 1,
):
    scenario = load_scenario(json.dumps(scenario_payload), "application/json")
    request_payload = {**run_request_payload}
    request_payload["limits"] = {**run_request_payload["limits"]}
    request_payload["scenario_digest"] = canonical_scenario(scenario).digest
    request_payload["seeds"] = seeds
    if workers == 2:
        request_payload["profile"] = "boundary"
        request_payload["limits"]["workers"] = 2
        request_payload["limits"]["aggregate_cpu_threads"] = 4
    request = RunRequest.model_validate(request_payload)
    return compile_scenario(scenario, request)


def test_each_ordered_seed_runs_once_in_a_fresh_process_and_seals_complete_bundle(
    tmp_path: Path,
    scenario_payload: dict[str, object],
    run_request_payload: dict[str, object],
) -> None:
    compiled = _compiled_bundle(scenario_payload, run_request_payload, seeds=[17, 23, 29], workers=2)

    outcome = run_bundle(
        compiled,
        tmp_path,
        run_id="run-success",
        fault_plan={0: "success", 1: "success", 2: "success"},
    )

    assert outcome.status == "completed"
    assert [record.seed for record in outcome.records] == [17, 23, 29]
    assert [record.status for record in outcome.records] == ["completed", "completed", "completed"]
    assert len({record.worker_pid for record in outcome.records}) == 3
    assert all(record.retry_count == 0 for record in outcome.records)
    assert all(record.backend == "metadrive-simulator" for record in outcome.records)
    assert all(record.backend_version == "0.4.3" for record in outcome.records)
    assert set(outcome.records[0].model_dump(mode="json")) == {
        "schema_version",
        "case_index",
        "seed",
        "status",
        "scenario_verdict",
        "termination_reason",
        "steps",
        "simulated_seconds",
        "collision",
        "off_road",
        "route_progress",
        "wall_seconds",
        "cpu_seconds",
        "peak_rss_bytes",
        "worker_pid",
        "worker_instance_id",
        "retry_count",
        "backend",
        "backend_version",
        "effective_config_digest",
    }

    manifest = verify_bundle(outcome.bundle_path)
    assert [artifact.path for artifact in manifest.artifacts] == [
        "compiled_bundle.json",
        "fault_receipts.json",
        "lifecycle.json",
        "metrics.json",
        "provenance.json",
        "run_records.json",
        "safety_evidence.json",
        "traces/case-000.json",
        "traces/case-001.json",
        "traces/case-002.json",
    ]
    lifecycle = load_bundle_json(outcome.bundle_path, "lifecycle.json")
    assert lifecycle == {
        "schema_version": "scenarioforge.lifecycle-report.v1",
        "run_id": "run-success",
        "status": "completed",
        "ordered_seeds": [17, 23, 29],
        "clean_worker_per_case": True,
        "retry_policy": "zero",
        "max_workers": 2,
        "max_observed_workers": 2,
        "worker_pids": [record.worker_pid for record in outcome.records],
        "fault_count": 0,
    }


@pytest.mark.parametrize(
    ("fault", "failed_status", "termination_reason"),
    [
        ("case_crash", "crashed", "injected_case_crash"),
        ("case_timeout", "timed_out", "case_wall_timeout"),
    ],
)
def test_case_local_fault_preserves_completed_cases_and_continues_in_clean_worker(
    tmp_path: Path,
    scenario_payload: dict[str, object],
    run_request_payload: dict[str, object],
    fault: str,
    failed_status: str,
    termination_reason: str,
) -> None:
    compiled = _compiled_bundle(scenario_payload, run_request_payload, seeds=[31, 37, 41])

    outcome = run_bundle(
        compiled,
        tmp_path,
        run_id=f"run-{fault}",
        fault_plan={0: "success", 1: fault, 2: "success"},
    )

    assert outcome.status == "partial"
    assert [record.status for record in outcome.records] == ["completed", failed_status, "completed"]
    assert outcome.records[1].termination_reason == termination_reason
    assert len({record.worker_pid for record in outcome.records}) == 3
    assert all(record.retry_count == 0 for record in outcome.records)
    receipts = load_bundle_json(outcome.bundle_path, "fault_receipts.json")
    assert receipts[0]["case_index"] == 1
    assert receipts[0]["reason"] == termination_reason
    assert receipts[0]["survivor_pids"] == []
    if fault == "case_timeout":
        assert receipts[0]["descendant_pids"]


@pytest.mark.parametrize(
    ("fault", "bundle_status", "current_status"),
    [
        ("bundle_cancel", "cancelled", "cancelled"),
        ("bundle_quota", "aborted", "aborted"),
        ("disk_exhaustion", "aborted", "aborted"),
        ("supervisor_failure", "aborted", "aborted"),
    ],
)
def test_bundle_global_fault_kills_process_tree_and_stops_every_remaining_case(
    tmp_path: Path,
    scenario_payload: dict[str, object],
    run_request_payload: dict[str, object],
    fault: str,
    bundle_status: str,
    current_status: str,
) -> None:
    compiled = _compiled_bundle(scenario_payload, run_request_payload, seeds=[43, 47, 53])

    outcome = run_bundle(
        compiled,
        tmp_path,
        run_id=f"run-{fault}",
        fault_plan={0: fault, 1: "success", 2: "success"},
    )

    assert outcome.status == bundle_status
    assert [record.status for record in outcome.records] == [current_status, "not_run", "not_run"]
    assert [record.termination_reason for record in outcome.records] == [fault, fault, fault]
    assert all(record.retry_count == 0 for record in outcome.records)
    receipt = load_bundle_json(outcome.bundle_path, "fault_receipts.json")[0]
    assert receipt["reason"] == fault
    assert receipt["root_pid"] == outcome.records[0].worker_pid
    assert receipt["descendant_pids"]
    assert receipt["survivor_pids"] == []


def test_missing_or_wrong_version_assets_fail_before_metadrive_import_or_network(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing-assets"
    wrong = tmp_path / "wrong-assets"
    wrong.mkdir()
    (wrong / "version.txt").write_text("0.4.2\n", encoding="utf-8")

    with pytest.raises(RuntimePreflightError) as missing_error:
        check_metadrive_runtime(asset_root=missing)
    with pytest.raises(RuntimePreflightError) as wrong_error:
        check_metadrive_runtime(asset_root=wrong)

    assert missing_error.value.code == "assets_missing"
    assert wrong_error.value.code == "assets_version_mismatch"
    assert missing_error.value.network_attempted is False
    assert wrong_error.value.network_attempted is False


def test_job_manager_exposes_async_lifecycle_and_cancellation_bundle(
    tmp_path: Path,
    scenario_payload: dict[str, object],
    run_request_payload: dict[str, object],
) -> None:
    compiled = _compiled_bundle(scenario_payload, run_request_payload, seeds=[61, 67])
    manager = JobManager()

    accepted = manager.submit(
        compiled,
        tmp_path,
        job_id="job-cancelled",
        fault_plan={0: "case_timeout", 1: "success"},
    )
    assert accepted.status in {"queued", "running"}
    assert accepted.bundle_path is None
    assert accepted.retry_count == 0

    cancelled = manager.cancel("job-cancelled")
    assert cancelled.cancel_requested is True
    terminal = manager.wait("job-cancelled", timeout_seconds=5.0)

    assert terminal.status == "cancelled"
    assert terminal.bundle_path is not None
    assert terminal.error is None
    outcome = manager.outcome("job-cancelled")
    assert outcome is not None
    assert all(record.status in {"cancelled", "not_run"} for record in outcome.records)
    assert all(record.retry_count == 0 for record in outcome.records)
    assert load_bundle_json(Path(terminal.bundle_path), "lifecycle.json")["status"] == "cancelled"
