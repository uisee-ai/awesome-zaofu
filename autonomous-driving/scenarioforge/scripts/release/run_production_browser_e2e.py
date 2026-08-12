from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
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
from scripts.release._common import (  # noqa: E402
    EvidenceError,
    digest_path,
    read_digest_sidecar,
    read_verified_json,
    write_digest_sidecar,
    write_immutable_json,
)

SCHEMA = "scenarioforge.production-browser-e2e.v1"
REQUIRED_CHECKS = {
    "import",
    "edit",
    "field_error_location",
    "canonical_preview",
    "real_run",
    "metrics",
    "exact_replay",
    "json_export",
    "yaml_export",
}


def validate_browser_report(output: Path) -> dict[str, Any]:
    report = read_verified_json(output / "report.json")
    if report.get("schema_version") != SCHEMA or report.get("status") != "passed":
        raise EvidenceError("production browser report did not pass")
    if (
        report.get("provider")
        != {"distribution": "metadrive-simulator", "version": "0.4.3", "kind": "real"}
        or report.get("mock_provider_used") is not False
    ):
        raise EvidenceError("production browser report does not prove the real provider")
    if report.get("external_network_attempts") != []:
        raise EvidenceError("production browser report contains an external network attempt")
    checks = report.get("checks")
    if not isinstance(checks, dict) or set(checks) != REQUIRED_CHECKS:
        raise EvidenceError("production browser report has an incomplete golden path")
    if any(value != "passed" for value in checks.values()):
        raise EvidenceError("production browser report has a failed golden-path check")
    if not isinstance(report.get("production_dist_sha256"), str):
        raise EvidenceError("production browser report has no Web build digest")
    trace = report.get("trace")
    if not isinstance(trace, dict) or trace.get("path") != "chromium-trace.zip":
        raise EvidenceError("production browser report has no supported-Chromium trace")
    if read_digest_sidecar(output / "chromium-trace.zip") != trace.get("sha256"):
        raise EvidenceError("production browser trace digest mismatch")
    bundle = report.get("bundle")
    if not isinstance(bundle, dict) or not isinstance(bundle.get("id"), str):
        raise EvidenceError("production browser report has no sealed run bundle")
    return report


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _with_system_libraries(environment: dict[str, str]) -> dict[str, str]:
    configured = os.environ.get("SCENARIOFORGE_SYSTEM_LIBRARY_ROOT")
    if not configured:
        raise EvidenceError("SCENARIOFORGE_SYSTEM_LIBRARY_ROOT must be set")
    root = Path(configured)
    if not root.is_dir() or not (root / "libGL.so.1").is_file():
        raise EvidenceError(
            "SCENARIOFORGE_SYSTEM_LIBRARY_ROOT must contain libGL.so.1"
        )
    environment["LD_LIBRARY_PATH"] = ":".join(
        value for value in (str(root), environment.get("LD_LIBRARY_PATH")) if value
    )
    return environment


def _wait_for(url: str, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise EvidenceError(f"release entrypoint exited before readiness: {process.returncode}")
        try:
            with urllib.request.urlopen(url, timeout=0.5) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, TimeoutError):
            pass
        time.sleep(0.1)
    raise EvidenceError("release entrypoint did not become ready")


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


def _remove_temporary_tree(path: Path) -> None:
    """Remove only this script's named staging tree, including sealed read-only bundles."""

    if not path.name.startswith(".browser-production-") or path.parent.resolve() != path.resolve().parent:
        raise EvidenceError(f"refusing to clean an unexpected browser staging path: {path}")
    for entry in sorted(path.rglob("*"), reverse=True):
        if entry.is_symlink():
            continue
        entry.chmod(stat.S_IRUSR | stat.S_IWUSR | (stat.S_IXUSR if entry.is_dir() else 0))
    path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    shutil.rmtree(path)


def _deep_validate(output: Path) -> dict[str, Any]:
    report = validate_browser_report(output)
    if report["production_dist_sha256"] != digest_path(PROJECT_ROOT / "web/dist"):
        raise EvidenceError("production browser report is stale for web/dist")
    bundle = report["bundle"]
    bundle_path = output / bundle["path"]
    verify_bundle(bundle_path)
    manifest_digest = (bundle_path / "bundle.sha256").read_text(encoding="ascii").split()[0]
    if bundle.get("manifest_sha256") != manifest_digest:
        raise EvidenceError("production browser bundle digest mismatch")
    return report


def run(output: Path) -> dict[str, Any]:
    if (output / "report.json").exists():
        return _deep_validate(output)
    if output.exists() or output.is_symlink():
        raise EvidenceError("production browser output must be absent or already complete")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".browser-production-", dir=output.parent))
    server: subprocess.Popen[bytes] | None = None
    try:
        port = _free_port()
        release_url = f"http://127.0.0.1:{port}"
        capability = "release-browser-capability-5e7781"
        csrf = "release-browser-csrf-392bc0"
        runs = temporary / "runs"
        environment = os.environ.copy()
        environment.update(
            {
                "PYTHONPATH": str(SRC_ROOT),
                "SCENARIOFORGE_ALLOWED_ORIGIN": release_url,
                "SCENARIOFORGE_BUNDLE_ROOT": str(runs),
                "SCENARIOFORGE_RUN_ROOT": str(runs),
                "SCENARIOFORGE_CAPABILITY_TOKEN": capability,
                "SCENARIOFORGE_CSRF_TOKEN": csrf,
            }
        )
        _with_system_libraries(environment)
        python = PROJECT_ROOT / ".venv/bin/python"
        server = subprocess.Popen(
            [
                str(python if python.is_file() else Path(sys.executable)),
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
        _wait_for(release_url, server)
        result_path = temporary / ".browser-result.json"
        browser_environment = environment | {
            "SCENARIOFORGE_RELEASE_URL": release_url,
            "SCENARIOFORGE_BROWSER_OUTPUT": str(temporary),
            "SCENARIOFORGE_BROWSER_RESULT": str(result_path),
        }
        completed = subprocess.run(
            ["node", "scripts/release/production_browser_e2e.mjs"],
            cwd=PROJECT_ROOT,
            env=browser_environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout)[-2000:]
            raise EvidenceError(f"supported-Chromium production flow failed: {message}")
        browser_result = json.loads(result_path.read_bytes())
        result_path.unlink()
        bundle_id = browser_result["bundle_id"]
        bundle_path = runs / bundle_id
        verify_bundle(bundle_path)
        bundle_digest = (bundle_path / "bundle.sha256").read_text(encoding="ascii").split()[0]
        trace_digest = write_digest_sidecar(temporary / "chromium-trace.zip")
        report = {
            "schema_version": SCHEMA,
            "status": "passed",
            "provider": {
                "distribution": "metadrive-simulator",
                "version": "0.4.3",
                "kind": "real",
            },
            "mock_provider_used": False,
            "external_network_attempts": browser_result["external_network_attempts"],
            "production_dist_sha256": digest_path(PROJECT_ROOT / "web/dist"),
            "chromium_version": browser_result["chromium_version"],
            "trace": {"path": "chromium-trace.zip", "sha256": trace_digest},
            "checks": browser_result["checks"],
            "bundle": {
                "id": bundle_id,
                "path": f"runs/{bundle_id}",
                "manifest_sha256": bundle_digest,
            },
            "metrics_readout": browser_result["metrics"],
        }
        write_immutable_json(temporary / "report.json", report)
        validate_browser_report(temporary)
        os.replace(temporary, output)
        return _deep_validate(output)
    finally:
        if server is not None:
            _stop(server)
        if temporary.exists():
            _remove_temporary_tree(temporary)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the exact production Chromium golden path")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = run(args.output)
    except EvidenceError as error:
        print(json.dumps({"status": "failed", "error": str(error)}, sort_keys=True))
        return 1
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
