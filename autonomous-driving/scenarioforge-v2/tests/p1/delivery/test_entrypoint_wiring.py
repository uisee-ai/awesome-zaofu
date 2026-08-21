from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import ProxyHandler, Request, build_opener


ROOT = Path(__file__).resolve().parents[3]
DELIVERY_RUNNER = ROOT / "tests/p1/delivery/run_candidate_delivery.py"
DIRECT_OPENER = build_opener(ProxyHandler({}))

EXPECTED_ENTRYPOINTS = [
    {
        "entrypoint_id": "scenarioforge-cli",
        "start_command": "uv run --frozen python -m scenarioforge health",
        "health_check": "uv run --frozen python -m scenarioforge health",
    },
    {
        "entrypoint_id": "scenarioforge-web",
        "start_command": (
            "uv run --frozen python -m scenarioforge web --port 8765 "
            "--timeout-seconds 3600"
        ),
        "health_check": "curl -fsS http://127.0.0.1:8765/api/session",
    },
    {
        "entrypoint_id": "p1-candidate-gate",
        "start_command": (
            "uv run --frozen python tests/p1/delivery/run_candidate_delivery.py "
            "--source-candidate-commit \"$(git rev-parse HEAD)\" "
            "--evidence-dir \"$SCENARIOFORGE_RELEASE_EVIDENCE_DIR\""
        ),
        "health_check": (
            "uv run --frozen python tests/p1/delivery/run_candidate_delivery.py "
            "--health-check"
        ),
    },
]

EXPECTED_GATES = [
    (
        "V-P1-CONTRACTS",
        "77299ff064a4a7094226f03c43dbdc45fdba398244a514aba8cc238a41030c45",
        [
            "AC-P1-001",
            "AC-P1-002",
            "AC-P1-003",
            "AC-P1-004",
            "AC-P1-010",
            "AC-P1-011",
            "AC-P1-013",
            "AC-P1-017",
            "AC-P1-018",
        ],
    ),
    (
        "V-P1-RIGHT-HAND-TRAFFIC",
        "8825cbb0ed96f0459661d97f1d1ba993d88db4927ff5e9847a9739768878be98",
        ["AC-P1-005", "AC-P1-006", "AC-P1-009"],
    ),
    (
        "V-P1-PROVENANCE-SNAPSHOT",
        "9cf4a030bfe94ef12fa5a3aab2273db3d1a161abda9f1ff681f8eab5fe4538cd",
        ["AC-P1-011"],
    ),
    (
        "V-P1-ARTIFACT-REDACTION",
        "d93b5bb3a0cbed2dec25b0d7710c0423b4729160cd0228845190548ea4df7950",
        ["AC-P1-017", "AC-P1-018"],
    ),
    (
        "V-P1-REAL-SMARTS",
        "b92f5d6a3aa75e60fb453c8ddd983ed44ffe667fab6cfe86bb171afa7c9b8869",
        [
            "AC-P1-004",
            "AC-P1-005",
            "AC-P1-006",
            "AC-P1-009",
            "AC-P1-011",
            "AC-P1-012",
            "AC-P1-014",
            "AC-P1-017",
            "AC-P1-018",
        ],
    ),
    (
        "V-P1-REAL-METADRIVE",
        "9bb0ca9f615d7906abccd7ff6f6e27178e57d8bb71a176ecf5343c96c0bc80c3",
        ["AC-P1-011", "AC-P1-012", "AC-P1-014", "AC-P1-016"],
    ),
    (
        "V-P1-DOCKER-CHROMIUM",
        "5c28f7cbc5d561d1f34fed16894096f599daf693eee4c9cc008f7776b72e4a0c",
        [
            "AC-P1-001",
            "AC-P1-002",
            "AC-P1-003",
            "AC-P1-005",
            "AC-P1-006",
            "AC-P1-007",
            "AC-P1-008",
            "AC-P1-009",
            "AC-P1-010",
            "AC-P1-011",
            "AC-P1-013",
            "AC-P1-014",
            "AC-P1-016",
            "AC-P1-017",
            "AC-P1-018",
        ],
    ),
    (
        "V-P1-VISUAL-SIGNOFF",
        "14d070efa7ddff9b50950e5937c7a07b7a13eaa378d79e099e5bfa5d0748b726",
        ["AC-P1-015", "AC-P1-017", "AC-P1-018"],
    ),
    (
        "V-P1-FULL-REGRESSION",
        "9b714e7c01e0d3730a75478bd361bef896b2cd22adafdd5f2babc173a8858b6e",
        ["AC-P1-016"],
    ),
]


def _head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _run(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *arguments],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def _loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def test_candidate_contract_binds_head_entrypoints_and_nine_exact_gates() -> None:
    candidate = _head()

    completed = _run(
        "-m",
        "scenarioforge",
        "--project-root",
        str(ROOT),
        "candidate-contract",
        "--candidate-commit",
        candidate,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""
    payload = json.loads(completed.stdout)
    assert list(payload) == [
        "candidate_commit",
        "entrypoints",
        "gates",
        "schema_version",
        "static_inventory_input",
        "status",
    ]
    assert payload["schema_version"] == "scenarioforge.p1-candidate-contract/v1"
    assert payload["status"] == "frozen"
    assert payload["candidate_commit"] == candidate
    assert payload["static_inventory_input"] == {
        "commit": "1eb82f2eaa202a9305f91698f62eff9c871fa459",
        "path": "tests/test_p0b_frontend_contract.py",
    }
    assert payload["entrypoints"] == EXPECTED_ENTRYPOINTS
    assert [
        (gate["command_id"], gate["command_digest"], gate["acceptance_ids"])
        for gate in payload["gates"]
    ] == EXPECTED_GATES
    assert all(
        list(gate)
        == [
            "acceptance_ids",
            "command",
            "command_digest",
            "command_id",
            "deterministic",
            "owner",
            "reusable",
            "tier",
            "timeout_seconds",
        ]
        for gate in payload["gates"]
    )


def test_cli_web_and_candidate_runner_health_checks_are_executable(
    tmp_path: Path,
) -> None:
    cli = _run("-m", "scenarioforge", "health")
    runner = _run(str(DELIVERY_RUNNER), "--health-check")

    assert cli.returncode == 0, cli.stderr
    assert json.loads(cli.stdout)["payload"] == {
        "capabilities": [
            "validation",
            "preflight",
            "control",
            "batch",
            "recovery",
            "query",
            "comparison",
        ],
        "package": "scenarioforge",
        "schema_version": "scenarioforge.client-health/v1",
        "transport": "local-no-web",
        "version": "0.1.0",
    }
    assert runner.returncode == 0, runner.stderr
    assert json.loads(runner.stdout) == {
        "entrypoint_id": "p1-candidate-gate",
        "browser_report": "p1-release-browser-report.json",
        "required_arguments": ["--source-candidate-commit", "--evidence-dir"],
        "schema_version": "scenarioforge.candidate-delivery-health/v2",
        "status": "ready",
        "visual_review_receipt": "visual-review-receipt.json",
    }

    port = _loopback_port()
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "scenarioforge",
            "--project-root",
            str(ROOT),
            "--workspace",
            str(tmp_path / "workspace"),
            "web",
            "--port",
            str(port),
            "--timeout-seconds",
            "30",
        ],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 20
        while True:
            if process.poll() is not None or time.monotonic() >= deadline:
                output = process.stdout.read().decode(errors="replace")
                raise AssertionError(f"Web health endpoint did not start: {output}")
            try:
                with DIRECT_OPENER.open(
                    Request(f"http://127.0.0.1:{port}/api/session"),
                    timeout=0.5,
                ) as response:
                    session = json.loads(response.read())
                break
            except (OSError, URLError, TimeoutError, json.JSONDecodeError):
                time.sleep(0.05)
        assert session["schema_version"] == "scenarioforge.web-session/v1"
        assert isinstance(session["csrf_token"], str)
        assert len(session["csrf_token"]) >= 32
    finally:
        process.terminate()
        process.wait(timeout=20)
