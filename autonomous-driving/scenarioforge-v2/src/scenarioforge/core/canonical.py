from __future__ import annotations

import hashlib
import json
from dataclasses import fields
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping


JSONValue = None | bool | int | float | str | tuple["JSONValue", ...] | Mapping[str, "JSONValue"]


def freeze_json(value: Any) -> JSONValue:
    """Recursively freeze a JSON value without introducing backend objects."""
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): freeze_json(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze_json(item) for item in value)
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    raise TypeError(f"not a JSON value: {type(value).__name__}")


def thaw_json(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw_json(item) for item in value]
    if isinstance(value, list):
        return [thaw_json(item) for item in value]
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return value


def canonical_bytes(value: Any) -> bytes:
    payload = thaw_json(value)
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


class CanonicalModel:
    """Dataclass mixin providing a stable public JSON representation."""

    def to_dict(self) -> dict[str, Any]:
        return {
            field.name: thaw_json(getattr(self, field.name))
            for field in fields(self)
            if not field.name.startswith("_")
        }

    @property
    def digest(self) -> str:
        return canonical_digest(self.to_dict())
