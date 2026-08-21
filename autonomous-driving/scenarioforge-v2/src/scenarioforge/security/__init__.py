"""Fail-closed local security boundaries for one ScenarioForge Worker."""

from .artifact_safety import (
    ArtifactAllowlist,
    ArtifactAllowlistRegistry,
    CaptureAuthorization,
    SafeArtifact,
    assert_no_marked_secrets,
    authorize_capture,
    load_artifact_allowlists,
    sanitize_artifact,
    write_safe_artifact,
)
from .boundaries import (
    ArtifactVerification,
    load_untrusted_scenario,
    validate_isolated_directories,
    verify_output_artifacts,
    verify_snapshot_binding,
)
from .environment import build_worker_environment
from .errors import SecurityViolation
from .redaction import SanitizedLog, redact_log
from .resources import (
    ResourceObservation,
    ResourcePolicy,
    enforce_resource_policy,
    observe_process_group,
)

__all__ = [
    "ArtifactAllowlist",
    "ArtifactAllowlistRegistry",
    "ArtifactVerification",
    "CaptureAuthorization",
    "ResourceObservation",
    "ResourcePolicy",
    "SecurityViolation",
    "SanitizedLog",
    "SafeArtifact",
    "assert_no_marked_secrets",
    "authorize_capture",
    "build_worker_environment",
    "enforce_resource_policy",
    "load_untrusted_scenario",
    "load_artifact_allowlists",
    "observe_process_group",
    "redact_log",
    "sanitize_artifact",
    "validate_isolated_directories",
    "verify_output_artifacts",
    "verify_snapshot_binding",
    "write_safe_artifact",
]
