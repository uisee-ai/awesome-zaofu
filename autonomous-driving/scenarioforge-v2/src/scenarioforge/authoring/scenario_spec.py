from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from scenarioforge.core.canonical import (
    CanonicalModel,
    JSONValue,
    canonical_bytes,
    canonical_digest,
    freeze_json,
    thaw_json,
)
from scenarioforge.core.strict_json import strict_loads

from .schema import AUTHORING_SCHEMA, AUTHORING_SCHEMA_VERSION


class ScenarioSpecError(ValueError):
    pass


class ValueSource(str, Enum):
    EXPLICIT = "explicit"
    INFERRED = "inferred"
    DEFAULT = "default"
    MISSING = "missing"


@dataclass(frozen=True)
class FieldAnnotation(CanonicalModel):
    path: str
    source: ValueSource


@dataclass(frozen=True)
class NormalizedScenarioSpec(CanonicalModel):
    """One canonical authoring value shared by JSON, form and Provider inputs."""

    schema_version: str
    content: Mapping[str, JSONValue]
    annotations: tuple[FieldAnnotation, ...]
    resolved_defaults: tuple[str, ...]
    missing_fields: tuple[str, ...]

    def __post_init__(self) -> None:
        frozen = freeze_json(self.content)
        if not isinstance(frozen, Mapping):
            raise ScenarioSpecError("ScenarioSpec content must be an object")
        object.__setattr__(self, "content", frozen)

    @property
    def content_digest(self) -> str:
        return canonical_digest(self.content)

    @property
    def digest(self) -> str:
        """The execution identity is the normalized content, never editor metadata."""
        return self.content_digest

    @property
    def canonical_json(self) -> str:
        return canonical_bytes(self.content).decode("utf-8")

    @property
    def ready_for_confirmation(self) -> bool:
        return not self.missing_fields


_DEFAULTS: dict[str, JSONValue] = {
    "$.schema_version": AUTHORING_SCHEMA_VERSION,
    "$.description": "",
    "$.seed": 0,
    "$.static_obstacles": (),
    "$.environment": {
        "weather": "clear",
        "time_of_day": "day",
        "road_surface": "dry",
        "visibility_m": 500.0,
    },
    "$.events": (),
    "$.parameters": (),
    "$.policy": {
        "id": "scenarioforge.deterministic-control",
        "version": "2.0.0",
        "config": {},
    },
}
_PATH_TOKEN = re.compile(r"\.([a-z][a-z0-9_]*)|\[([0-9]+)\]")


def _leaf_paths(value: Any, path: str = "$") -> set[str]:
    if isinstance(value, Mapping):
        if not value:
            return {path}
        paths: set[str] = set()
        for key, item in value.items():
            paths.update(_leaf_paths(item, f"{path}.{key}"))
        return paths
    if isinstance(value, (list, tuple)):
        if not value:
            return {path}
        paths = set()
        for index, item in enumerate(value):
            paths.update(_leaf_paths(item, f"{path}[{index}]"))
        return paths
    return {path}


def _parts(path: str) -> tuple[str | int, ...]:
    if not isinstance(path, str) or not path.startswith("$"):
        raise ScenarioSpecError("field path must start with $")
    parts: list[str | int] = []
    offset = 1
    for match in _PATH_TOKEN.finditer(path, offset):
        if match.start() != offset:
            raise ScenarioSpecError(f"invalid field path: {path}")
        field, index = match.groups()
        parts.append(field if field is not None else int(index))
        offset = match.end()
    if offset != len(path) or not parts:
        raise ScenarioSpecError(f"invalid field path: {path}")
    return tuple(parts)


def _contains(value: object, path: str) -> bool:
    current = value
    for part in _parts(path):
        if isinstance(part, str) and isinstance(current, Mapping) and part in current:
            current = current[part]
        elif isinstance(part, int) and isinstance(current, list) and part < len(current):
            current = current[part]
        else:
            return False
    return True


def _set(value: dict[str, Any], path: str, item: Any) -> None:
    parts = _parts(path)
    current: Any = value
    for part in parts[:-1]:
        if isinstance(part, str) and isinstance(current, dict):
            current = current.setdefault(part, {})
        elif isinstance(part, int) and isinstance(current, list) and part < len(current):
            current = current[part]
        else:
            raise ScenarioSpecError(f"field path cannot be applied: {path}")
    final = parts[-1]
    if isinstance(final, str) and isinstance(current, dict):
        current[final] = thaw_json(item)
    elif isinstance(final, int) and isinstance(current, list) and final < len(current):
        current[final] = thaw_json(item)
    else:
        raise ScenarioSpecError(f"field path cannot be applied: {path}")


def _resolve_schema(schema: Mapping[str, Any]) -> Mapping[str, Any]:
    reference = schema.get("$ref")
    if not isinstance(reference, str):
        return schema
    prefix = "#/$defs/"
    if not reference.startswith(prefix):
        return schema
    resolved = AUTHORING_SCHEMA["$defs"].get(reference[len(prefix) :])
    return resolved if isinstance(resolved, Mapping) else schema


def _select_union_schema(
    value: Any,
    schema: Mapping[str, Any],
) -> Mapping[str, Any]:
    for keyword in ("oneOf", "anyOf"):
        variants = schema.get(keyword)
        if not isinstance(variants, list):
            continue
        candidates = [
            _resolve_schema(item)
            for item in variants
            if isinstance(item, Mapping)
        ]
        if not candidates:
            return schema
        if isinstance(value, Mapping):
            for candidate in candidates:
                properties = candidate.get("properties", {})
                if not isinstance(properties, Mapping):
                    continue
                constants = {
                    field: definition["const"]
                    for field, definition in properties.items()
                    if isinstance(definition, Mapping) and "const" in definition
                }
                if constants and all(
                    value.get(field) == item for field, item in constants.items()
                ):
                    return candidate
            return min(
                candidates,
                key=lambda item: len(set(item.get("required", ())) - set(value)),
            )
        return candidates[0]
    return schema


def _required_missing(
    value: Any,
    schema: Mapping[str, Any] = AUTHORING_SCHEMA,
    path: str = "$",
) -> set[str]:
    schema = _select_union_schema(value, _resolve_schema(schema))
    missing: set[str] = set()
    if isinstance(value, Mapping):
        for field in schema.get("required", ()):
            if field not in value:
                missing.add(f"{path}.{field}")
        properties = schema.get("properties", {})
        if isinstance(properties, Mapping):
            for field, item in value.items():
                child_schema = properties.get(field)
                if isinstance(child_schema, Mapping):
                    missing.update(
                        _required_missing(item, child_schema, f"{path}.{field}")
                    )
    elif isinstance(value, list):
        item_schema = schema.get("items")
        if isinstance(item_schema, Mapping):
            for index, item in enumerate(value):
                missing.update(
                    _required_missing(item, item_schema, f"{path}[{index}]")
                )
    return missing


def normalize_scenario_spec(
    value: Mapping[str, Any],
    *,
    explicit_paths: set[str] | frozenset[str] | None = None,
    inferred_paths: set[str] | frozenset[str] = frozenset(),
) -> NormalizedScenarioSpec:
    if not isinstance(value, Mapping):
        raise ScenarioSpecError("ScenarioSpec must be an object")
    normalized = thaw_json(value)
    if not isinstance(normalized, dict):
        raise ScenarioSpecError("ScenarioSpec must be an object")
    supplied_paths = _leaf_paths(normalized)
    explicit = supplied_paths if explicit_paths is None else set(explicit_paths)
    inferred = set(inferred_paths) - explicit
    defaulted: set[str] = set()
    for path, item in _DEFAULTS.items():
        if not _contains(normalized, path):
            _set(normalized, path, item)
            defaulted.update(_leaf_paths(thaw_json(item), path))
    missing = _required_missing(normalized)
    annotations: dict[str, ValueSource] = {}
    for path in _leaf_paths(normalized):
        if path in explicit:
            annotations[path] = ValueSource.EXPLICIT
        elif path in inferred:
            annotations[path] = ValueSource.INFERRED
        elif any(path == item or path.startswith(f"{item}.") for item in defaulted):
            annotations[path] = ValueSource.DEFAULT
        else:
            annotations[path] = ValueSource.INFERRED
    for path in missing:
        annotations[path] = ValueSource.MISSING
    return NormalizedScenarioSpec(
        schema_version="scenarioforge.normalized-scenario-spec/v1",
        content=normalized,
        annotations=tuple(
            FieldAnnotation(path=path, source=source)
            for path, source in sorted(annotations.items())
        ),
        resolved_defaults=tuple(sorted(defaulted)),
        missing_fields=tuple(sorted(missing)),
    )


class ScenarioSpecEditor:
    @staticmethod
    def from_json(payload: str | bytes) -> NormalizedScenarioSpec:
        try:
            encoded = payload.encode("utf-8") if isinstance(payload, str) else payload
            value = strict_loads(encoded)
        except (TypeError, ValueError) as error:
            raise ScenarioSpecError("editor content must be strict JSON") from error
        if not isinstance(value, Mapping):
            raise ScenarioSpecError("editor content must be one JSON object")
        return normalize_scenario_spec(value)

    @staticmethod
    def from_form(value: Mapping[str, Any]) -> NormalizedScenarioSpec:
        return normalize_scenario_spec(value)

    @staticmethod
    def apply_form_patch(
        current: NormalizedScenarioSpec,
        changes: Mapping[str, Any],
    ) -> NormalizedScenarioSpec:
        content = thaw_json(current.content)
        if not isinstance(content, dict):
            raise ScenarioSpecError("normalized ScenarioSpec is invalid")
        for path, item in changes.items():
            _set(content, path, item)
        return normalize_scenario_spec(
            content,
            explicit_paths=set(changes),
            inferred_paths=_leaf_paths(content) - set(changes),
        )


__all__ = [
    "FieldAnnotation",
    "NormalizedScenarioSpec",
    "ScenarioSpecEditor",
    "ScenarioSpecError",
    "ValueSource",
    "normalize_scenario_spec",
]
