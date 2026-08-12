from __future__ import annotations

import argparse
import time
from pathlib import Path

from _common import (
    build_demo,
    bundle_digest,
    canonical_bytes,
    elapsed_seconds,
    has_real_provider_provenance,
    prepare_output,
    print_report,
    read_existing_report,
    write_report_once,
)

from scenarioforge.oracle import calibrate_tolerance, resimulate
from scenarioforge.runtime import run_bundle

SCHEMA = "scenarioforge.tolerance-calibration-report.v1"


def main() -> int:
    parser = argparse.ArgumentParser(description="Calibrate tolerance from repeated real MetaDrive runs")
    parser.add_argument("--runs", type=int, choices=[5], required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    prepare_output(args.output)
    existing = read_existing_report(args.output, SCHEMA)
    if existing is not None:
        print_report(existing)
        return 0 if existing["status"] == "passed" else 1

    scenario, request, compiled = build_demo(
        profile="default",
        seeds=[211],
        actors=2,
        workers=1,
        max_steps=20,
    )
    started = time.monotonic()
    outcomes = [
        run_bundle(compiled, args.output, run_id=f"calibration-{index}")
        for index in range(args.runs)
    ]
    profile = calibrate_tolerance([outcome.bundle_path for outcome in outcomes])
    profile_path = args.output / "tolerance-profile.json"
    profile_path.write_bytes(canonical_bytes(profile.model_dump(mode="json")))
    profile_path.chmod(0o444)
    resimulation = resimulate(outcomes[0].bundle_path, scenario, request, args.output, profile)
    all_outcomes = [*outcomes, resimulation.outcome]
    passed = (
        all(outcome.status == "completed" for outcome in all_outcomes)
        and all(has_real_provider_provenance(outcome.bundle_path) for outcome in all_outcomes)
        and resimulation.report.status == "pass"
    )
    report = {
        "schema_version": SCHEMA,
        "command_id": "SFP0-002-CMD-TOLERANCE",
        "status": "passed" if passed else "failed",
        "provider": {"distribution": "metadrive-simulator", "version": "0.4.3", "kind": "real"},
        "calibration_runs": args.runs,
        "elapsed_seconds": elapsed_seconds(started),
        "profile": profile.model_dump(mode="json"),
        "resimulation": resimulation.report.model_dump(mode="json"),
        "bundles": [
            {
                "path": outcome.bundle_path.relative_to(args.output).as_posix(),
                "manifest_digest": bundle_digest(outcome.bundle_path),
                "status": outcome.status,
            }
            for outcome in all_outcomes
        ],
    }
    write_report_once(args.output, report)
    print_report(report)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
