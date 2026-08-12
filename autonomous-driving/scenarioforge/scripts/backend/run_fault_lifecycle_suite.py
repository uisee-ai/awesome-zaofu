from __future__ import annotations

import argparse
import time
from pathlib import Path

from _common import (
    build_demo,
    bundle_digest,
    elapsed_seconds,
    prepare_output,
    print_report,
    read_existing_report,
    write_report_once,
)

from scenarioforge.runtime import run_bundle

SCHEMA = "scenarioforge.fault-lifecycle-suite.v1"
EXPECTED = {
    "case_crash": ("partial", ["completed", "crashed", "completed"]),
    "case_timeout": ("partial", ["completed", "timed_out", "completed"]),
    "bundle_cancel": ("cancelled", ["cancelled", "not_run", "not_run"]),
    "bundle_quota": ("aborted", ["aborted", "not_run", "not_run"]),
    "disk_exhaustion": ("aborted", ["aborted", "not_run", "not_run"]),
    "supervisor_failure": ("aborted", ["aborted", "not_run", "not_run"]),
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Exercise the complete fault lifecycle contract")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    prepare_output(args.output)
    existing = read_existing_report(args.output, SCHEMA)
    if existing is not None:
        print_report(existing)
        return 0 if existing["status"] == "passed" else 1

    _, _, compiled = build_demo(
        profile="default",
        seeds=[31, 37, 41],
        actors=2,
        workers=1,
        max_steps=10,
    )
    bundle_root = args.output / "bundles"
    bundle_root.mkdir()
    started = time.monotonic()
    results = []
    passed = True
    for fault, (expected_bundle_status, expected_case_statuses) in EXPECTED.items():
        plan = (
            {0: "success", 1: fault, 2: "success"}
            if fault.startswith("case_")
            else {0: fault, 1: "success", 2: "success"}
        )
        outcome = run_bundle(compiled, bundle_root, run_id=fault, fault_plan=plan)
        case_statuses = [record.status for record in outcome.records]
        case_passed = outcome.status == expected_bundle_status and case_statuses == expected_case_statuses
        passed = passed and case_passed
        results.append(
            {
                "fault": fault,
                "status": "passed" if case_passed else "failed",
                "bundle_status": outcome.status,
                "case_statuses": case_statuses,
                "zero_retries": all(record.retry_count == 0 for record in outcome.records),
                "bundle": {
                    "path": outcome.bundle_path.relative_to(args.output).as_posix(),
                    "manifest_digest": bundle_digest(outcome.bundle_path),
                    "status": outcome.status,
                },
            }
        )
    report = {
        "schema_version": SCHEMA,
        "command_id": "SFP0-002-CMD-FAULTS",
        "status": "passed" if passed else "failed",
        "fault_injection_mode": "controlled-process",
        "elapsed_seconds": elapsed_seconds(started),
        "results": results,
        "bundles": [result["bundle"] for result in results],
    }
    write_report_once(args.output, report)
    print_report(report)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
