#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[3]
DOCKERFILE = Path("tests/web/e2e/Dockerfile.playwright")
REPORT_NAME = "p1-release-browser-report.json"
SCENARIOS = (
    "highway_merge",
    "competitive_lane_change",
    "cross_traffic_red_light_violation",
    "unprotected_left_turn",
    "pedestrian_red_light_crossing",
)
COMMIT = re.compile(r"^[0-9a-f]{40}$")


class VisualReplayRunnerError(RuntimeError):
    def __init__(self, message: str, *, failure_class: str) -> None:
        super().__init__(message)
        self.failure_class = failure_class


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise VisualReplayRunnerError(
            "visual replay runner arguments are invalid",
            failure_class="runner_setup",
        )


def _parser() -> argparse.ArgumentParser:
    parser = SafeArgumentParser()
    parser.add_argument("--health-check", action="store_true")
    parser.add_argument("--evidence-dir")
    return parser


def _write_json(stream: Any, payload: dict[str, object]) -> None:
    stream.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
    stream.flush()


def _health() -> dict[str, object]:
    return {
        "schema_version": "scenarioforge.visual-replay-runner-health/v1",
        "status": "ready",
        "runner_id": "p1-docker-chromium",
        "browser": "chromium",
        "network_policy": "offline-runtime",
        "scenario_count": len(SCENARIOS),
        "required_arguments": ["--evidence-dir"],
    }


def _head() -> str:
    try:
        value = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as error:
        raise VisualReplayRunnerError(
            "candidate commit cannot be resolved",
            failure_class="runner_setup",
        ) from error
    if COMMIT.fullmatch(value) is None:
        raise VisualReplayRunnerError(
            "candidate commit is invalid",
            failure_class="runner_setup",
        )
    return value


def _evidence_root(raw: object) -> Path:
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise VisualReplayRunnerError(
            "evidence directory is required",
            failure_class="runner_setup",
        )
    requested = Path(raw)
    if requested.is_symlink():
        raise VisualReplayRunnerError(
            "evidence directory is unsafe",
            failure_class="runner_setup",
        )
    try:
        requested.mkdir(parents=True, exist_ok=True)
        resolved = requested.resolve(strict=True)
    except OSError as error:
        raise VisualReplayRunnerError(
            "evidence directory is unavailable",
            failure_class="runner_setup",
        ) from error
    if not resolved.is_dir():
        raise VisualReplayRunnerError(
            "evidence directory is unsafe",
            failure_class="runner_setup",
        )
    try:
        resolved.relative_to(ROOT.resolve(strict=True))
    except ValueError:
        return resolved
    raise VisualReplayRunnerError(
        "evidence directory must be an external sidecar",
        failure_class="runner_setup",
    )


def _run(command: Sequence[str], *, phase: str) -> None:
    try:
        completed = subprocess.run(command, cwd=ROOT, check=False)
    except OSError as error:
        raise VisualReplayRunnerError(
            f"{phase} could not start",
            failure_class="runner_setup",
        ) from error
    if completed.returncode != 0:
        raise VisualReplayRunnerError(
            f"{phase} failed with exit code {completed.returncode}",
            failure_class=(
                "runner_setup" if phase == "docker image build" else "product_assertion"
            ),
        )


def _docker_commands(
    *,
    evidence: Path,
    candidate_commit: str,
) -> tuple[list[str], list[str]]:
    image = f"scenarioforge-p1-visual-{candidate_commit[:12]}"
    build = [
        "docker",
        "build",
        "--pull=false",
        "-f",
        DOCKERFILE.as_posix(),
        "-t",
        image,
        ".",
    ]
    run = [
        "docker",
        "run",
        "--rm",
        "--network", "none",
        "--shm-size=1g",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--tmpfs",
        "/tmp:rw,exec,nosuid,size=4g",
        "-v",
        f"{ROOT}:/workspace:ro",
        "-v",
        f"{evidence}:/evidence:rw",
        "-w",
        "/workspace",
        "-e",
        "HOME=/tmp/scenarioforge-pw",
        "-e",
        "PYTHONDONTWRITEBYTECODE=1",
        "-e",
        "SCENARIOFORGE_E2E_BIND_HOST=127.0.0.1",
        "-e",
        "SCENARIOFORGE_E2E_BASE_URL=http://127.0.0.1:8765",
        "-e",
        f"SCENARIOFORGE_CANDIDATE_COMMIT={candidate_commit}",
        "-e",
        "SCENARIOFORGE_RELEASE_EVIDENCE_DIR=/evidence",
        "-e",
        "SCENARIOFORGE_MARKED_SECRET=[REDACTED_SECRET]",
        image,
        "python",
        "-m",
        "pytest",
        "-q",
        "tests/web/e2e/test_p1_release.py",
        "tests/web/e2e/test_p1_secret_redaction.py",
    ]
    return build, run


def _validate_report(evidence: Path, candidate_commit: str) -> dict[str, object]:
    report_path = evidence / REPORT_NAME
    if report_path.is_symlink() or not report_path.is_file():
        raise VisualReplayRunnerError(
            "browser report was not produced",
            failure_class="product_assertion",
        )
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise VisualReplayRunnerError(
            "browser report is invalid",
            failure_class="product_assertion",
        ) from error
    scenarios = report.get("scenarios") if isinstance(report, dict) else None
    if (
        report.get("schema_version") != "scenarioforge.p1-candidate-media/v3"
        or report.get("source_candidate_commit") != candidate_commit
        or report.get("console_errors") != []
        or report.get("page_errors") != []
        or not isinstance(scenarios, list)
        or tuple(item.get("scenario_id") for item in scenarios) != SCENARIOS
        or report.get("assertion_summary", {}).get("status") != "passed"
        or report.get("assertion_summary", {}).get("media_count") != 15
    ):
        raise VisualReplayRunnerError(
            "browser report does not satisfy the candidate contract",
            failure_class="product_assertion",
        )
    return {
        "browser_report": REPORT_NAME,
        "scenario_count": len(scenarios),
        "media_count": 15,
    }


def main(argv: list[str] | None = None) -> int:
    try:
        arguments = _parser().parse_args(argv)
        if arguments.health_check:
            _write_json(sys.stdout, _health())
            return 0
        if shutil.which("docker") is None:
            raise VisualReplayRunnerError(
                "docker executable is unavailable",
                failure_class="runner_setup",
            )
        evidence = _evidence_root(arguments.evidence_dir)
        candidate_commit = _head()
        build, run = _docker_commands(
            evidence=evidence,
            candidate_commit=candidate_commit,
        )
        _write_json(
            sys.stdout,
            {
                "schema_version": "scenarioforge.visual-replay-run/v1",
                "status": "running",
                "candidate_commit": candidate_commit,
                "browser": "chromium",
                "network_policy": "offline-runtime",
            },
        )
        _run(build, phase="docker image build")
        _run(run, phase="real Chromium product assertions")
        summary = _validate_report(evidence, candidate_commit)
        _write_json(
            sys.stdout,
            {
                "schema_version": "scenarioforge.visual-replay-run/v1",
                "status": "passed",
                "candidate_commit": candidate_commit,
                **summary,
            },
        )
        return 0
    except VisualReplayRunnerError as error:
        _write_json(
            sys.stderr,
            {
                "schema_version": "scenarioforge.visual-replay-run/v1",
                "status": "failed",
                "failure_class": error.failure_class,
                "message": str(error),
            },
        )
        return 2 if error.failure_class == "runner_setup" else 1


if __name__ == "__main__":
    raise SystemExit(main())
