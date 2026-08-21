"""Local Web lifecycle primitives with no arbitrary-path or client-cancel surface."""

from .coordinator import (
    CoordinatorError,
    ExecutionState,
    InvalidIdentifierError,
    RunCoordinator,
    RunExecutionError,
    RunReference,
    SlotOccupiedError,
    UnknownRunError,
    UnknownScenarioError,
)

__all__ = [
    "CoordinatorError",
    "ExecutionState",
    "InvalidIdentifierError",
    "RunCoordinator",
    "RunExecutionError",
    "RunReference",
    "SlotOccupiedError",
    "UnknownRunError",
    "UnknownScenarioError",
]
