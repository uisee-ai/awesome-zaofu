from __future__ import annotations

import argparse
import time
from pathlib import Path

from _common import (
    build_demo,
    bundle_digest,
    elapsed_seconds,
    has_real_provider_provenance,
    prepare_output,
    print_report,
    read_existing_report,
    write_report_once,
)

from scenarioforge.runtime import run_bundle

SCHEMA = "scenarioforge.capacity-benchmark.v1"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the owner-frozen boundary capacity profile")
    parser.add_argument("--profile", choices=["boundary"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    prepare_output(args.output)
    existing = read_existing_report(args.output, SCHEMA)
    if existing is not None:
        print_report(existing)
        return 0 if existing["status"] == "passed" else 1

    _, _, compiled = build_demo(
        profile=args.profile,
        seeds=list(range(100, 116)),
        actors=8,
        workers=2,
        max_steps=12,
    )
    started = time.monotonic()
    outcome = run_bundle(compiled, args.output, run_id="bundle")
    passed = (
        outcome.status == "completed"
        and len(outcome.records) == 16
        and has_real_provider_provenance(outcome.bundle_path)
    )
    report = {
        "schema_version": SCHEMA,
        "command_id": "SFP0-002-CMD-CAPACITY",
        "status": "passed" if passed else "failed",
        "provider": {"distribution": "metadrive-simulator", "version": "0.4.3", "kind": "real"},
        "profile": args.profile,
        "elapsed_seconds": elapsed_seconds(started),
        "limits_contract": {
            "default": {
                "cases": 4,
                "actors": 4,
                "workers": 1,
                "aggregate_cpu_threads": 2,
                "steps": 3000,
                "simulated_seconds": 30,
                "case_wall_seconds": 60,
                "bundle_wall_minutes": 10,
                "bundle_disk_gib": 1,
            },
            "hard": {
                "cases": 16,
                "actors": 8,
                "workers": 2,
                "aggregate_cpu_threads": 4,
                "steps": 10000,
                "simulated_seconds": 60,
                "case_wall_seconds": 120,
                "bundle_wall_minutes": 30,
                "bundle_disk_gib": 2,
            },
        },
        "measured": {
            "cases": len(outcome.records),
            "actors": 8,
            "workers": compiled.limits.workers,
            "aggregate_cpu_threads": compiled.limits.aggregate_cpu_threads,
            "total_steps": sum(record.steps for record in outcome.records),
            "terminal_records": len(outcome.records),
        },
        "bundles": [
            {
                "path": outcome.bundle_path.relative_to(args.output).as_posix(),
                "manifest_digest": bundle_digest(outcome.bundle_path),
                "status": outcome.status,
            }
        ],
    }
    write_report_once(args.output, report)
    print_report(report)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
