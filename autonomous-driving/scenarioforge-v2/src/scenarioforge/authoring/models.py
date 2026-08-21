from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from scenarioforge.core.canonical import CanonicalModel


class CapabilityStatus(str, Enum):
    """Backend-neutral semantic fidelity used by authoring diagnostics."""

    EXACT = "exact"
    LOSSY = "lossy"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class AuthoringDiagnostic(CanonicalModel):
    code: str
    path: str
    capability: str
    status: CapabilityStatus
    reason: str
    suggestion: str


@dataclass(frozen=True)
class AuthoringValidationReport(CanonicalModel):
    schema_version: str
    document_schema_version: str | None
    valid: bool
    overall_status: CapabilityStatus
    diagnostics: tuple[AuthoringDiagnostic, ...]
