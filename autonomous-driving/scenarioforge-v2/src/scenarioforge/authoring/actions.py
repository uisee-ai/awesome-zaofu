from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping

from scenarioforge.core.strict_json import strict_loads
from scenarioforge.runtime.confirmation import (
    ConfirmationMismatch,
    RunAuthorization,
    RunAuthorizationAuthority,
)

from .p1_preflight import AuthoringPreflightReport
from .scenario_spec import NormalizedScenarioSpec


class AuthoringActionError(RuntimeError):
    pass


_CONTENT_REFERENCE = re.compile(r"^content://sha256/([0-9a-f]{64})$")
_RESOURCE_MEDIA_TYPES = frozenset(
    {
        "application/json",
        "image/png",
        "model/gltf-binary",
        "model/gltf+json",
    }
)


class ControlledResourceRegistry:
    def __init__(
        self,
        *,
        builtin_ids: tuple[str, ...],
        content_digests: tuple[str, ...] = (),
        allowed_media_types: frozenset[str] = _RESOURCE_MEDIA_TYPES,
        max_upload_bytes: int = 8 * 1024 * 1024,
    ) -> None:
        if max_upload_bytes <= 0:
            raise ValueError("max_upload_bytes must be positive")
        if any(not item.startswith("builtin://") for item in builtin_ids):
            raise ValueError("built-in resource IDs must use builtin://")
        if any(
            re.fullmatch(r"[0-9a-f]{64}", item) is None
            for item in content_digests
        ):
            raise ValueError("content digests must be lowercase SHA-256 values")
        self._builtin_ids = frozenset(builtin_ids)
        self._content_digests = set(content_digests)
        self._allowed_media_types = allowed_media_types
        self._max_upload_bytes = max_upload_bytes

    def register_upload(
        self,
        payload: bytes,
        *,
        media_type: str,
        expected_digest: str,
    ) -> str:
        if media_type not in self._allowed_media_types:
            raise AuthoringActionError("resource media type is not allowlisted")
        if (
            not isinstance(payload, bytes)
            or not payload
            or len(payload) > self._max_upload_bytes
        ):
            raise AuthoringActionError("resource size is outside the controlled limit")
        self._validate_type(payload, media_type)
        digest = hashlib.sha256(payload).hexdigest()
        if (
            not re.fullmatch(r"[0-9a-f]{64}", expected_digest)
            or digest != expected_digest
        ):
            raise AuthoringActionError("resource integrity digest does not match")
        self._content_digests.add(digest)
        return f"content://sha256/{digest}"

    @staticmethod
    def _validate_type(payload: bytes, media_type: str) -> None:
        valid = False
        if media_type == "image/png":
            valid = payload.startswith(b"\x89PNG\r\n\x1a\n")
        elif media_type == "model/gltf-binary":
            valid = len(payload) >= 12 and payload.startswith(b"glTF")
        elif media_type in {"application/json", "model/gltf+json"}:
            try:
                value = strict_loads(payload)
            except (TypeError, ValueError):
                value = None
            valid = isinstance(value, Mapping)
        if not valid:
            raise AuthoringActionError(
                "resource content does not match its allowlisted media type"
            )

    def resolve(self, reference: str) -> str:
        if reference in self._builtin_ids:
            return reference
        match = _CONTENT_REFERENCE.fullmatch(reference)
        if match is not None and match.group(1) in self._content_digests:
            return reference
        raise AuthoringActionError("resource is not a registered controlled resource")


class AuthoringActionService:
    def __init__(
        self,
        *,
        registered_adapter_ids: tuple[str, ...],
        authority: RunAuthorizationAuthority | None = None,
    ) -> None:
        self._registered = frozenset(registered_adapter_ids)
        self._authority = authority or RunAuthorizationAuthority(
            registered_backend_ids=registered_adapter_ids
        )

    @staticmethod
    def _assert_binding(
        spec: NormalizedScenarioSpec,
        report: AuthoringPreflightReport,
        backend_id: str,
    ) -> None:
        if spec.content_digest != report.normalized_scenario_spec_digest:
            raise ConfirmationMismatch(
                "preflight binding changed; revalidation is required"
            )
        if backend_id != report.backend_id:
            raise ConfirmationMismatch("backend binding changed; revalidation is required")
        if report.blocked:
            raise AuthoringActionError(
                f"preflight {report.status.value} blocks confirmation"
            )
        if not spec.ready_for_confirmation:
            raise AuthoringActionError("missing fields must be corrected before confirmation")

    def confirm(
        self,
        spec: NormalizedScenarioSpec,
        report: AuthoringPreflightReport,
        *,
        backend_id: str | None = None,
    ) -> RunAuthorization:
        selected = report.backend_id if backend_id is None else backend_id
        if selected not in self._registered:
            raise AuthoringActionError(f"adapter is not registered: {selected}")
        self._assert_binding(spec, report, selected)
        return self._authority.issue(
            normalized_scenario_spec=spec.content,
            backend_id=selected,
            capability_report={
                "digest": report.capability_report_digest,
                "status": report.status.value,
                "disclosures": [item.to_dict() for item in report.disclosures],
            },
            validation_version=report.validation_version,
        )

    def authorize_run(
        self,
        authorization: RunAuthorization,
        spec: NormalizedScenarioSpec,
        report: AuthoringPreflightReport,
        *,
        backend_id: str | None = None,
    ) -> RunAuthorization:
        selected = report.backend_id if backend_id is None else backend_id
        if selected not in self._registered:
            raise AuthoringActionError(f"adapter is not registered: {selected}")
        self._assert_binding(spec, report, selected)
        return self._authority.consume(
            authorization,
            normalized_scenario_spec=spec.content,
            backend_id=selected,
            capability_report={
                "digest": report.capability_report_digest,
                "status": report.status.value,
                "disclosures": [item.to_dict() for item in report.disclosures],
            },
            validation_version=report.validation_version,
        )


__all__ = [
    "AuthoringActionError",
    "AuthoringActionService",
    "ControlledResourceRegistry",
]
