from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


def _run_twice(script: str, output: Path) -> dict[str, object]:
    command = ["python", script, "--output", str(output)]
    first = subprocess.run(command, check=False, capture_output=True, text=True)
    assert first.returncode == 0, first.stderr
    first_bytes = (output / "report.json").read_bytes()
    second = subprocess.run(command, check=False, capture_output=True, text=True)
    assert second.returncode == 0, second.stderr
    assert (output / "report.json").read_bytes() == first_bytes
    digest = hashlib.sha256(first_bytes).hexdigest()
    assert (output / "report.sha256").read_text(encoding="ascii") == f"{digest}  report.json\n"
    return json.loads(first_bytes)


def test_offline_demo_evidence_is_exact_network_free_and_idempotent(tmp_path: Path) -> None:
    report = _run_twice("scripts/run_offline_demo.py", tmp_path / "offline")

    assert report["schema_version"] == "scenarioforge.offline-demo-evidence.v1"
    assert report["status"] == "passed"
    assert report["runner_state"] == "stopped"
    assert report["metadrive_calls"] == 0
    assert report["external_network_attempts"] == []
    assert report["terminal_frame"]["position"] == [7.8343329429626465, 3.5]


def test_security_suite_covers_mandatory_matrix_without_disclosure(tmp_path: Path) -> None:
    report = _run_twice("scripts/run_security_suite.py", tmp_path / "security")

    assert report["schema_version"] == "scenarioforge.local-security-evidence.v1"
    assert report["status"] == "passed"
    assert report["disclosure_scan"] == {
        "auth_material": "absent",
        "host_absolute_paths": "absent",
        "secret_canaries": "absent",
    }
    assert set(report["attacks"]) == {
        "illegal_origin",
        "csrf",
        "capability_token",
        "path_traversal",
        "symlink_traversal",
        "hardlink_traversal",
        "archive_bomb",
        "xss",
        "pickle",
        "secret_canary",
    }
    assert all(result["rejected"] for result in report["attacks"].values())
