from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping, TYPE_CHECKING

from scenarioforge.core.canonical import CanonicalModel, canonical_digest, freeze_json
from scenarioforge.core.models import CompilationStatus, CompileBundle

if TYPE_CHECKING:
    from scenarioforge.authoring.preflight import PreflightResult


class ConfirmationError(RuntimeError):
    pass


class ConfirmationMismatch(ConfirmationError):
    pass


class ConfirmationStale(ConfirmationError):
    pass


class ConfirmationReplay(ConfirmationError):
    pass


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("confirmation clock must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _authorization_subject(
    *,
    normalized_scenario_spec: Mapping[str, Any],
    backend_id: str,
    capability_report: Mapping[str, Any],
    validation_version: str,
) -> dict[str, str]:
    if not backend_id:
        raise ConfirmationMismatch("backend_id is required")
    if not validation_version:
        raise ConfirmationMismatch("validation_version is required")
    return {
        "normalized_scenario_spec_digest": canonical_digest(normalized_scenario_spec),
        "backend_id": backend_id,
        "capability_report_digest": canonical_digest(capability_report),
        "validation_version": validation_version,
    }


@dataclass(frozen=True)
class RunAuthorization(CanonicalModel):
    schema_version: str
    authorization_id: str
    issued_at: str
    expires_at: str
    normalized_scenario_spec_digest: str
    backend_id: str
    capability_report_digest: str
    validation_version: str


class RunAuthorizationAuthority:
    """Process-local server authority for short-lived, one-shot run grants."""

    def __init__(
        self,
        *,
        registered_backend_ids: tuple[str, ...],
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
        ttl_seconds: int = 300,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if not registered_backend_ids or any(not item for item in registered_backend_ids):
            raise ValueError("registered_backend_ids must not be empty")
        if len(set(registered_backend_ids)) != len(registered_backend_ids):
            raise ValueError("registered_backend_ids contains duplicates")
        self._registered_backend_ids = frozenset(registered_backend_ids)
        self._clock = clock or _utc_now
        self._id_factory = id_factory or (lambda: f"authorization-{uuid.uuid4().hex}")
        self._ttl = ttl_seconds
        self._issued: dict[str, str] = {}
        self._consumed: set[str] = set()
        self._invalidated: set[str] = set()

    def issue(
        self,
        *,
        normalized_scenario_spec: Mapping[str, Any],
        backend_id: str,
        capability_report: Mapping[str, Any],
        validation_version: str,
    ) -> RunAuthorization:
        if backend_id not in self._registered_backend_ids:
            raise ConfirmationMismatch(f"backend is not registered: {backend_id}")
        subject = _authorization_subject(
            normalized_scenario_spec=normalized_scenario_spec,
            backend_id=backend_id,
            capability_report=capability_report,
            validation_version=validation_version,
        )
        now = self._clock()
        authorization = RunAuthorization(
            schema_version="scenarioforge.run-authorization/v1",
            authorization_id=self._id_factory(),
            issued_at=_timestamp(now),
            expires_at=_timestamp(now + timedelta(seconds=self._ttl)),
            **subject,
        )
        if (
            authorization.authorization_id in self._issued
            or authorization.authorization_id in self._consumed
            or authorization.authorization_id in self._invalidated
        ):
            raise ConfirmationMismatch("authorization identity collision")
        self._issued[authorization.authorization_id] = authorization.digest
        return authorization

    def consume(
        self,
        authorization: RunAuthorization,
        *,
        normalized_scenario_spec: Mapping[str, Any],
        backend_id: str,
        capability_report: Mapping[str, Any],
        validation_version: str,
    ) -> RunAuthorization:
        authorization_id = authorization.authorization_id
        if authorization_id in self._consumed or authorization_id in self._invalidated:
            raise ConfirmationReplay("authorization was already consumed or invalidated")
        recorded = self._issued.get(authorization_id)
        if recorded != authorization.digest:
            self._invalidated.add(authorization_id)
            raise ConfirmationMismatch("authorization was not issued by this authority")
        try:
            expires_at = _parse_timestamp(authorization.expires_at)
        except ValueError as error:
            self._invalidated.add(authorization_id)
            raise ConfirmationMismatch("authorization expiry is invalid") from error
        if self._clock() >= expires_at:
            self._invalidated.add(authorization_id)
            raise ConfirmationStale("authorization expired")
        expected = _authorization_subject(
            normalized_scenario_spec=normalized_scenario_spec,
            backend_id=backend_id,
            capability_report=capability_report,
            validation_version=validation_version,
        )
        actual = {key: getattr(authorization, key) for key in expected}
        if actual != expected:
            self._invalidated.add(authorization_id)
            raise ConfirmationMismatch("authorization binding changed; revalidation is required")
        self._consumed.add(authorization_id)
        return authorization


def confirmation_subject(
    preflight: PreflightResult,
    *,
    run_id: str,
    attempt_id: str,
) -> dict[str, str]:
    report = preflight.report
    if None in {report.adapter_id, report.adapter_version, report.adapter_digest}:
        raise ConfirmationMismatch("preflight lacks complete adapter identity")
    return {
        "run_id": run_id,
        "attempt_id": attempt_id,
        "revision_id": preflight.revision.revision_id,
        "revision_digest": preflight.revision.canonical_digest,
        "scenario_instance_digest": preflight.scenario_instance.digest,
        "compile_report_digest": report.digest,
        "capability_descriptor_digest": preflight.capabilities.digest,
        "adapter_id": str(report.adapter_id),
        "adapter_version": str(report.adapter_version),
        "adapter_digest": str(report.adapter_digest),
    }


@dataclass(frozen=True)
class LossyConfirmation(CanonicalModel):
    schema_version: str
    confirmation_id: str
    actor: str
    issued_at: str
    expires_at: str
    run_id: str
    attempt_id: str
    revision_id: str
    revision_digest: str
    scenario_instance_digest: str
    compile_report_digest: str
    capability_descriptor_digest: str
    adapter_id: str
    adapter_version: str
    adapter_digest: str
    run_manifest_binding_digest: str


class LossyConfirmationAuthority:
    """Process-local, one-shot authority for the local operator confirmation."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
        ttl_seconds: int = 300,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._clock = clock or _utc_now
        self._id_factory = id_factory or (lambda: f"confirmation-{uuid.uuid4().hex}")
        self._ttl = ttl_seconds
        self._issued: dict[str, str] = {}
        self._consumed: set[str] = set()

    def issue(
        self,
        preflight: PreflightResult,
        *,
        run_id: str,
        attempt_id: str,
        actor: str = "local_operator",
    ) -> LossyConfirmation:
        if actor != "local_operator":
            raise ConfirmationMismatch("lossy confirmation requires local_operator")
        if preflight.status is not CompilationStatus.LOSSY:
            raise ConfirmationMismatch("confirmation can bind only a lossy preflight")
        now = self._clock()
        subject = confirmation_subject(preflight, run_id=run_id, attempt_id=attempt_id)
        confirmation = LossyConfirmation(
            schema_version="scenarioforge.lossy-confirmation/v1",
            confirmation_id=self._id_factory(),
            actor=actor,
            issued_at=_timestamp(now),
            expires_at=_timestamp(now + timedelta(seconds=self._ttl)),
            **subject,
            run_manifest_binding_digest=canonical_digest(subject),
        )
        if confirmation.confirmation_id in self._issued:
            raise ConfirmationMismatch("confirmation identity collision")
        self._issued[confirmation.confirmation_id] = confirmation.digest
        return confirmation

    def consume(
        self,
        confirmation: LossyConfirmation,
        *,
        preflight: PreflightResult,
        run_id: str,
        attempt_id: str,
    ) -> CompileBundle:
        expected = confirmation_subject(preflight, run_id=run_id, attempt_id=attempt_id)
        actual = {
            key: getattr(confirmation, key)
            for key in expected
        }
        if actual != expected or confirmation.run_manifest_binding_digest != canonical_digest(expected):
            raise ConfirmationMismatch("confirmation binding does not match preflight or run")
        recorded = self._issued.get(confirmation.confirmation_id)
        if recorded != confirmation.digest:
            raise ConfirmationMismatch("confirmation was not issued by this authority")
        if confirmation.confirmation_id in self._consumed:
            raise ConfirmationReplay("confirmation was already consumed")
        if self._clock() > _parse_timestamp(confirmation.expires_at):
            raise ConfirmationStale("confirmation expired")
        self._consumed.add(confirmation.confirmation_id)
        return replace(
            preflight.bundle,
            confirmation=freeze_json(confirmation.to_dict()),
        )


def validate_bound_confirmation(bundle: CompileBundle, *, run_id: str, attempt_id: str) -> None:
    value = bundle.confirmation
    instance = bundle.scenario_instance
    report = bundle.report
    if value is None or instance.revision_id is None or instance.revision_digest is None:
        raise ConfirmationMismatch("lossy run lacks a revision-bound confirmation")
    expected = {
        "run_id": run_id,
        "attempt_id": attempt_id,
        "revision_id": instance.revision_id,
        "revision_digest": instance.revision_digest,
        "scenario_instance_digest": instance.digest,
        "compile_report_digest": report.digest,
        "capability_descriptor_digest": report.capability_descriptor_digest,
        "adapter_id": report.adapter_id,
        "adapter_version": report.adapter_version,
        "adapter_digest": report.adapter_digest,
    }
    if any(value.get(key) != expected_value for key, expected_value in expected.items()):
        raise ConfirmationMismatch("lossy confirmation binding mismatch")
    if value.get("actor") != "local_operator":
        raise ConfirmationMismatch("lossy confirmation requires local_operator")
    if value.get("run_manifest_binding_digest") != canonical_digest(expected):
        raise ConfirmationMismatch("lossy confirmation manifest binding mismatch")


__all__ = [
    "ConfirmationError",
    "ConfirmationMismatch",
    "ConfirmationReplay",
    "ConfirmationStale",
    "LossyConfirmation",
    "LossyConfirmationAuthority",
    "RunAuthorization",
    "RunAuthorizationAuthority",
    "confirmation_subject",
    "validate_bound_confirmation",
]
