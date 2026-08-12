"""Calibrated tolerance comparison and immutable re-simulation."""

from .models import (
    ExactDifference,
    ExactReplayVerification,
    NumericDifference,
    ResimulationReport,
    ResimulationResult,
    ToleranceProfile,
)
from .oracle import (
    CalibrationError,
    calibrate_tolerance,
    compare_bundles,
    resimulate,
    verify_exact_replay,
)

__all__ = [
    "CalibrationError",
    "ExactDifference",
    "ExactReplayVerification",
    "NumericDifference",
    "ResimulationReport",
    "ResimulationResult",
    "ToleranceProfile",
    "calibrate_tolerance",
    "compare_bundles",
    "resimulate",
    "verify_exact_replay",
]
