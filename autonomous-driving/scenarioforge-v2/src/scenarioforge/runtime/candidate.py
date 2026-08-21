from __future__ import annotations

import hashlib
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


_COMMIT = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_STATIC_INVENTORY_COMMIT = "1eb82f2eaa202a9305f91698f62eff9c871fa459"
_STATIC_INVENTORY_PATH = "tests/test_p0b_frontend_contract.py"


class CandidateContractError(RuntimeError):
    pass


@dataclass(frozen=True)
class CandidateEntrypoint:
    entrypoint_id: str
    start_command: str
    health_check: str

    def to_dict(self) -> dict[str, str]:
        return {
            "entrypoint_id": self.entrypoint_id,
            "start_command": self.start_command,
            "health_check": self.health_check,
        }


@dataclass(frozen=True)
class CandidateGate:
    command_id: str
    command: str
    acceptance_ids: tuple[str, ...]
    owner: str
    tier: str
    deterministic: bool
    reusable: bool
    timeout_seconds: int

    @property
    def command_digest(self) -> str:
        return hashlib.sha256(self.command.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {
            "command_id": self.command_id,
            "command": self.command,
            "command_digest": self.command_digest,
            "acceptance_ids": list(self.acceptance_ids),
            "owner": self.owner,
            "tier": self.tier,
            "deterministic": self.deterministic,
            "reusable": self.reusable,
            "timeout_seconds": self.timeout_seconds,
        }


P1_ENTRYPOINTS = (
    CandidateEntrypoint(
        entrypoint_id="scenarioforge-cli",
        start_command="uv run --frozen python -m scenarioforge health",
        health_check="uv run --frozen python -m scenarioforge health",
    ),
    CandidateEntrypoint(
        entrypoint_id="scenarioforge-web",
        start_command=(
            "uv run --frozen python -m scenarioforge web --port 8765 "
            "--timeout-seconds 3600"
        ),
        health_check="curl -fsS http://127.0.0.1:8765/api/session",
    ),
    CandidateEntrypoint(
        entrypoint_id="p1-candidate-gate",
        start_command=(
            "uv run --frozen python tests/p1/delivery/run_candidate_delivery.py "
            "--source-candidate-commit \"$(git rev-parse HEAD)\" "
            "--evidence-dir \"$SCENARIOFORGE_RELEASE_EVIDENCE_DIR\""
        ),
        health_check=(
            "uv run --frozen python tests/p1/delivery/run_candidate_delivery.py "
            "--health-check"
        ),
    ),
)


P1_CANONICAL_GATES = (
    CandidateGate(
        command_id="V-P1-CONTRACTS",
        command=(
            "uv sync --frozen && uv run --frozen python -m pytest -q "
            "tests/p1/contracts tests/p1/authoring tests/p1/security"
        ),
        acceptance_ids=(
            "AC-P1-001",
            "AC-P1-002",
            "AC-P1-003",
            "AC-P1-004",
            "AC-P1-010",
            "AC-P1-011",
            "AC-P1-013",
            "AC-P1-017",
            "AC-P1-018",
        ),
        owner="dev",
        tier="runtime",
        deterministic=True,
        reusable=True,
        timeout_seconds=1200,
    ),
    CandidateGate(
        command_id="V-P1-RIGHT-HAND-TRAFFIC",
        command=(
            "uv run --frozen python -m pytest -q "
            "tests/p1/replay/test_right_hand_traffic.py "
            "tests/p1/replay/test_wrong_way_rejection.py"
        ),
        acceptance_ids=("AC-P1-005", "AC-P1-006", "AC-P1-009"),
        owner="dev",
        tier="runtime",
        deterministic=True,
        reusable=True,
        timeout_seconds=600,
    ),
    CandidateGate(
        command_id="V-P1-PROVENANCE-SNAPSHOT",
        command=(
            "uv run --frozen python -m pytest -q "
            "tests/p1/provenance/test_snapshot_contract.py "
            "tests/p1/provenance/test_snapshot_fail_closed.py"
        ),
        acceptance_ids=("AC-P1-011",),
        owner="dev",
        tier="runtime",
        deterministic=True,
        reusable=True,
        timeout_seconds=900,
    ),
    CandidateGate(
        command_id="V-P1-ARTIFACT-REDACTION",
        command=(
            "uv run --frozen python -m pytest -q "
            "tests/p1/security/test_artifact_allowlists.py "
            "tests/p1/security/test_marked_secret_gate.py"
        ),
        acceptance_ids=("AC-P1-017", "AC-P1-018"),
        owner="security_reviewer",
        tier="runtime",
        deterministic=True,
        reusable=True,
        timeout_seconds=900,
    ),
    CandidateGate(
        command_id="V-P1-REAL-SMARTS",
        command=(
            "SCENARIOFORGE_SMARTS_EVIDENCE_DIR=artifacts/p1/smarts "
            "uv run --frozen python -m pytest -q "
            "tests/p1/smarts/test_real_adapter.py "
            "tests/p1/smarts/test_real_scenarios.py "
            "tests/p1/smarts/test_reproducibility.py"
        ),
        acceptance_ids=(
            "AC-P1-004",
            "AC-P1-005",
            "AC-P1-006",
            "AC-P1-009",
            "AC-P1-011",
            "AC-P1-012",
            "AC-P1-014",
            "AC-P1-017",
            "AC-P1-018",
        ),
        owner="verify",
        tier="e2e",
        deterministic=False,
        reusable=True,
        timeout_seconds=5400,
    ),
    CandidateGate(
        command_id="V-P1-REAL-METADRIVE",
        command=(
            "uv run --frozen python -m pytest -q tests/p0c "
            "tests/web/acceptance/test_p0c_real_validation.py"
        ),
        acceptance_ids=("AC-P1-011", "AC-P1-012", "AC-P1-014", "AC-P1-016"),
        owner="verify",
        tier="e2e",
        deterministic=False,
        reusable=True,
        timeout_seconds=5400,
    ),
    CandidateGate(
        command_id="V-P1-DOCKER-CHROMIUM",
        command=(
            "docker build -f tests/web/e2e/Dockerfile.playwright -t "
            "scenarioforge-p1-e2e . && docker run --rm --network none "
            "--shm-size=1g --user \"$(id -u):$(id -g)\" -v \"$PWD:/workspace:ro\" "
            "-v \"$SCENARIOFORGE_RELEASE_EVIDENCE_DIR:/evidence\" "
            "-w /workspace -e HOME=/tmp/scenarioforge-pw "
            "-e SCENARIOFORGE_E2E_BIND_HOST=127.0.0.1 "
            "-e SCENARIOFORGE_E2E_BASE_URL=http://127.0.0.1:8765 "
            "-e SCENARIOFORGE_CANDIDATE_COMMIT=\"$(git rev-parse HEAD)\" "
            "-e SCENARIOFORGE_RELEASE_EVIDENCE_DIR=/evidence "
            "-e SCENARIOFORGE_MARKED_SECRET=[REDACTED_SECRET] "
            "scenarioforge-p1-e2e bash -lc 'set -euo pipefail; mkdir -p "
            "\"$HOME\" \"$SCENARIOFORGE_RELEASE_EVIDENCE_DIR\"; python -m pytest -q "
            "tests/web/e2e/test_p1_release.py "
            "tests/web/e2e/test_p1_secret_redaction.py'"
        ),
        acceptance_ids=(
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
        ),
        owner="verify",
        tier="e2e",
        deterministic=False,
        reusable=True,
        timeout_seconds=7200,
    ),
    CandidateGate(
        command_id="V-P1-VISUAL-SIGNOFF",
        command=(
            "uv run --frozen python -m pytest -q "
            "tests/p1/delivery/test_visual_review_receipt.py"
        ),
        acceptance_ids=("AC-P1-015", "AC-P1-017", "AC-P1-018"),
        owner="quality_gate",
        tier="manual_evidence",
        deterministic=True,
        reusable=True,
        timeout_seconds=120,
    ),
    CandidateGate(
        command_id="V-P1-FULL-REGRESSION",
        command="uv run --frozen python -m pytest -q",
        acceptance_ids=("AC-P1-016",),
        owner="verify",
        tier="runtime",
        deterministic=False,
        reusable=True,
        timeout_seconds=10800,
    ),
)


@dataclass(frozen=True)
class P1CandidateContract:
    candidate_commit: str
    entrypoints: tuple[CandidateEntrypoint, ...] = P1_ENTRYPOINTS
    gates: tuple[CandidateGate, ...] = P1_CANONICAL_GATES

    def __post_init__(self) -> None:
        if not _COMMIT.fullmatch(self.candidate_commit):
            raise CandidateContractError("candidate commit is invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "scenarioforge.p1-candidate-contract/v1",
            "status": "frozen",
            "candidate_commit": self.candidate_commit,
            "static_inventory_input": {
                "commit": _STATIC_INVENTORY_COMMIT,
                "path": _STATIC_INVENTORY_PATH,
            },
            "entrypoints": [entrypoint.to_dict() for entrypoint in self.entrypoints],
            "gates": [gate.to_dict() for gate in self.gates],
        }


def freeze_candidate(
    *,
    project_root: Path | str,
    candidate_commit: str,
) -> P1CandidateContract:
    root = Path(project_root)
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as error:
        raise CandidateContractError("candidate HEAD cannot be resolved") from error
    if not _COMMIT.fullmatch(head) or candidate_commit != head:
        raise CandidateContractError("candidate commit is not the current frozen HEAD")
    return P1CandidateContract(candidate_commit=candidate_commit)


__all__ = [
    "CandidateContractError",
    "CandidateEntrypoint",
    "CandidateGate",
    "P1CandidateContract",
    "P1_CANONICAL_GATES",
    "P1_ENTRYPOINTS",
    "freeze_candidate",
]
