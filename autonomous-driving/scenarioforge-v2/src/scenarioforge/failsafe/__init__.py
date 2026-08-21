"""Fail-closed terminal publication for one isolated ScenarioForge run."""

from .contracts import FailureKind, TerminalStatus, create_run_result
from .process_tree import (
    ProcessTreeIsolationError,
    TerminationEvidence,
    live_process_group_members,
    terminate_process_tree,
)
from .publisher import (
    FailureOutcome,
    FailurePublicationError,
    publish_failure,
)
from .supervisor import FailureController

__all__ = [
    "FailureKind",
    "FailureController",
    "FailureOutcome",
    "FailurePublicationError",
    "ProcessTreeIsolationError",
    "TerminalStatus",
    "TerminationEvidence",
    "create_run_result",
    "live_process_group_members",
    "publish_failure",
    "terminate_process_tree",
]
