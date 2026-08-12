from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src"
for import_root in (PROJECT_ROOT, SRC_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from scenarioforge.bundle import verify_bundle  # noqa: E402
from scenarioforge.runtime import (  # noqa: E402
    RuntimePreflightError,
    check_metadrive_runtime,
)


SCENARIO = {
    "schema_version": "scenarioforge.scenario-spec.v1",
    "name": "clean-install-offline-release",
    "map": {"block_sequence": "S", "lane_count": 2, "lane_width": 3.5},
    "actors": [{"id": "ego", "role": "ego"}],
    "environment": {"traffic_density": 0.0},
    "tags": ["clean-install", "offline", "real-provider"],
}


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _request(url: str, headers: dict[str, str], payload: dict[str, Any] | None = None) -> Any:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method="GET" if data is None else "POST")
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def _wait_for(url: str, process: subprocess.Popen[bytes], headers: dict[str, str]) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"offline release entrypoint exited: {process.returncode}")
        try:
            status, _ = _request(url, headers)
            if status == 200:
                return
        except (OSError, TimeoutError):
            pass
        time.sleep(0.1)
    raise RuntimeError("offline release entrypoint did not become ready")


def _stop(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=10)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)


def run(output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=False)
    missing_root = output / "missing-assets"
    before = Path(os.environ["SCENARIOFORGE_NETWORK_ATTEMPT_LOG"]).stat().st_size
    try:
        check_metadrive_runtime(asset_root=missing_root)
    except RuntimePreflightError as error:
        missing = {
            "status": "rejected_before_execution",
            "code": error.code,
            "network_attempted": error.network_attempted,
        }
    else:
        raise RuntimeError("missing assets were not rejected")
    after = Path(os.environ["SCENARIOFORGE_NETWORK_ATTEMPT_LOG"]).stat().st_size
    if before != after or missing != {
        "status": "rejected_before_execution",
        "code": "assets_missing",
        "network_attempted": False,
    }:
        raise RuntimeError("missing assets did not fail closed before network or execution")

    runtime = check_metadrive_runtime()
    asset_lock = PROJECT_ROOT / "config/metadrive-assets.lock.json"
    port = _free_port()
    origin = f"http://127.0.0.1:{port}"
    capability = "offline-release-capability-4675"
    csrf = "offline-release-csrf-9134"
    runs = output / "runs"
    environment = os.environ.copy()
    environment.update(
        {
            "SCENARIOFORGE_ALLOWED_ORIGIN": origin,
            "SCENARIOFORGE_BUNDLE_ROOT": str(runs),
            "SCENARIOFORGE_RUN_ROOT": str(runs),
            "SCENARIOFORGE_CAPABILITY_TOKEN": capability,
            "SCENARIOFORGE_CSRF_TOKEN": csrf,
        }
    )
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "scenarioforge.app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--dist-root",
            str(PROJECT_ROOT / "web/dist"),
        ],
        cwd=PROJECT_ROOT,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    headers = {
        "Origin": origin,
        "X-ScenarioForge-Capability": capability,
        "X-ScenarioForge-CSRF": csrf,
        "Content-Type": "application/json",
    }
    try:
        _wait_for(f"{origin}/api/health", process, headers)
        source = json.dumps(SCENARIO)
        status, validated = _request(
            f"{origin}/api/scenarios/validate",
            headers,
            {"source": source, "media_type": "application/json"},
        )
        if status != 200 or validated.get("valid") is not True:
            raise RuntimeError("offline loopback scenario validation failed")
        request = {
            "schema_version": "scenarioforge.run-request.v1",
            "scenario_digest": validated["canonical"]["digest"],
            "seeds": [17],
            "profile": "default",
            "limits": {
                "workers": 1,
                "aggregate_cpu_threads": 2,
                "max_steps": 20,
                "max_simulated_seconds": 30.0,
                "case_wall_seconds": 60.0,
                "bundle_wall_seconds": 600.0,
                "bundle_disk_bytes": 1073741824,
            },
        }
        status, run_result = _request(
            f"{origin}/api/runs",
            headers,
            {"source": source, "media_type": "application/json", "request": request},
        )
        if status != 202 or run_result.get("status") != "completed":
            raise RuntimeError(f"offline real-provider run failed: {run_result}")
        bundle_id = run_result["bundle_id"]
        bundle_path = runs / bundle_id
        verify_bundle(bundle_path)
        bundle_digest = (bundle_path / "bundle.sha256").read_text(encoding="ascii").split()[0]
        status, replay = _request(
            f"{origin}/api/replays/load", headers, {"bundle_id": bundle_id}
        )
        if status != 200 or replay.get("execution", {}).get("metadrive_calls") != 0:
            raise RuntimeError("sealed offline replay was not load-only and exact")
        return {
            "asset": {
                "status": "passed",
                "installation": "allowlisted-archive-after-uv-frozen-lock",
                "distribution": runtime.distribution,
                "version": runtime.version,
                "asset_version": runtime.asset_version,
                "asset_lock_sha256": hashlib.sha256(asset_lock.read_bytes()).hexdigest(),
                "network_access": "denied",
                "auto_download": runtime.auto_download,
            },
            "missing_assets": missing,
            "run": {
                "status": run_result["status"],
                "bundle_id": bundle_id,
                "bundle_manifest_sha256": bundle_digest,
            },
            "replay": {
                "status": "passed",
                "bundle_id": replay["bundle_id"],
                "metadrive_calls": replay["execution"]["metadrive_calls"],
                "total_steps": replay["metrics"]["total_steps"],
            },
        }
    finally:
        _stop(process)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(run(args.output), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
