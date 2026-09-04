"""Authoritative recording and project-scoped Episode Library primitives."""

from .library import ProjectEpisodeLibrary
from .replay import (
    EpisodeNotFound,
    EpisodeRecorder,
    LibraryError,
    ReplayValidationError,
    SimulatedCrash,
    TemporaryEpisodeStore,
    canonical_replay_bytes,
    parse_replay_json,
    validate_replay,
)

__all__ = [
    "EpisodeNotFound",
    "EpisodeRecorder",
    "LibraryError",
    "ProjectEpisodeLibrary",
    "ReplayValidationError",
    "SimulatedCrash",
    "TemporaryEpisodeStore",
    "canonical_replay_bytes",
    "parse_replay_json",
    "validate_replay",
]
