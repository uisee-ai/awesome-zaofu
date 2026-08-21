"""Supervisor-side runtime API; importing it never imports MetaDrive."""

from .candidate import CandidateContractError, P1CandidateContract, freeze_candidate
from .contracts import ArtifactEntry, ArtifactIndex, RunOutcome, RunRequest, RunResult
from .snapshot import SnapshotError, validate_input_snapshot
from .supervisor import RunSupervisor

__all__ = [
    "ArtifactEntry",
    "ArtifactIndex",
    "CandidateContractError",
    "P1CandidateContract",
    "RunOutcome",
    "RunRequest",
    "RunResult",
    "RunSupervisor",
    "SnapshotError",
    "freeze_candidate",
    "validate_input_snapshot",
]
