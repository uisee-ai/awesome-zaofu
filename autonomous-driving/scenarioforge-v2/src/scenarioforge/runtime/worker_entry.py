from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import platform
import stat
from pathlib import Path
from typing import Any

from scenarioforge.core import canonical_bytes, canonical_digest, simulator_fingerprint, strict_loads

from .snapshot import SnapshotError, validate_input_snapshot


ALLOWED_ENVIRONMENT = {"PATH", "LANG", "LC_ALL"}


def _read_object(path: Path) -> dict[str, Any]:
    value = strict_loads(path.read_bytes())
    if not isinstance(value, dict):
        raise SnapshotError(f"{path.name} is not a JSON object")
    return value


def _validate_output_staging(input_snapshot: Path, output_staging: Path) -> None:
    if output_staging.is_symlink() or not output_staging.is_dir():
        raise SnapshotError("OutputStaging is not a regular directory")
    if any(output_staging.iterdir()):
        raise SnapshotError("OutputStaging must be empty for a single-run Worker")
    if os.path.commonpath([input_snapshot.resolve(), output_staging.resolve()]) in {
        str(input_snapshot.resolve()),
        str(output_staging.resolve()),
    }:
        raise SnapshotError("InputSnapshot and OutputStaging overlap")
    mode = output_staging.stat().st_mode
    if not stat.S_ISDIR(mode) or not (mode & stat.S_IWUSR):
        raise SnapshotError("OutputStaging is not owner-writable")


def _write_output(path: Path, value: Any) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        payload = canonical_bytes(value)
        if os.write(descriptor, payload) != len(payload):
            raise RuntimeError(f"short write for {path.name}")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def execute(input_snapshot: Path, output_staging: Path) -> None:
    unexpected_environment = set(os.environ) - ALLOWED_ENVIRONMENT
    if unexpected_environment:
        raise SnapshotError("Worker environment contains non-whitelisted variables")
    snapshot_digest = validate_input_snapshot(input_snapshot)
    _validate_output_staging(input_snapshot, output_staging)

    request = _read_object(input_snapshot / "run_request.json")
    manifest = _read_object(input_snapshot / "run_manifest.json")
    plan = _read_object(input_snapshot / "execution_plan.json")
    assets = _read_object(input_snapshot / "assets.json")
    if request["input_snapshot_digest"] != snapshot_digest:
        raise SnapshotError("Worker received a stale InputSnapshot")
    if manifest["run_id"] != request["run_id"] or manifest["attempt_id"] != request["attempt_id"]:
        raise SnapshotError("run identity binding is invalid")
    if canonical_digest(plan) != request["execution_plan_digest"]:
        raise SnapshotError("execution plan binding is invalid")
    if canonical_digest(assets) != manifest["assets"]["digest"]:
        raise SnapshotError("asset descriptor binding is invalid")
    if platform.system() != manifest["environment"]["os"] or platform.machine() != manifest["environment"]["architecture"]:
        raise SnapshotError("runtime platform does not match the frozen Manifest")
    if platform.python_version() != manifest["python"]["version"]:
        raise SnapshotError("Python version does not match the frozen Manifest")
    for distribution, version in manifest["dependencies"]["resolved"].items():
        if importlib.metadata.version(distribution) != version:
            raise SnapshotError(f"dependency version mismatch: {distribution}")
    if simulator_fingerprint() != manifest["simulator"]:
        raise SnapshotError("MetaDrive distribution or asset digest does not match the Manifest")
    expected_adapter = {
        "id": plan["backend"]["adapter"]["id"],
        "version": plan["backend"]["adapter"]["version"],
    }
    if manifest["adapter"] != {**expected_adapter, "digest": canonical_digest(expected_adapter)}:
        raise SnapshotError("adapter binding is invalid")

    from .adapter import MetaDriveAdapter

    outputs = MetaDriveAdapter(plan).run()
    metrics = outputs["metrics.json"]
    is_v2 = plan["schema_version"] == "scenarioforge.execution-plan/v2"
    road_geometry = outputs.pop("_road_geometry", None)
    worker_result: dict[str, Any] = {
        "schema_version": (
            "scenarioforge.worker-result/v2"
            if is_v2
            else "scenarioforge.worker-result/v1"
        ),
        "run_id": request["run_id"],
        "attempt_id": request["attempt_id"],
        "worker_pid": os.getpid(),
        "backend": {
            "distribution": manifest["simulator"]["distribution"],
            "version": manifest["simulator"]["version"],
            "asset_version": manifest["simulator"]["asset_version"],
            "engine_class": "MultiAgentMetaDrive",
        },
        "execution_plan_digest": request["execution_plan_digest"],
        "completed_steps": metrics["completed_steps"],
        "collision": metrics["collision"],
        "termination_reason": metrics["termination_reason"],
    }
    if is_v2:
        if not isinstance(road_geometry, dict):
            raise RuntimeError("v2 Worker did not capture MetaDrive road geometry")
        worker_result.update(
            {
                "execution_status": metrics["execution_status"],
                "scenario_outcome": metrics["scenario_outcome"],
                "road_geometry": road_geometry,
            }
        )
    else:
        worker_result["status"] = "completed"
    outputs["worker_result.json"] = worker_result
    for name in plan["artifact_contract"]["required"]:
        if name not in outputs:
            raise RuntimeError(f"Worker did not produce required artifact: {name}")
        _write_output(output_staging / name, outputs[name])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scenarioforge.runtime.worker_entry")
    parser.add_argument("--input-snapshot", required=True, type=Path)
    parser.add_argument("--output-staging", required=True, type=Path)
    arguments = parser.parse_args(argv)
    execute(arguments.input_snapshot, arguments.output_staging)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
