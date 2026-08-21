from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scenarioforge.core.canonical import CanonicalModel, JSONValue, freeze_json, thaw_json
from scenarioforge.core.strict_json import strict_loads


BUILTIN_PRESET_IDS = (
    "brake_lead",
    "construction_merge",
    "dangerous_cut_in",
    "highway_merge",
    "unprotected_left_turn",
)


class UnknownPresetError(LookupError):
    pass


class InvalidPresetError(ValueError):
    pass


@dataclass(frozen=True)
class PresetTemplate(CanonicalModel):
    template_id: str
    template_digest: str
    schema_version: str
    content: JSONValue


class PresetCatalog:
    """Read-only access to the five frozen P0-C fixture files."""

    def __init__(self, root: str | Path | None = None) -> None:
        repository_root = Path(__file__).resolve().parents[3]
        self._root = Path(root) if root is not None else repository_root / "examples" / "p0c"

    @property
    def template_ids(self) -> tuple[str, ...]:
        return BUILTIN_PRESET_IDS

    def _path(self, template_id: str) -> Path:
        if template_id not in BUILTIN_PRESET_IDS:
            raise UnknownPresetError("unknown preset")
        return self._root / f"{template_id}.json"

    def get(self, template_id: str) -> PresetTemplate:
        raw = self._path(template_id).read_bytes()
        value = strict_loads(raw)
        if not isinstance(value, Mapping):
            raise InvalidPresetError("preset must contain a JSON object")
        if value.get("scenario_id") != template_id:
            raise InvalidPresetError("preset identity does not match its registration")
        schema_version = value.get("schema_version")
        if not isinstance(schema_version, str) or not schema_version:
            raise InvalidPresetError("preset schema version is missing")
        return PresetTemplate(
            template_id=template_id,
            template_digest=hashlib.sha256(raw).hexdigest(),
            schema_version=schema_version,
            content=freeze_json(value),
        )

    def editable_copy(self, template_id: str) -> dict[str, Any]:
        value = thaw_json(self.get(template_id).content)
        if not isinstance(value, dict):
            raise InvalidPresetError("preset must contain a JSON object")
        return value


__all__ = [
    "BUILTIN_PRESET_IDS",
    "InvalidPresetError",
    "PresetCatalog",
    "PresetTemplate",
    "UnknownPresetError",
]
