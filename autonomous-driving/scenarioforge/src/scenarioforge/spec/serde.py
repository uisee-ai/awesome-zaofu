from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any, NoReturn

import rfc8785
import yaml
from pydantic import ValidationError

from .models import CanonicalScenario, ScenarioSpec

MAX_DOCUMENT_BYTES = 1_048_576
_YAML_FEATURE = re.compile(r"(?:^|[\s\[{,])(?:!!|&[A-Za-z0-9_-]+|\*[A-Za-z0-9_-]+|%TAG)")
_DANGEROUS_STRING = re.compile(
    r"(?:[A-Za-z][A-Za-z0-9+.-]*://|(?:^|[\\/])\.\.(?:[\\/]|$)|^[/~]|\$\{|`|\b(?:eval|exec|import)\s*\()",
    re.IGNORECASE,
)


class ScenarioInputError(ValueError):
    def __init__(self, diagnostics: list[dict[str, str]]):
        self.diagnostics = diagnostics
        super().__init__("; ".join(item["message"] for item in diagnostics))


class _NoDuplicateSafeLoader(yaml.SafeLoader):
    pass


def _construct_mapping(loader: yaml.SafeLoader, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping", node.start_mark, f"duplicate key: {key}", key_node.start_mark
            )
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_NoDuplicateSafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping
)


def _fail(location: str, code: str, message: str) -> NoReturn:
    raise ScenarioInputError([{"location": location, "code": code, "message": message}])


def _location(parts: tuple[object, ...]) -> str:
    if not parts:
        return "$"
    return ".".join(str(part) for part in parts)


def _scan_untrusted(value: Any, parts: tuple[object, ...] = (), depth: int = 0) -> None:
    if depth > 32:
        _fail(_location(parts), "max_depth", "document nesting exceeds 32 levels")
    if isinstance(value, float) and not math.isfinite(value):
        _fail(_location(parts), "non_finite", "non-finite numbers are not allowed")
    if isinstance(value, str) and _DANGEROUS_STRING.search(value):
        _fail(_location(parts), "unsafe_reference", "code, URL, path, and environment references are forbidden")
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                _fail(_location(parts), "non_string_key", "object keys must be strings")
            _scan_untrusted(child, (*parts, key), depth + 1)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _scan_untrusted(child, (*parts, index), depth + 1)


def _parse_json(source: str) -> Any:
    try:
        return json.loads(source, parse_constant=lambda value: _fail("$", "non_finite", f"{value} is forbidden"))
    except ScenarioInputError:
        raise
    except (json.JSONDecodeError, RecursionError) as error:
        _fail("$", "invalid_json", f"invalid JSON: {error}")


def _parse_yaml(source: str) -> Any:
    if _YAML_FEATURE.search(source):
        _fail("$", "unsafe_yaml", "YAML tags, anchors, aliases, and directives are forbidden")
    try:
        return yaml.load(source, Loader=_NoDuplicateSafeLoader)
    except (yaml.YAMLError, RecursionError) as error:
        _fail("$", "invalid_yaml", f"invalid or unsafe YAML: {error}")


def load_scenario(source: str | bytes, media_type: str) -> ScenarioSpec:
    raw = source.encode("utf-8") if isinstance(source, str) else source
    if len(raw) > MAX_DOCUMENT_BYTES:
        _fail("$", "document_too_large", f"document exceeds {MAX_DOCUMENT_BYTES} bytes")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        _fail("$", "invalid_utf8", f"document is not UTF-8: {error}")
    normalized_media_type = media_type.split(";", 1)[0].strip().lower()
    if normalized_media_type == "application/json":
        payload = _parse_json(text)
    elif normalized_media_type in {"application/yaml", "text/yaml", "application/x-yaml"}:
        payload = _parse_yaml(text)
    else:
        _fail("$", "unsupported_media_type", f"unsupported media type: {normalized_media_type}")
    if not isinstance(payload, dict):
        _fail("$", "expected_object", "ScenarioSpec must be an object")
    _scan_untrusted(payload)
    try:
        return ScenarioSpec.model_validate(payload)
    except ValidationError as error:
        raw_diagnostics = [
            {
                "location": _location(tuple(item["loc"])),
                "code": str(item["type"]),
                "message": str(item["msg"]),
            }
            for item in error.errors(include_url=False)
        ]
        diagnostics = sorted(
            raw_diagnostics,
            key=lambda item: 0 if item["code"] == "extra_forbidden" else 1,
        )
        raise ScenarioInputError(diagnostics) from error


def canonical_scenario(scenario: ScenarioSpec) -> CanonicalScenario:
    # ScenarioSpec v1 accepts the P0 fields as optional extensions.  Omitting
    # their defaults preserves the canonical identity of pre-P0 v1 documents.
    data = rfc8785.dumps(scenario.model_dump(mode="json", exclude_defaults=True))
    return CanonicalScenario(bytes=data, digest=hashlib.sha256(data).hexdigest())


def export_scenario(scenario: ScenarioSpec, format: str) -> str:
    payload = scenario.model_dump(mode="json", exclude_defaults=True)
    if format == "json":
        return json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if format == "yaml":
        return yaml.safe_dump(payload, allow_unicode=True, sort_keys=True)
    raise ValueError(f"unsupported export format: {format}")
