from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any

from scenarioforge.core.canonical import (
    CanonicalModel,
    JSONValue,
    canonical_digest,
    freeze_json,
    thaw_json,
)

from .scenario_spec import NormalizedScenarioSpec
from .models import CapabilityStatus
from .validation import validate_authoring_spec


VALIDATION_VERSION = "scenarioforge.authoring-validation/v1"


class PreflightContractError(ValueError):
    pass


class PreflightStatus(str, Enum):
    ERROR = "error"
    UNSUPPORTED = "unsupported"
    LOSSY = "lossy"
    WARNING = "warning"
    EXACT = "exact"


@dataclass(frozen=True)
class SemanticDisclosure(CanonicalModel):
    path: str
    source_semantics: str
    degraded_semantics: str
    impact: str


@dataclass(frozen=True)
class AuthoringPreflightReport(CanonicalModel):
    schema_version: str
    normalized_scenario_spec_digest: str
    backend_id: str
    capability_report_digest: str
    validation_version: str
    status: PreflightStatus
    blocked: bool
    requires_confirmation: bool
    diagnostics: tuple[Mapping[str, JSONValue], ...]
    disclosures: tuple[SemanticDisclosure, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "diagnostics",
            tuple(freeze_json(item) for item in self.diagnostics),
        )


def _disclosures(diagnostics: Sequence[object]) -> tuple[SemanticDisclosure, ...]:
    result: list[SemanticDisclosure] = []
    required = {"path", "source_semantics", "degraded_semantics", "impact"}
    for diagnostic in diagnostics:
        if not isinstance(diagnostic, Mapping) or not required <= set(diagnostic):
            raise PreflightContractError(
                "lossy or unsupported diagnostics require path, source semantics, "
                "degraded semantics and impact"
            )
        result.append(
            SemanticDisclosure(
                path=str(diagnostic["path"]),
                source_semantics=str(diagnostic["source_semantics"]),
                degraded_semantics=str(diagnostic["degraded_semantics"]),
                impact=str(diagnostic["impact"]),
            )
        )
    return tuple(result)


def _validation_disclosures(
    diagnostics: Sequence[Mapping[str, Any]],
) -> tuple[SemanticDisclosure, ...]:
    return tuple(
        SemanticDisclosure(
            path=str(item["path"]),
            source_semantics=str(item["capability"]),
            degraded_semantics=str(item["suggestion"]),
            impact=str(item["reason"]),
        )
        for item in diagnostics
        if item.get("status") == CapabilityStatus.LOSSY.value
    )


def evaluate_preflight(
    normalized_spec: NormalizedScenarioSpec,
    *,
    backend_id: str,
    capability_report: Mapping[str, Any],
    warnings: Sequence[Mapping[str, Any]] = (),
) -> AuthoringPreflightReport:
    if not backend_id:
        raise PreflightContractError("backend_id is required")
    if capability_report.get("backend_id") != backend_id:
        raise PreflightContractError("capability report backend does not match selection")
    validation = validate_authoring_spec(thaw_json(normalized_spec.content))
    validation_diagnostics = tuple(item.to_dict() for item in validation.diagnostics)
    capability_diagnostics = capability_report.get("diagnostics", ())
    if not isinstance(capability_diagnostics, (list, tuple)):
        raise PreflightContractError("capability diagnostics must be an array")
    if normalized_spec.missing_fields or not validation.valid:
        status = PreflightStatus.ERROR
        diagnostics = validation_diagnostics
        disclosures: tuple[SemanticDisclosure, ...] = ()
    else:
        capability_status = capability_report.get("status")
        authoring_disclosures = _validation_disclosures(validation_diagnostics)
        if capability_status == "unsupported":
            status = PreflightStatus.UNSUPPORTED
            disclosures = (*authoring_disclosures, *_disclosures(capability_diagnostics))
        elif capability_status == "lossy":
            if not capability_diagnostics:
                raise PreflightContractError(
                    "lossy capability status requires semantic disclosures"
                )
            status = PreflightStatus.LOSSY
            disclosures = (*authoring_disclosures, *_disclosures(capability_diagnostics))
        elif capability_status == "exact" and authoring_disclosures:
            status = PreflightStatus.LOSSY
            disclosures = authoring_disclosures
        elif capability_status == "exact" and warnings:
            status = PreflightStatus.WARNING
            disclosures = ()
        elif capability_status == "exact":
            status = PreflightStatus.EXACT
            disclosures = ()
        else:
            raise PreflightContractError("capability status is invalid")
        validation_lossy = tuple(
            item
            for item in validation_diagnostics
            if item.get("status") == CapabilityStatus.LOSSY.value
        )
        diagnostics = tuple(
            dict(item)
            for item in (*validation_lossy, *capability_diagnostics, *warnings)
            if isinstance(item, Mapping)
        )
    return AuthoringPreflightReport(
        schema_version="scenarioforge.authoring-preflight/v2",
        normalized_scenario_spec_digest=normalized_spec.content_digest,
        backend_id=backend_id,
        capability_report_digest=canonical_digest(capability_report),
        validation_version=VALIDATION_VERSION,
        status=status,
        blocked=status in {PreflightStatus.ERROR, PreflightStatus.UNSUPPORTED},
        requires_confirmation=status in {PreflightStatus.WARNING, PreflightStatus.LOSSY},
        diagnostics=diagnostics,
        disclosures=disclosures,
    )


__all__ = [
    "AuthoringPreflightReport",
    "PreflightContractError",
    "PreflightStatus",
    "SemanticDisclosure",
    "VALIDATION_VERSION",
    "evaluate_preflight",
]
