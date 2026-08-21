from __future__ import annotations

import base64
import os
import re
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import quote

from scenarioforge.core import canonical_bytes, strict_loads
from scenarioforge.core.canonical import CanonicalModel, JSONValue, freeze_json, thaw_json

from .errors import SecurityViolation


_KIND = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_ABSOLUTE_PATH = re.compile(r"(?<![A-Za-z0-9+.-])/(?:[^\s,;\"']+)")
_FORBIDDEN_KEY_FRAGMENTS = (
    "secret",
    "token",
    "cookie",
    "authorization",
    "password",
    "environment_value",
    "file_content",
)


def _freeze_object(value: Mapping[str, Any], label: str) -> Mapping[str, JSONValue]:
    frozen = freeze_json(value)
    if not isinstance(frozen, Mapping):
        raise TypeError(f"{label} must be a JSON object")
    return frozen


@dataclass(frozen=True)
class ArtifactAllowlist(CanonicalModel):
    schema_version: str
    artifact_kind: str
    allowed_fields: tuple[str, ...]
    required_fields: tuple[str, ...]
    approved_capture_layers: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema_version != "scenarioforge.artifact-allowlist/v1":
            raise ValueError("artifact allowlist schema version is unsupported")
        if not _KIND.fullmatch(self.artifact_kind):
            raise ValueError("artifact_kind is invalid")
        for label, values in (
            ("allowed_fields", self.allowed_fields),
            ("required_fields", self.required_fields),
            ("approved_capture_layers", self.approved_capture_layers),
        ):
            if len(values) != len(set(values)) or any(not value for value in values):
                raise ValueError(f"{label} contains empty or duplicate values")
        if not self.allowed_fields:
            raise ValueError("allowed_fields must not be empty")
        if not set(self.required_fields) <= set(self.allowed_fields):
            raise ValueError("required_fields must be explicitly allowlisted")


@dataclass(frozen=True)
class SafeArtifact(CanonicalModel):
    schema_version: str
    artifact_kind: str
    allowlist_schema_version: str
    allowlist_digest: str
    payload: Mapping[str, JSONValue]

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", _freeze_object(self.payload, "payload"))


@dataclass(frozen=True)
class CaptureAuthorization(CanonicalModel):
    schema_version: str
    artifact_kind: str
    allowlist_digest: str
    capture_layers: tuple[str, ...]


class ArtifactAllowlistRegistry(CanonicalModel):
    def __init__(self, policies: tuple[ArtifactAllowlist, ...]) -> None:
        if not policies:
            raise ValueError("at least one artifact policy is required")
        by_kind = {policy.artifact_kind: policy for policy in policies}
        if len(by_kind) != len(policies):
            raise ValueError("artifact policy kinds must be unique")
        self._policies = policies
        self._by_kind = by_kind

    def policy(self, artifact_kind: str) -> ArtifactAllowlist:
        try:
            return self._by_kind[artifact_kind]
        except KeyError as error:
            raise SecurityViolation(
                f"artifact kind has no registered allowlist: {artifact_kind}",
                code="artifact_allowlist_violation",
            ) from error

    def kinds(self) -> tuple[str, ...]:
        return tuple(sorted(self._by_kind))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "scenarioforge.artifact-allowlist-registry/v1",
            "policies": [policy.to_dict() for policy in self._policies],
        }


def load_artifact_allowlists(path: Path | str) -> ArtifactAllowlistRegistry:
    try:
        value = strict_loads(Path(path).read_bytes())
    except (OSError, ValueError, TypeError) as error:
        raise SecurityViolation(
            "artifact allowlist registry cannot be loaded",
            code="artifact_allowlist_violation",
        ) from error
    if not isinstance(value, dict) or set(value) != {"schema_version", "policies"}:
        raise SecurityViolation(
            "artifact allowlist registry shape is invalid",
            code="artifact_allowlist_violation",
        )
    if value["schema_version"] != "scenarioforge.artifact-allowlist-registry/v1":
        raise SecurityViolation(
            "artifact allowlist registry version is unsupported",
            code="artifact_allowlist_violation",
        )
    raw_policies = value["policies"]
    if not isinstance(raw_policies, list):
        raise SecurityViolation(
            "artifact allowlist registry policies are invalid",
            code="artifact_allowlist_violation",
        )
    try:
        policies = tuple(
            ArtifactAllowlist(
                schema_version=str(item["schema_version"]),
                artifact_kind=str(item["artifact_kind"]),
                allowed_fields=tuple(item["allowed_fields"]),
                required_fields=tuple(item["required_fields"]),
                approved_capture_layers=tuple(item["approved_capture_layers"]),
            )
            for item in raw_policies
            if isinstance(item, dict)
        )
    except (KeyError, TypeError, ValueError) as error:
        raise SecurityViolation(
            "artifact allowlist registry policy is invalid",
            code="artifact_allowlist_violation",
        ) from error
    if len(policies) != len(raw_policies):
        raise SecurityViolation(
            "artifact allowlist registry policy is invalid",
            code="artifact_allowlist_violation",
        )
    return ArtifactAllowlistRegistry(policies)


def _field_paths(value: object, prefix: str = "") -> Iterable[str]:
    if isinstance(value, Mapping):
        if not value and prefix:
            yield prefix
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            yield from _field_paths(item, path)
    elif isinstance(value, (list, tuple)):
        if not value and prefix:
            yield prefix
        for item in value:
            yield from _field_paths(item, f"{prefix}[]")
    elif prefix:
        yield prefix


def _allowed_path(path: str, pattern: str) -> bool:
    if path == pattern:
        return True
    if pattern.endswith(".*"):
        prefix = pattern[:-2]
        return path == prefix or path.startswith(f"{prefix}.") or path.startswith(f"{prefix}[]")
    return False


def _forbidden_key(value: object, prefix: str = "") -> str | None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            path = f"{prefix}.{key}" if prefix else str(key)
            if any(fragment in normalized for fragment in _FORBIDDEN_KEY_FRAGMENTS):
                return path
            found = _forbidden_key(item, path)
            if found is not None:
                return found
    elif isinstance(value, (list, tuple)):
        for item in value:
            found = _forbidden_key(item, f"{prefix}[]")
            if found is not None:
                return found
    return None


def _validate_allowlist(payload: Mapping[str, Any], policy: ArtifactAllowlist) -> None:
    forbidden = _forbidden_key(payload)
    if forbidden is not None:
        raise SecurityViolation(
            f"artifact contains a forbidden field: {forbidden}",
            code="artifact_allowlist_violation",
        )
    for required in policy.required_fields:
        if required not in payload:
            raise SecurityViolation(
                f"artifact required field is missing: {required}",
                code="artifact_allowlist_violation",
            )
    for path in _field_paths(payload):
        if not any(_allowed_path(path, pattern) for pattern in policy.allowed_fields):
            raise SecurityViolation(
                f"artifact contains an unknown field: {path}",
                code="artifact_allowlist_violation",
            )


def _secret_variants(values: Iterable[str]) -> tuple[str, ...]:
    variants: set[str] = set()
    for value in values:
        if not value:
            continue
        encoded = value.encode("utf-8")
        variants.update(
            {
                value,
                quote(value, safe=""),
                base64.b64encode(encoded).decode("ascii"),
                encoded.hex(),
            }
        )
    return tuple(sorted(variants, key=lambda item: (-len(item), item)))


def _sanitize_path(match: re.Match[str], project_root: Path | None) -> str:
    raw = match.group(0)
    if raw.startswith("//"):
        return "<redacted-path>"
    if project_root is not None:
        try:
            relative = Path(raw).relative_to(project_root)
        except ValueError:
            pass
        else:
            return f"project://{relative.as_posix()}"
    return "<redacted-path>"


def _sanitize_string(value: str, variants: tuple[str, ...], project_root: Path | None) -> str:
    sanitized = value
    for variant in variants:
        sanitized = sanitized.replace(variant, "<redacted>")
    sanitized = _ABSOLUTE_PATH.sub(lambda match: _sanitize_path(match, project_root), sanitized)
    return sanitized


def _sanitize_value(value: object, variants: tuple[str, ...], project_root: Path | None) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _sanitize_value(item, variants, project_root)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize_value(item, variants, project_root) for item in value]
    if isinstance(value, str):
        return _sanitize_string(value, variants, project_root)
    return value


def _contains_variant(payload: bytes, variants: tuple[str, ...]) -> bool:
    return any(variant.encode("utf-8") in payload for variant in variants)


def sanitize_artifact(
    payload: Mapping[str, Any],
    *,
    policy: ArtifactAllowlist,
    sensitive_values: tuple[str, ...] = (),
    environment_values: tuple[str, ...] = (),
    controlled_file_contents: tuple[str, ...] = (),
    project_root: Path | None = None,
) -> SafeArtifact:
    _validate_allowlist(payload, policy)
    variants = _secret_variants(
        (*sensitive_values, *environment_values, *controlled_file_contents)
    )
    safe_payload = _sanitize_value(payload, variants, Path(project_root) if project_root else None)
    assert isinstance(safe_payload, dict)
    serialized = canonical_bytes(safe_payload)
    if _contains_variant(serialized, variants):
        raise SecurityViolation(
            "marked secret remains after pre-write redaction",
            code="marked_secret_detected",
        )
    return SafeArtifact(
        schema_version="scenarioforge.safe-artifact/v1",
        artifact_kind=policy.artifact_kind,
        allowlist_schema_version=policy.schema_version,
        allowlist_digest=policy.digest,
        payload=safe_payload,
    )


def write_safe_artifact(
    path: Path | str,
    payload: Mapping[str, Any],
    *,
    policy: ArtifactAllowlist,
    sensitive_values: tuple[str, ...] = (),
    environment_values: tuple[str, ...] = (),
    controlled_file_contents: tuple[str, ...] = (),
    project_root: Path | None = None,
) -> SafeArtifact:
    safe = sanitize_artifact(
        payload,
        policy=policy,
        sensitive_values=sensitive_values,
        environment_values=environment_values,
        controlled_file_contents=controlled_file_contents,
        project_root=project_root,
    )
    destination = Path(path)
    if destination.parent.is_symlink() or not destination.parent.is_dir():
        raise SecurityViolation(
            "artifact parent is not a regular directory",
            code="path_boundary_escape",
        )
    data = canonical_bytes(safe)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(destination, flags, 0o600)
    try:
        offset = 0
        while offset < len(data):
            written = os.write(descriptor, data[offset:])
            if written <= 0:
                raise OSError("short write")
            offset += written
        os.fsync(descriptor)
    except BaseException:
        os.close(descriptor)
        destination.unlink(missing_ok=True)
        raise
    else:
        os.close(descriptor)
    return safe


def authorize_capture(
    *,
    policy: ArtifactAllowlist,
    capture_layers: tuple[str, ...],
    render_state: Mapping[str, Any],
    sensitive_values: tuple[str, ...] = (),
    environment_values: tuple[str, ...] = (),
    controlled_file_contents: tuple[str, ...] = (),
) -> CaptureAuthorization:
    if not capture_layers or len(capture_layers) != len(set(capture_layers)):
        raise SecurityViolation(
            "capture layers are empty or duplicated",
            code="capture_allowlist_violation",
        )
    unapproved = sorted(set(capture_layers) - set(policy.approved_capture_layers))
    if unapproved:
        raise SecurityViolation(
            f"capture layer is not approved: {', '.join(unapproved)}",
            code="capture_allowlist_violation",
        )
    if _forbidden_key(render_state) is not None:
        raise SecurityViolation(
            "forbidden render state was present before capture",
            code="marked_secret_detected",
        )
    variants = _secret_variants(
        (*sensitive_values, *environment_values, *controlled_file_contents)
    )
    if _contains_variant(canonical_bytes(render_state), variants):
        raise SecurityViolation(
            "marked secret was present before capture",
            code="marked_secret_detected",
        )
    return CaptureAuthorization(
        schema_version="scenarioforge.capture-authorization/v1",
        artifact_kind=policy.artifact_kind,
        allowlist_digest=policy.digest,
        capture_layers=capture_layers,
    )


def _scan_payload(payload: bytes, variants: tuple[str, ...], label: str) -> None:
    if _contains_variant(payload, variants):
        raise SecurityViolation(
            f"marked secret detected in governed artifact: {label}",
            code="marked_secret_detected",
        )


def _scan_zip(path: Path, variants: tuple[str, ...], max_bytes: int) -> None:
    total = 0
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            member = Path(info.filename)
            if member.is_absolute() or ".." in member.parts:
                raise SecurityViolation(
                    "trace archive contains an unsafe member",
                    code="artifact_allowlist_violation",
                )
            total += info.file_size
            if total > max_bytes:
                raise SecurityViolation(
                    "trace archive exceeds scan limit",
                    code="artifact_size_limit_exceeded",
                )
            _scan_payload(info.filename.encode("utf-8"), variants, f"{path.name}:{info.filename}")
            if not info.is_dir():
                _scan_payload(archive.read(info), variants, f"{path.name}:{info.filename}")


def assert_no_marked_secrets(
    root: Path | str,
    *,
    sensitive_values: tuple[str, ...],
    max_file_bytes: int = 104_857_600,
) -> tuple[str, ...]:
    variants = _secret_variants(sensitive_values)
    target = Path(root)
    if target.is_symlink():
        raise SecurityViolation("artifact scan root is a link", code="link_or_special_file")
    paths = [target] if target.is_file() else sorted(path for path in target.rglob("*") if path.is_file())
    scanned: list[str] = []
    for path in paths:
        mode = path.lstat().st_mode
        if path.is_symlink() or not stat.S_ISREG(mode):
            raise SecurityViolation("governed artifact is a link or special file", code="link_or_special_file")
        relative = path.name if target.is_file() else path.relative_to(target).as_posix()
        if path.stat().st_size > max_file_bytes:
            raise SecurityViolation(
                "governed artifact exceeds scan limit",
                code="artifact_size_limit_exceeded",
            )
        _scan_payload(relative.encode("utf-8"), variants, relative)
        if zipfile.is_zipfile(path):
            _scan_zip(path, variants, max_file_bytes)
        else:
            _scan_payload(path.read_bytes(), variants, relative)
        scanned.append(relative)
    return tuple(scanned)


__all__ = [
    "ArtifactAllowlist",
    "ArtifactAllowlistRegistry",
    "CaptureAuthorization",
    "SafeArtifact",
    "assert_no_marked_secrets",
    "authorize_capture",
    "load_artifact_allowlists",
    "sanitize_artifact",
    "write_safe_artifact",
]
