from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import stat
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from scenarioforge.replay import load_replay_bundle  # noqa: E402


SCHEMA = "scenarioforge.offline-demo-evidence.v1"
FIXTURE = PROJECT_ROOT / "evidence/runtime/metadrive-smoke/bundle"


def _canonical_bytes(payload: object) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _regular_single_link(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return False
    return stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1


def write_evidence(output: Path, payload: dict[str, Any]) -> None:
    if output.is_symlink():
        raise RuntimeError("evidence output must not be a symbolic link")
    output.mkdir(parents=True, exist_ok=True)
    report = output / "report.json"
    sidecar = output / "report.sha256"
    data = _canonical_bytes(payload)
    digest = hashlib.sha256(data).hexdigest()
    digest_data = f"{digest}  report.json\n".encode("ascii")
    if report.exists() or sidecar.exists():
        if not _regular_single_link(report) or not _regular_single_link(sidecar):
            raise RuntimeError("existing evidence files are unsafe")
        if report.read_bytes() != data or sidecar.read_bytes() != digest_data:
            raise RuntimeError("existing evidence does not match this deterministic run")
        return

    nofollow = getattr(os, "O_NOFOLLOW", 0)
    report_fd = os.open(report, os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow, 0o600)
    try:
        os.write(report_fd, data)
        os.fsync(report_fd)
    finally:
        os.close(report_fd)
    sidecar_fd = os.open(sidecar, os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow, 0o600)
    try:
        os.write(sidecar_fd, digest_data)
        os.fsync(sidecar_fd)
    finally:
        os.close(sidecar_fd)
    report.chmod(0o444)
    sidecar.chmod(0o444)


def _manifest_digest() -> str:
    return (FIXTURE / "bundle.sha256").read_text(encoding="ascii").split()[0]


def build_report() -> dict[str, Any]:
    network_attempts: list[str] = []
    metadrive_before = {name for name in sys.modules if name == "metadrive" or name.startswith("metadrive.")}

    def deny_network(*_args: object, **_kwargs: object) -> None:
        network_attempts.append("blocked")
        raise OSError("external network is disabled during offline replay")

    with (
        patch.object(socket.socket, "connect", deny_network),
        patch("socket.create_connection", deny_network),
    ):
        replay = load_replay_bundle(FIXTURE)

    metadrive_after = {name for name in sys.modules if name == "metadrive" or name.startswith("metadrive.")}
    case = replay.cases[0]
    initial = case.frames[0]
    terminal = case.frames[-1]
    passed = (
        replay.execution.runner_state == "stopped"
        and replay.execution.metadrive_calls == 0
        and replay.execution.external_network == "denied"
        and not network_attempts
        and metadrive_after == metadrive_before
        and initial.step == 0
        and initial.position == (5, 3.5)
        and terminal.step == 20
        and terminal.position == (7.8343329429626465, 3.5)
        and terminal.speed_km_h == 10.517005062104593
        and terminal.route_progress == 0.0634676881231387
    )
    return {
        "schema_version": SCHEMA,
        "acceptance_criterion": "AC-07",
        "status": "passed" if passed else "failed",
        "bundle": {
            "id": replay.bundle_id,
            "artifact": "evidence/runtime/metadrive-smoke/bundle",
            "manifest_digest": _manifest_digest(),
            "sealed": True,
        },
        "provider": replay.provider.model_dump(mode="json"),
        "runner_state": replay.execution.runner_state,
        "metadrive_calls": replay.execution.metadrive_calls,
        "external_network_policy": replay.execution.external_network,
        "external_network_attempts": network_attempts,
        "controls_exercised": ["case", "play", "pause", "step", "seek", "rate", "events", "metrics"],
        "initial_frame": initial.model_dump(mode="json"),
        "terminal_frame": terminal.model_dump(mode="json"),
        "events": [event.model_dump(mode="json") for event in case.events],
        "metrics": replay.metrics.model_dump(mode="json"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the sealed offline replay golden path")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_report()
    write_evidence(args.output, report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
