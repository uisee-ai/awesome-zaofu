from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REHEARSAL_ROOT = ROOT / "artifacts" / "rehearsal"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "suite",
        choices=(
            "visual-browser",
            "phase-b-browser",
            "real-matrix",
            "release-browser",
            "full-suite",
        ),
    )
    return parser


def _command(suite: str) -> tuple[str, list[str], dict[str, str], Path]:
    if suite == "visual-browser":
        output = REHEARSAL_ROOT / "visual"
        return (
            "REHEARSAL-AS-BROWSER",
            [sys.executable, "-m", "pytest", "-q", "tests/web/e2e/test_visual_replay.py"],
            {"SCENARIOFORGE_VISUAL_EVIDENCE_DIR": str(output)},
            output,
        )
    if suite == "phase-b-browser":
        output = REHEARSAL_ROOT / "phase-b"
        return (
            "REHEARSAL-B-BROWSER",
            [sys.executable, "-m", "pytest", "-q", "tests/web/e2e/test_phase_b_controls.py"],
            {"SCENARIOFORGE_PHASE_B_EVIDENCE_DIR": str(output)},
            output,
        )
    if suite == "real-matrix":
        output = REHEARSAL_ROOT / "p0-real-matrix"
        return (
            "REHEARSAL-REAL-MATRIX",
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "tests/release/test_p0_real_matrix.py",
                "--junitxml=artifacts/rehearsal/p0-real-matrix.xml",
            ],
            {"SCENARIOFORGE_REAL_MATRIX_EVIDENCE_DIR": str(output)},
            output,
        )
    if suite == "release-browser":
        output = REHEARSAL_ROOT / "release"
        return (
            "REHEARSAL-RELEASE-BROWSER",
            [sys.executable, "-m", "pytest", "-q", "tests/web/e2e/test_p0_release.py"],
            {"SCENARIOFORGE_RELEASE_EVIDENCE_DIR": str(output)},
            output,
        )
    output = REHEARSAL_ROOT
    return (
        "REHEARSAL-ROOT",
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--junitxml=artifacts/rehearsal/full-suite.xml",
        ],
        {},
        output,
    )


def _head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def main() -> int:
    suite = _parser().parse_args().suite
    command_id, command, additions, output = _command(suite)
    output.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    environment.pop("SCENARIOFORGE_CANDIDATE_COMMIT", None)
    environment.pop("SCENARIOFORGE_RELEASE_EVIDENCE_DIR", None)
    environment.pop("SCENARIOFORGE_VISUAL_EVIDENCE_DIR", None)
    environment.pop("SCENARIOFORGE_PHASE_B_EVIDENCE_DIR", None)
    environment.pop("SCENARIOFORGE_REAL_MATRIX_EVIDENCE_DIR", None)
    environment.update(additions)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    started_at = datetime.now(UTC).isoformat()
    completed = subprocess.run(command, cwd=ROOT, env=environment, check=False)
    receipt = {
        "schema_version": "scenarioforge.prefreeze-rehearsal-receipt/v1",
        "command_id": command_id,
        "command": command,
        "source_commit": _head(),
        "started_at": started_at,
        "completed_at": datetime.now(UTC).isoformat(),
        "exit_code": completed.returncode,
        "status": "passed" if completed.returncode == 0 else "failed",
        "candidate_receipt": False,
        "output_root": str(output.relative_to(ROOT)),
    }
    (output / "command-receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
