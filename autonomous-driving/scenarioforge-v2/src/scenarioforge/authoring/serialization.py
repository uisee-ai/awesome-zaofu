from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Never, cast

import yaml
from yaml.events import (
    AliasEvent,
    CollectionEndEvent,
    CollectionStartEvent,
    DocumentStartEvent,
)
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from scenarioforge.core.canonical import (
    JSONValue,
    canonical_bytes,
    freeze_json,
    thaw_json,
)
from scenarioforge.core.strict_json import StrictJSONError, strict_loads

from .models import AuthoringValidationReport
from .validation import validate_authoring_spec


AuthoringFormat = Literal["json", "yaml"]


@dataclass(frozen=True)
class SerializationLimits:
    """Budgets shared by strict JSON and the safe YAML subset."""

    byte_limit: int = 65_536
    max_depth: int = 32
    max_parse_events: int = 8_192
    max_object_members: int = 128
    max_array_items: int = 256
    max_string_bytes: int = 8_192
    max_absolute_number: float = 2_147_483_647.0


@dataclass(frozen=True)
class ImportedAuthoringDocument:
    source_format: AuthoringFormat
    value: JSONValue
    validation: AuthoringValidationReport
    raw_digest: str
    canonical_digest: str
    canonical_payload: bytes


_ERROR_MESSAGES = {
    "alias_forbidden": "YAML aliases are not permitted",
    "anchor_forbidden": "YAML anchors are not permitted",
    "array_items_exceeded": "an array exceeds the configured item budget",
    "byte_limit_exceeded": "content exceeds the configured byte budget",
    "compressed_content_forbidden": "compressed or archive content is not permitted",
    "content_only_required": "only inline authoring content is accepted",
    "duplicate_key": "duplicate mapping keys are not permitted",
    "invalid_format": "the requested authoring format is not supported",
    "invalid_json": "content is not strict JSON",
    "invalid_utf8": "content is not valid UTF-8",
    "invalid_yaml": "content is not valid safe YAML",
    "max_depth_exceeded": "content exceeds the configured nesting budget",
    "merge_key_forbidden": "YAML merge keys are not permitted",
    "multiple_documents_forbidden": "exactly one YAML document is required",
    "non_finite_number": "numbers must be finite",
    "non_json_scalar": "YAML contains a scalar outside the JSON data model",
    "number_range_exceeded": "a number exceeds the configured finite range",
    "object_members_exceeded": "an object exceeds the configured member budget",
    "parse_events_exceeded": "content exceeds the configured parse-event budget",
    "schema_validation_failed": "content does not satisfy the authoring contract",
    "string_bytes_exceeded": "a string exceeds the configured byte budget",
    "tag_forbidden": "YAML tags are not permitted",
}


class SerializationError(ValueError):
    """Stable, sanitized import/export failure safe for user-facing transport."""

    def __init__(self, *, stage: str, code: str, path: str = "$") -> None:
        super().__init__(_ERROR_MESSAGES[code])
        self.stage = stage
        self.code = code
        self.path = path


_WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")
_REFERENCE_SUFFIXES = (
    ".json",
    ".yaml",
    ".yml",
    ".zip",
    ".gz",
    ".bz2",
    ".xz",
)
_ARCHIVE_PREFIXES = (
    b"PK\x03\x04",
    b"PK\x05\x06",
    b"PK\x07\x08",
    b"\x1f\x8b",
    b"BZh",
    b"\xfd7zXZ\x00",
)
_JSON_SCALAR_TAGS = {
    "tag:yaml.org,2002:null",
    "tag:yaml.org,2002:bool",
    "tag:yaml.org,2002:int",
    "tag:yaml.org,2002:float",
    "tag:yaml.org,2002:str",
}


class _NoAliasSafeDumper(yaml.SafeDumper):
    def ignore_aliases(self, data: Any) -> bool:
        return True


def _raise(*, stage: str, code: str, path: str = "$") -> Never:
    raise SerializationError(stage=stage, code=code, path=path)


def _normalize_format(format: str) -> AuthoringFormat:
    if format not in {"json", "yaml"}:
        _raise(stage="content_boundary", code="invalid_format")
    return cast(AuthoringFormat, format)


def _looks_like_reference(value: str) -> bool:
    stripped = value.strip()
    lowered = stripped.lower()
    if lowered.startswith(("file:", "http://", "https://")):
        return True
    if stripped.startswith(("/", "./", "../", "\\\\")):
        return True
    if _WINDOWS_ABSOLUTE.match(stripped):
        return True
    return "\n" not in stripped and lowered.endswith(_REFERENCE_SUFFIXES)


def _is_archive(payload: bytes) -> bool:
    return payload.startswith(_ARCHIVE_PREFIXES) or (
        len(payload) >= 262 and payload[257:262] == b"ustar"
    )


def _bounded_payload(
    payload: bytes | str,
    limits: SerializationLimits,
) -> bytes:
    if isinstance(payload, Path) or not isinstance(payload, (bytes, str)):
        _raise(stage="content_boundary", code="content_only_required")
    if isinstance(payload, str):
        if _looks_like_reference(payload):
            _raise(stage="content_boundary", code="content_only_required")
        encoded = payload.encode("utf-8")
    else:
        encoded = payload
    if len(encoded) > limits.byte_limit:
        _raise(stage="resource_budget", code="byte_limit_exceeded")
    if _is_archive(encoded):
        _raise(stage="content_boundary", code="compressed_content_forbidden")
    return encoded


def _path(parent: str, part: str | int) -> str:
    if isinstance(part, int):
        return f"{parent}[{part}]"
    return f"{parent}.{part}"


def _walk_limits(
    value: Any,
    limits: SerializationLimits,
    *,
    path: str = "$",
    depth: int = 1,
) -> int:
    if depth > limits.max_depth:
        _raise(stage="resource_budget", code="max_depth_exceeded", path=path)
    event_count = 1
    if isinstance(value, Mapping):
        if len(value) > limits.max_object_members:
            _raise(stage="resource_budget", code="object_members_exceeded", path=path)
        for key, item in value.items():
            if not isinstance(key, str):
                _raise(stage="resource_budget", code="non_json_scalar", path=path)
            item_path = _path(path, key)
            if len(key.encode("utf-8")) > limits.max_string_bytes:
                _raise(
                    stage="resource_budget",
                    code="string_bytes_exceeded",
                    path=item_path,
                )
            event_count += _walk_limits(
                item,
                limits,
                path=item_path,
                depth=depth + 1,
            )
    elif isinstance(value, (list, tuple)):
        if len(value) > limits.max_array_items:
            _raise(stage="resource_budget", code="array_items_exceeded", path=path)
        for index, item in enumerate(value):
            event_count += _walk_limits(
                item,
                limits,
                path=_path(path, index),
                depth=depth + 1,
            )
    elif isinstance(value, str):
        if len(value.encode("utf-8")) > limits.max_string_bytes:
            _raise(stage="resource_budget", code="string_bytes_exceeded", path=path)
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(value):
            _raise(stage="resource_budget", code="non_finite_number", path=path)
        if abs(value) > limits.max_absolute_number:
            _raise(stage="resource_budget", code="number_range_exceeded", path=path)
    elif value is not None and not isinstance(value, bool):
        _raise(stage="resource_budget", code="non_json_scalar", path=path)
    return event_count


def _enforce_value_limits(value: Any, limits: SerializationLimits) -> None:
    if _walk_limits(value, limits) > limits.max_parse_events:
        _raise(stage="resource_budget", code="parse_events_exceeded")


def _load_json(payload: bytes) -> Any:
    try:
        return strict_loads(payload)
    except StrictJSONError as error:
        code = error.code
        if code not in {"duplicate_key", "non_finite_number", "invalid_utf8"}:
            code = "invalid_json"
        _raise(stage="strict_json", code=code, path=error.path)


def _scan_yaml(text: str, limits: SerializationLimits) -> None:
    event_count = 0
    document_count = 0
    depth = 0
    try:
        for event in yaml.parse(text, Loader=yaml.SafeLoader):
            event_count += 1
            if event_count > limits.max_parse_events:
                _raise(stage="resource_budget", code="parse_events_exceeded")
            if isinstance(event, AliasEvent):
                _raise(stage="safe_yaml", code="alias_forbidden")
            if getattr(event, "anchor", None) is not None:
                _raise(stage="safe_yaml", code="anchor_forbidden")
            if getattr(event, "tag", None) is not None:
                _raise(stage="safe_yaml", code="tag_forbidden")
            if isinstance(event, DocumentStartEvent):
                document_count += 1
                if document_count > 1:
                    _raise(stage="safe_yaml", code="multiple_documents_forbidden")
            if isinstance(event, CollectionStartEvent):
                depth += 1
                if depth > limits.max_depth:
                    _raise(stage="resource_budget", code="max_depth_exceeded")
            elif isinstance(event, CollectionEndEvent):
                depth -= 1
    except SerializationError:
        raise
    except (yaml.YAMLError, RecursionError) as error:
        raise SerializationError(stage="safe_yaml", code="invalid_yaml") from error


def _construct_yaml_node(node: Node, loader: yaml.SafeLoader) -> Any:
    if isinstance(node, MappingNode):
        result: dict[str, Any] = {}
        for key_node, value_node in node.value:
            if key_node.tag == "tag:yaml.org,2002:merge" or key_node.value == "<<":
                _raise(stage="safe_yaml", code="merge_key_forbidden")
            if (
                not isinstance(key_node, ScalarNode)
                or key_node.tag != "tag:yaml.org,2002:str"
            ):
                _raise(stage="safe_yaml", code="non_json_scalar")
            key = key_node.value
            if key in result:
                _raise(stage="safe_yaml", code="duplicate_key")
            result[key] = _construct_yaml_node(value_node, loader)
        return result
    if isinstance(node, SequenceNode):
        return [_construct_yaml_node(item, loader) for item in node.value]
    if isinstance(node, ScalarNode):
        if node.tag not in _JSON_SCALAR_TAGS:
            _raise(stage="safe_yaml", code="non_json_scalar")
        if node.tag == "tag:yaml.org,2002:str":
            return node.value
        value = loader.construct_object(node, deep=True)
        if isinstance(value, float) and not math.isfinite(value):
            _raise(stage="safe_yaml", code="non_finite_number")
        return value
    _raise(stage="safe_yaml", code="non_json_scalar")


def _load_yaml(payload: bytes, limits: SerializationLimits) -> Any:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise SerializationError(stage="safe_yaml", code="invalid_utf8") from error
    _scan_yaml(text, limits)
    try:
        documents = list(yaml.compose_all(text, Loader=yaml.SafeLoader))
    except (yaml.YAMLError, RecursionError) as error:
        raise SerializationError(stage="safe_yaml", code="invalid_yaml") from error
    if len(documents) != 1:
        _raise(stage="safe_yaml", code="multiple_documents_forbidden")
    node = documents[0]
    if node is None:
        return None
    loader = yaml.SafeLoader("")
    try:
        return _construct_yaml_node(node, loader)
    finally:
        loader.dispose()


def _validate_authoring(value: Any) -> AuthoringValidationReport:
    report = validate_authoring_spec(value)
    if not report.valid:
        path = report.diagnostics[0].path if report.diagnostics else "$"
        _raise(
            stage="authoring_validation",
            code="schema_validation_failed",
            path=path,
        )
    return report


def import_authoring(
    payload: bytes | str,
    *,
    format: str,
    limits: SerializationLimits | None = None,
) -> ImportedAuthoringDocument:
    """Import inline strict JSON or safe YAML through one authoring contract."""

    source_format = _normalize_format(format)
    effective_limits = limits or SerializationLimits()
    encoded = _bounded_payload(payload, effective_limits)
    if source_format == "json":
        value = _load_json(encoded)
    else:
        value = _load_yaml(encoded, effective_limits)
    _enforce_value_limits(value, effective_limits)
    validation = _validate_authoring(value)
    normalized = canonical_bytes(value)
    if len(normalized) > effective_limits.byte_limit:
        _raise(stage="resource_budget", code="byte_limit_exceeded")
    return ImportedAuthoringDocument(
        source_format=source_format,
        value=freeze_json(value),
        validation=validation,
        raw_digest=hashlib.sha256(encoded).hexdigest(),
        canonical_digest=hashlib.sha256(normalized).hexdigest(),
        canonical_payload=normalized,
    )


def _export_value(value: object) -> dict[str, Any]:
    if isinstance(value, ImportedAuthoringDocument):
        thawed = thaw_json(value.value)
    elif isinstance(value, Mapping):
        thawed = thaw_json(value)
    else:
        _raise(stage="content_boundary", code="content_only_required")
    if not isinstance(thawed, dict):
        _raise(stage="content_boundary", code="content_only_required")
    return thawed


def export_authoring(
    value: object,
    *,
    format: str,
    limits: SerializationLimits | None = None,
) -> bytes:
    """Return bounded bytes only; filesystem and URL destinations are absent."""

    target_format = _normalize_format(format)
    effective_limits = limits or SerializationLimits()
    exported_value = _export_value(value)
    _enforce_value_limits(exported_value, effective_limits)
    _validate_authoring(exported_value)
    normalized = canonical_bytes(exported_value)
    if target_format == "json":
        payload = normalized
    else:
        payload = yaml.dump(
            exported_value,
            Dumper=_NoAliasSafeDumper,
            allow_unicode=True,
            default_flow_style=False,
            line_break="\n",
            sort_keys=True,
        ).encode("utf-8")
        round_trip = _load_yaml(payload, effective_limits)
        _enforce_value_limits(round_trip, effective_limits)
        if canonical_bytes(round_trip) != normalized:
            _raise(stage="bounded_export", code="schema_validation_failed")
    if len(payload) > effective_limits.byte_limit:
        _raise(stage="bounded_export", code="byte_limit_exceeded")
    return payload


__all__ = [
    "AuthoringFormat",
    "ImportedAuthoringDocument",
    "SerializationError",
    "SerializationLimits",
    "export_authoring",
    "import_authoring",
]
