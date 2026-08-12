from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.release._common import (  # noqa: E402
    EvidenceError,
    artifact_descriptor,
    digest_path,
    read_verified_json,
    write_digest_sidecar,
    write_immutable_json,
)

SCHEMA = "scenarioforge.clean-install-offline-e2e.v1"
RECEIPT_NAMES = ("asset", "network", "run", "replay", "missing-assets")


def validate_offline_report(output: Path) -> dict[str, Any]:
    report = read_verified_json(output / "report.json")
    if report.get("schema_version") != SCHEMA or report.get("status") != "passed":
        raise EvidenceError("clean-install offline report did not pass")
    if report.get("clean_install") is not True:
        raise EvidenceError("clean-install offline report is not from a clean installation")
    locks = report.get("locks")
    if not isinstance(locks, dict) or set(locks) != {"python", "web", "asset"}:
        raise EvidenceError("clean-install offline report has incomplete exact locks")
    if any(not isinstance(value, str) or len(value) != 64 for value in locks.values()):
        raise EvidenceError("clean-install offline report has an invalid lock digest")
    if report.get("provider") != {
        "distribution": "metadrive-simulator",
        "version": "0.4.3",
        "kind": "real",
    }:
        raise EvidenceError("clean-install offline report does not prove the real provider")
    network = report.get("network")
    if not isinstance(network, dict) or network.get("policy") != "denied":
        raise EvidenceError("clean-install offline report has no network denial")
    if network.get("external_attempts") != []:
        raise EvidenceError("clean-install offline report contains an external network attempt")
    run = report.get("run")
    if not isinstance(run, dict) or run.get("status") != "completed":
        raise EvidenceError("clean-install offline run did not complete")
    replay = report.get("replay")
    if not isinstance(replay, dict) or replay.get("status") != "passed" or replay.get("metadrive_calls") != 0:
        raise EvidenceError("clean-install offline sealed replay is incomplete")
    missing = report.get("missing_assets")
    if missing != {
        "status": "rejected_before_execution",
        "code": "assets_missing",
        "network_attempted": False,
    }:
        raise EvidenceError("missing assets were not rejected before execution and download")
    receipts = report.get("receipts")
    if receipts is not None:
        if not isinstance(receipts, list) or len(receipts) != len(RECEIPT_NAMES):
            raise EvidenceError("clean-install offline receipt set is incomplete")
        for descriptor in receipts:
            if not isinstance(descriptor, dict):
                raise EvidenceError("clean-install offline receipt descriptor is invalid")
            path = output / str(descriptor.get("path", ""))
            if digest_path(path) != descriptor.get("sha256"):
                raise EvidenceError("clean-install offline receipt digest mismatch")
    return report


def _run(command: list[str], cwd: Path, *, environment: dict[str, str] | None = None) -> None:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=600,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout)[-3000:]
        raise EvidenceError(f"clean-install command failed ({' '.join(command)}): {detail}")


def _asset_archive() -> Path:
    configured = os.environ.get("SCENARIOFORGE_METADRIVE_ASSET_ARCHIVE")
    candidate = Path(configured) if configured else Path("/tmp/metadrive-assets-0.4.3.zip")
    if candidate.is_symlink() or not candidate.is_file():
        raise EvidenceError(
            "the allowlisted MetaDrive archive is not staged; set "
            "SCENARIOFORGE_METADRIVE_ASSET_ARCHIVE"
        )
    lock = json.loads((PROJECT_ROOT / "config/metadrive-assets.lock.json").read_bytes())
    artifact = lock["artifacts"][0]
    if candidate.stat().st_size != artifact["size_bytes"] or _sha256(candidate) != artifact["sha256"]:
        raise EvidenceError("the staged MetaDrive archive does not match the release allowlist")
    return candidate


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


def _remove_temporary_tree(path: Path, prefix: str) -> None:
    if not path.name.startswith(prefix) or path.parent.resolve() != path.resolve().parent:
        raise EvidenceError(f"refusing to clean an unexpected staging path: {path}")
    for entry in sorted(path.rglob("*"), reverse=True):
        if entry.is_symlink():
            continue
        entry.chmod(stat.S_IRUSR | stat.S_IWUSR | (stat.S_IXUSR if entry.is_dir() else 0))
    path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    shutil.rmtree(path)


def _clean_checkout(target: Path) -> None:
    archive = target.parent / "source.tar"
    with archive.open("wb") as stream:
        completed = subprocess.run(
            ["git", "archive", "--format=tar", "HEAD"],
            cwd=PROJECT_ROOT,
            stdout=stream,
            stderr=subprocess.PIPE,
            check=False,
        )
    if completed.returncode != 0:
        raise EvidenceError("could not archive the exact source revision")
    target.mkdir()
    with tarfile.open(archive) as source:
        source.extractall(target, filter="data")
    archive.unlink()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _deep_validate(output: Path) -> dict[str, Any]:
    report = validate_offline_report(output)
    if report["locks"] != {
        "python": _sha256(PROJECT_ROOT / "uv.lock"),
        "web": _sha256(PROJECT_ROOT / "web/package-lock.json"),
        "asset": _sha256(PROJECT_ROOT / "config/metadrive-assets.lock.json"),
    }:
        raise EvidenceError("clean-install offline report is stale for the current locks")
    if report.get("production_dist_sha256") != digest_path(PROJECT_ROOT / "web/dist"):
        raise EvidenceError("clean-install offline report is stale for web/dist")
    return report


def run(output: Path) -> dict[str, Any]:
    if (output / "report.json").exists():
        return _deep_validate(output)
    if output.exists() or output.is_symlink():
        raise EvidenceError("clean-install offline output must be absent or already complete")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".clean-install-offline-", dir=output.parent))
    workspace = Path(tempfile.mkdtemp(prefix="scenarioforge-clean-install-"))
    try:
        checkout = workspace / "source"
        _clean_checkout(checkout)
        _run(["uv", "sync", "--frozen", "--all-groups", "--offline"], checkout)
        site_packages = subprocess.check_output(
            [
                str(checkout / ".venv/bin/python"),
                "-c",
                "import sysconfig; print(sysconfig.get_paths()['purelib'])",
            ],
            cwd=checkout,
            text=True,
        ).strip()
        _run(
            [
                str(checkout / ".venv/bin/python"),
                "scripts/release/install_metadrive_assets.py",
                "--archive",
                str(_asset_archive()),
                "--target",
                str(Path(site_packages) / "metadrive/assets"),
            ],
            checkout,
        )
        _run(["npm", "--prefix", "web", "ci", "--offline", "--ignore-scripts"], checkout)
        _run(["npm", "--prefix", "web", "run", "build"], checkout)
        if digest_path(checkout / "web/dist") != digest_path(PROJECT_ROOT / "web/dist"):
            raise EvidenceError("clean installation did not reproduce the committed production build")

        network_log = temporary / "network-attempts.jsonl"
        network_log.touch(mode=0o600)
        probe_output = temporary / "probe"
        environment = os.environ.copy()
        environment.update(
            {
                "PYTHONPATH": f"{checkout / 'scripts/release'}:{checkout / 'src'}",
                "PYTHONNOUSERSITE": "1",
                "SCENARIOFORGE_NETWORK_GUARD": "1",
                "SCENARIOFORGE_NETWORK_ATTEMPT_LOG": str(network_log),
            }
        )
        _with_system_libraries(environment)
        completed = subprocess.run(
            [
                str(checkout / ".venv/bin/python"),
                "scripts/release/_offline_probe.py",
                "--output",
                str(probe_output),
            ],
            cwd=checkout,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if completed.returncode != 0:
            raise EvidenceError(f"clean offline probe failed: {(completed.stderr or completed.stdout)[-3000:]}")
        probe = json.loads(completed.stdout)
        attempts = [json.loads(line) for line in network_log.read_text(encoding="utf-8").splitlines()]
        if attempts:
            raise EvidenceError("clean offline probe attempted external network access")

        shutil.move(str(probe_output / "runs"), temporary / "runs")
        receipts = {
            "asset": probe["asset"],
            "network": {"status": "passed", "policy": "denied", "external_attempts": attempts},
            "run": probe["run"],
            "replay": probe["replay"],
            "missing-assets": probe["missing_assets"],
        }
        for name, payload in receipts.items():
            write_immutable_json(temporary / f"{name}-receipt.json", payload)
        write_digest_sidecar(network_log)
        descriptors = [
            artifact_descriptor(temporary, temporary / f"{name}-receipt.json")
            for name in RECEIPT_NAMES
        ]
        report = {
            "schema_version": SCHEMA,
            "status": "passed",
            "clean_install": True,
            "locks": {
                "python": _sha256(checkout / "uv.lock"),
                "web": _sha256(checkout / "web/package-lock.json"),
                "asset": _sha256(checkout / "config/metadrive-assets.lock.json"),
            },
            "provider": {
                "distribution": "metadrive-simulator",
                "version": "0.4.3",
                "kind": "real",
            },
            "network": receipts["network"],
            "run": probe["run"],
            "replay": probe["replay"],
            "missing_assets": probe["missing_assets"],
            "production_dist_sha256": digest_path(checkout / "web/dist"),
            "receipts": descriptors,
        }
        write_immutable_json(temporary / "report.json", report)
        validate_offline_report(temporary)
        os.replace(temporary, output)
        return _deep_validate(output)
    finally:
        if temporary.exists():
            _remove_temporary_tree(temporary, ".clean-install-offline-")
        if workspace.exists():
            _remove_temporary_tree(workspace, "scenarioforge-clean-install-")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prove a clean exact-lock offline release path")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = run(args.output)
    except (EvidenceError, OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "failed", "error": str(error)}, sort_keys=True))
        return 1
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
