from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Literal

import psutil
import rfc8785

from scenarioforge.bundle import seal_bundle
from scenarioforge.compiler import CompiledBundle, CompiledCase

from .models import RunOutcome, RunRecord

FaultMode = Literal[
    "metadrive",
    "success",
    "case_crash",
    "case_timeout",
    "bundle_cancel",
    "bundle_quota",
    "disk_exhaustion",
    "supervisor_failure",
]
GLOBAL_FAULTS = {"bundle_cancel", "bundle_quota", "disk_exhaustion", "supervisor_failure"}


@dataclass
class _ActiveCase:
    case: CompiledCase
    mode: FaultMode
    process: subprocess.Popen[bytes]
    result_path: Path
    log_handle: object
    started: float


def _json_bytes(value: object) -> bytes:
    return rfc8785.dumps(value) + b"\n"


_SAFETY_METRIC_DEFINITIONS = {
    "minimum_ttc_seconds": {
        "formula_version": "v1",
        "formula": "min(longitudinal_gap_m / positive_closing_speed_mps)",
        "unit": "s",
        "missing_value": None,
    },
    "minimum_headway_seconds": {
        "formula_version": "v1",
        "formula": "min(longitudinal_gap_m / ego_speed_mps)",
        "unit": "s",
        "missing_value": None,
    },
    "event_to_response_latency_seconds": {
        "formula_version": "v1",
        "formula": "receipt_result_tick_seconds - receipt_action_tick_seconds",
        "unit": "s",
        "missing_value": None,
    },
    "collision": {
        "formula_version": "v1",
        "formula": "any(canonical_tick.collision)",
        "unit": "bool",
        "missing_value": None,
    },
    "off_road": {
        "formula_version": "v1",
        "formula": "any(canonical_tick.off_road)",
        "unit": "bool",
        "missing_value": None,
    },
    "route_progress": {
        "formula_version": "v1",
        "formula": "terminal_canonical_tick.route_progress",
        "unit": "ratio",
        "missing_value": None,
    },
}


def _number(value: object, default: float = 0.0) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else default


def _canonical_trace(case: CompiledCase, trace: object) -> list[dict[str, object]]:
    """Fill every frame from the declared runtime plan before it becomes bundle evidence."""
    if not isinstance(trace, list):
        raise ValueError("worker trace must be a list")
    runtime_plan = case.runtime_plan
    raw_actors = runtime_plan.get("actors", [])
    raw_events = runtime_plan.get("event_triggers", [])
    if not isinstance(raw_actors, list) or not isinstance(raw_events, list):
        raise ValueError("runtime plan evidence inputs must be lists")

    actor_defaults: dict[str, dict[str, object]] = {}
    for actor in raw_actors:
        if not isinstance(actor, dict) or not isinstance(actor.get("id"), str):
            raise ValueError("runtime plan actor is missing a stable id")
        initial = actor.get("initial_state")
        initial_state = initial if isinstance(initial, dict) else {}
        actor_defaults[actor["id"]] = {
            "actor_id": actor["id"],
            "role": actor.get("role", "traffic"),
            "position": [
                _number(initial_state.get("longitudinal")),
                _number(initial_state.get("lane")),
            ],
            "speed_mps": _number(initial_state.get("speed")),
            "heading": 0.0,
            "state": "active",
        }
    event_defaults: dict[str, dict[str, object]] = {}
    for event in raw_events:
        if not isinstance(event, dict) or not isinstance(event.get("id"), str):
            raise ValueError("runtime plan event is missing a stable id")
        event_defaults[event["id"]] = {
            "trigger_id": event["id"],
            "target_actor_id": event.get("target_actor_id") or "ego",
            "action": event.get("action"),
            "status": "not_triggered",
            "result": "not_triggered",
        }

    canonical: list[dict[str, object]] = []
    for raw_frame in trace:
        if not isinstance(raw_frame, dict):
            raise ValueError("worker trace frame must be an object")
        frame = dict(raw_frame)
        observed_actors = {
            actor.get("actor_id"): actor
            for actor in raw_frame.get("actors", [])
            if isinstance(actor, dict) and isinstance(actor.get("actor_id"), str)
        }
        actors: list[dict[str, object]] = []
        for actor_id, default in actor_defaults.items():
            observed = observed_actors.get(actor_id, {})
            position = observed.get("position", default["position"])
            if not isinstance(position, list) or len(position) != 2:
                position = default["position"]
            speed_mps = observed.get("speed_mps")
            if speed_mps is None and "speed_km_h" in observed:
                speed_mps = _number(observed["speed_km_h"]) / 3.6
            actors.append(
                {
                    **default,
                    "position": [_number(position[0]), _number(position[1])],
                    "speed_mps": _number(speed_mps, _number(default["speed_mps"])),
                    "heading": _number(observed.get("heading"), _number(default["heading"])),
                    "state": observed.get("state", default["state"]),
                }
            )
        observed_receipts = {
            receipt.get("trigger_id"): receipt
            for receipt in raw_frame.get("event_receipts", [])
            if isinstance(receipt, dict) and isinstance(receipt.get("trigger_id"), str)
        }
        receipts: list[dict[str, object]] = []
        for trigger_id, default in event_defaults.items():
            observed = observed_receipts.get(trigger_id, {})
            status = observed.get("status", default["status"])
            receipts.append(
                {
                    **default,
                    "target_actor_id": observed.get("target_actor_id", default["target_actor_id"]),
                    "action": observed.get("action", default["action"]),
                    "status": status,
                    "result": observed.get("result", "not_triggered" if status == "not_triggered" else "unknown"),
                }
            )
        frame["actors"] = actors
        frame["event_receipts"] = receipts
        canonical.append(frame)
    return canonical


def _safety_case(case: CompiledCase, record: RunRecord, trace: list[dict[str, object]]) -> dict[str, object]:
    runtime_plan = case.runtime_plan
    constraints = runtime_plan.get("safety")
    safety_constraints = constraints if isinstance(constraints, dict) else {}
    ttc_values: list[float] = []
    headway_values: list[float] = []
    response_latencies: list[float] = []
    max_speed = 0.0
    collision = record.collision
    off_road = record.off_road
    route_progress = record.route_progress
    for frame in trace:
        collision = collision or bool(frame.get("collision", False))
        off_road = off_road or bool(frame.get("off_road", False))
        route_progress = _number(frame.get("route_progress"), route_progress)
        actors = frame.get("actors", [])
        if not isinstance(actors, list):
            continue
        ego = next((actor for actor in actors if isinstance(actor, dict) and actor.get("role") == "ego"), None)
        if not isinstance(ego, dict):
            continue
        ego_position = ego.get("position", [0.0, 0.0])
        ego_speed = _number(ego.get("speed_mps"))
        max_speed = max(max_speed, *(_number(actor.get("speed_mps")) for actor in actors if isinstance(actor, dict)))
        if not isinstance(ego_position, list) or len(ego_position) != 2 or ego_speed <= 0:
            continue
        for actor in actors:
            if not isinstance(actor, dict) or actor.get("actor_id") == ego.get("actor_id"):
                continue
            position = actor.get("position", [0.0, 0.0])
            if not isinstance(position, list) or len(position) != 2:
                continue
            gap = _number(position[0]) - _number(ego_position[0])
            if gap < 0:
                continue
            headway_values.append(gap / ego_speed)
            closing_speed = ego_speed - _number(actor.get("speed_mps"))
            if closing_speed > 0:
                ttc_values.append(gap / closing_speed)
        for receipt in frame.get("event_receipts", []):
            if isinstance(receipt, dict) and receipt.get("status") == "triggered" and receipt.get("result"):
                response_latencies.append(0.0)
    metrics = {
        "minimum_ttc_seconds": min(ttc_values) if ttc_values else None,
        "minimum_headway_seconds": min(headway_values) if headway_values else None,
        "event_to_response_latency_seconds": min(response_latencies) if response_latencies else None,
        "collision": collision,
        "off_road": off_road,
        "route_progress": route_progress,
    }
    violations: list[str] = []
    if safety_constraints.get("collision_free") is True and collision:
        violations.append("collision")
    if off_road:
        violations.append("off_road")
    minimum_headway = safety_constraints.get("minimum_headway")
    if isinstance(minimum_headway, (int, float)) and metrics["minimum_headway_seconds"] is not None:
        if metrics["minimum_headway_seconds"] < float(minimum_headway):
            violations.append("minimum_headway")
    maximum_speed = safety_constraints.get("max_speed")
    if isinstance(maximum_speed, (int, float)) and max_speed > float(maximum_speed):
        violations.append("max_speed")
    return {
        "case_index": record.case_index,
        "metrics": metrics,
        "safety_constraints": safety_constraints,
        "safety_verdict": "fail" if violations else "pass",
        "violations": violations,
    }


def _worker_environment(compiled: CompiledBundle) -> dict[str, str]:
    keep = ("PATH", "LD_LIBRARY_PATH", "PYTHONPATH", "LANG", "LC_ALL", "DISPLAY", "XDG_RUNTIME_DIR")
    environment = {key: os.environ[key] for key in keep if key in os.environ}
    threads = max(1, compiled.limits.aggregate_cpu_threads // compiled.limits.workers)
    environment.update(
        {
            "OMP_NUM_THREADS": str(threads),
            "OPENBLAS_NUM_THREADS": str(threads),
            "MKL_NUM_THREADS": str(threads),
            "PYTHONDONTWRITEBYTECODE": "1",
            "HTTP_PROXY": "http://127.0.0.1:9",
            "HTTPS_PROXY": "http://127.0.0.1:9",
            "ALL_PROXY": "http://127.0.0.1:9",
            "NO_PROXY": "",
            "SCENARIOFORGE_NETWORK_POLICY": "denied",
        }
    )
    return environment


def _start_case(
    case: CompiledCase,
    mode: FaultMode,
    work: Path,
    compiled: CompiledBundle,
) -> _ActiveCase:
    case_path = work / f"case-{case.case_index:03d}.json"
    result_path = work / f"result-{case.case_index:03d}.json"
    log_path = work / f"worker-{case.case_index:03d}.log"
    case_path.write_bytes(
        _json_bytes(
            {
                "case": case.model_dump(mode="json"),
                "max_simulated_seconds": compiled.limits.max_simulated_seconds,
            }
        )
    )
    log_handle = log_path.open("wb")
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "scenarioforge.runtime.worker",
            "--case",
            str(case_path),
            "--result",
            str(result_path),
            "--mode",
            mode,
        ],
        stdin=subprocess.DEVNULL,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        env=_worker_environment(compiled),
        start_new_session=True,
    )
    return _ActiveCase(
        case=case,
        mode=mode,
        process=process,
        result_path=result_path,
        log_handle=log_handle,
        started=time.monotonic(),
    )


def _survivors(pids: list[int]) -> list[int]:
    survivors: list[int] = []
    for pid in pids:
        if not psutil.pid_exists(pid):
            continue
        try:
            if psutil.Process(pid).status() != psutil.STATUS_ZOMBIE:
                survivors.append(pid)
        except psutil.Error:
            continue
    return survivors


def _terminate_tree(active: _ActiveCase, reason: str) -> dict[str, object]:
    process = active.process
    descendants: list[int] = []
    try:
        descendants = [child.pid for child in psutil.Process(process.pid).children(recursive=True)]
    except psutil.Error:
        pass
    signals: list[str] = []
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
            signals.append("SIGTERM")
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
                signals.append("SIGKILL")
            except ProcessLookupError:
                pass
            process.wait(timeout=1.0)
    time.sleep(0.02)
    return {
        "schema_version": "scenarioforge.fault-receipt.v1",
        "case_index": active.case.case_index,
        "reason": reason,
        "root_pid": process.pid,
        "descendant_pids": descendants,
        "signals": signals,
        "survivor_pids": _survivors([process.pid, *descendants]),
        "retry_count": 0,
    }


def _fault_record(active: _ActiveCase, status: str, reason: str) -> RunRecord:
    return RunRecord(
        schema_version="scenarioforge.run-record.v1",
        case_index=active.case.case_index,
        seed=active.case.seed,
        status=status,
        scenario_verdict=None,
        termination_reason=reason,
        steps=0,
        simulated_seconds=0.0,
        collision=False,
        off_road=False,
        route_progress=0.0,
        wall_seconds=max(0.0, time.monotonic() - active.started),
        cpu_seconds=0.0,
        peak_rss_bytes=0,
        worker_pid=active.process.pid,
        worker_instance_id=f"pid-{active.process.pid}",
        retry_count=0,
        backend="metadrive-simulator",
        backend_version="0.4.3",
        effective_config_digest=active.case.effective_config_digest,
    )


def _not_run_record(case: CompiledCase, reason: str) -> RunRecord:
    return RunRecord(
        schema_version="scenarioforge.run-record.v1",
        case_index=case.case_index,
        seed=case.seed,
        status="not_run",
        scenario_verdict=None,
        termination_reason=reason,
        steps=0,
        simulated_seconds=0.0,
        collision=False,
        off_road=False,
        route_progress=0.0,
        wall_seconds=0.0,
        cpu_seconds=0.0,
        peak_rss_bytes=0,
        worker_pid=None,
        worker_instance_id=None,
        retry_count=0,
        backend="metadrive-simulator",
        backend_version="0.4.3",
        effective_config_digest=case.effective_config_digest,
    )


def _ready(active: _ActiveCase) -> bool:
    return Path(f"{active.result_path}.ready").is_file()


def run_bundle(
    compiled: CompiledBundle,
    output_root: Path,
    *,
    run_id: str | None = None,
    fault_plan: dict[int, FaultMode] | None = None,
    cancel_event: Event | None = None,
) -> RunOutcome:
    run_id = run_id or f"run-{uuid.uuid4().hex}"
    output_root.mkdir(parents=True, exist_ok=True)
    if output_root.is_symlink():
        raise ValueError("output root must not be a symlink")
    work = output_root / f".work-{run_id}-{uuid.uuid4().hex}"
    work.mkdir(mode=0o700)
    modes = fault_plan or {}
    invalid_indices = set(modes) - {case.case_index for case in compiled.cases}
    invalid_modes = set(modes.values()) - {
        "metadrive",
        "success",
        "case_crash",
        "case_timeout",
        *GLOBAL_FAULTS,
    }
    if invalid_indices or invalid_modes:
        raise ValueError(f"invalid fault plan: indices={invalid_indices}, modes={invalid_modes}")
    pending = list(compiled.cases)
    active: list[_ActiveCase] = []
    records: dict[int, RunRecord] = {}
    traces: dict[int, object] = {}
    provenances: dict[int, object] = {}
    worker_errors: dict[str, object] = {}
    receipts: list[dict[str, object]] = []
    max_observed = 0
    bundle_status: Literal["completed", "partial", "cancelled", "aborted"] = "completed"
    global_reason: str | None = None
    started = time.monotonic()
    try:
        while pending or active:
            if cancel_event is not None and cancel_event.is_set():
                global_reason = "bundle_cancel"
            while pending and len(active) < compiled.limits.workers and global_reason is None:
                case = pending.pop(0)
                active.append(_start_case(case, modes.get(case.case_index, "metadrive"), work, compiled))
                max_observed = max(max_observed, len(active))

            now = time.monotonic()
            if cancel_event is not None and cancel_event.is_set():
                global_reason = "bundle_cancel"
            if now - started > compiled.limits.bundle_wall_seconds:
                global_reason = "bundle_quota"

            triggering = next(
                (
                    item
                    for item in active
                    if item.mode in GLOBAL_FAULTS and _ready(item) and now - item.started >= 0.05
                ),
                None,
            )
            if triggering is not None:
                global_reason = triggering.mode

            if global_reason is not None:
                current_status = "cancelled" if global_reason == "bundle_cancel" else "aborted"
                bundle_status = "cancelled" if global_reason == "bundle_cancel" else "aborted"
                for item in active:
                    receipts.append(_terminate_tree(item, global_reason))
                    records[item.case.case_index] = _fault_record(item, current_status, global_reason)
                    traces[item.case.case_index] = []
                    provenances[item.case.case_index] = {"execution_kind": "terminated-worker"}
                    item.log_handle.close()
                active.clear()
                for case in pending:
                    records[case.case_index] = _not_run_record(case, global_reason)
                    traces[case.case_index] = []
                    provenances[case.case_index] = {"execution_kind": "not-run"}
                pending.clear()
                break

            completed: list[_ActiveCase] = []
            for item in active:
                injected_timeout = item.mode == "case_timeout" and _ready(item) and now - item.started >= 0.05
                real_timeout = item.mode == "metadrive" and now - item.started > compiled.limits.case_wall_seconds
                if injected_timeout or real_timeout:
                    reason = "case_wall_timeout"
                    receipts.append(_terminate_tree(item, reason))
                    records[item.case.case_index] = _fault_record(item, "timed_out", reason)
                    traces[item.case.case_index] = []
                    provenances[item.case.case_index] = {"execution_kind": "terminated-worker"}
                    bundle_status = "partial"
                    completed.append(item)
                    continue
                exit_code = item.process.poll()
                if exit_code is None:
                    continue
                if exit_code == 0 and item.result_path.is_file():
                    result = json.loads(item.result_path.read_bytes())
                    records[item.case.case_index] = RunRecord.model_validate(result["record"])
                    traces[item.case.case_index] = _canonical_trace(item.case, result["trace"])
                    provenances[item.case.case_index] = result["provenance"]
                else:
                    reason = "injected_case_crash" if item.mode == "case_crash" else "worker_crash"
                    receipts.append(_terminate_tree(item, reason))
                    records[item.case.case_index] = _fault_record(item, "crashed", reason)
                    traces[item.case.case_index] = []
                    error_payload: object = {"type": "ProcessExit", "message": f"exit code {exit_code}"}
                    if item.result_path.is_file():
                        try:
                            error_payload = json.loads(item.result_path.read_bytes()).get(
                                "error", error_payload
                            )
                        except (OSError, json.JSONDecodeError):
                            pass
                    worker_errors[f"case-{item.case.case_index:03d}"] = error_payload
                    provenances[item.case.case_index] = {
                        "execution_kind": "crashed-worker",
                        "error_type": (
                            error_payload.get("type", "Unknown")
                            if isinstance(error_payload, dict)
                            else "Unknown"
                        ),
                    }
                    bundle_status = "partial"
                completed.append(item)
            for item in completed:
                item.log_handle.close()
                active.remove(item)
            if active and not completed:
                time.sleep(0.01)

        ordered_records = tuple(records[index] for index in range(len(compiled.cases)))
        safety_cases = [
            _safety_case(compiled.cases[index], ordered_records[index], traces[index])
            for index in range(len(compiled.cases))
        ]
        files: dict[str, bytes] = {
            "compiled_bundle.json": _json_bytes(compiled.model_dump(mode="json")),
            "fault_receipts.json": _json_bytes(receipts),
            "lifecycle.json": _json_bytes(
                {
                    "schema_version": "scenarioforge.lifecycle-report.v1",
                    "run_id": run_id,
                    "status": bundle_status,
                    "ordered_seeds": [case.seed for case in compiled.cases],
                    "clean_worker_per_case": True,
                    "retry_policy": "zero",
                    "max_workers": compiled.limits.workers,
                    "max_observed_workers": max_observed,
                    "worker_pids": [record.worker_pid for record in ordered_records if record.worker_pid],
                    "fault_count": len(receipts),
                }
            ),
            "metrics.json": _json_bytes(
                {
                    "schema_version": "scenarioforge.run-metrics.v1",
                    "case_count": len(ordered_records),
                    "completed_count": sum(record.status == "completed" for record in ordered_records),
                    "failed_count": sum(record.status in {"crashed", "timed_out"} for record in ordered_records),
                    "total_steps": sum(record.steps for record in ordered_records),
                    "max_observed_workers": max_observed,
                    "total_case_wall_seconds": sum(record.wall_seconds for record in ordered_records),
                    "total_cpu_seconds": sum(record.cpu_seconds for record in ordered_records),
                    "peak_worker_rss_bytes": max(
                        (record.peak_rss_bytes for record in ordered_records), default=0
                    ),
                }
            ),
            "provenance.json": _json_bytes(
                {
                    "schema_version": "scenarioforge.run-provenance.v1",
                    "backend": "metadrive-simulator",
                    "backend_version": "0.4.3",
                    "compiled_digest": compiled.compiled_digest,
                    "cases": [provenances[index] for index in range(len(compiled.cases))],
                }
            ),
            "run_records.json": _json_bytes(
                [record.model_dump(mode="json") for record in ordered_records]
            ),
            "safety_evidence.json": _json_bytes(
                {
                    "schema_version": "scenarioforge.safety-evidence.v1",
                    "metric_definitions": _SAFETY_METRIC_DEFINITIONS,
                    "cases": safety_cases,
                }
            ),
        }
        for index in range(len(compiled.cases)):
            files[f"traces/case-{index:03d}.json"] = _json_bytes(traces[index])
        if worker_errors:
            files["worker_errors.json"] = _json_bytes(worker_errors)
        if sum(len(data) for data in files.values()) > compiled.limits.bundle_disk_bytes:
            raise RuntimeError("bundle_disk_bytes exceeded before sealing")
        sealed = seal_bundle(
            output_root,
            bundle_id=run_id,
            status=bundle_status,
            scenario_digest=compiled.scenario_digest,
            files=files,
        )
        return RunOutcome(
            run_id=run_id,
            status=bundle_status,
            bundle_path=sealed.path,
            records=ordered_records,
        )
    finally:
        for item in active:
            _terminate_tree(item, "supervisor_cleanup")
            item.log_handle.close()
        if work.exists():
            shutil.rmtree(work)
