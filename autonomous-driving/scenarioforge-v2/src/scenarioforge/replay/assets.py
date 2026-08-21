from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

from .interpolation import ReplayProjectionError


_MANIFEST_REF = PurePosixPath("assets/p1/replay/vehicle-model-manifest.json")
_STATIC_ASSET_PREFIX = PurePosixPath("src/scenarioforge/web/static")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")
_DIMENSION_FIELDS = {"length", "width", "height"}
_FEATURES = [
    "front",
    "rear",
    "body",
    "windows",
    "wheels",
    "headlights",
    "brake_lights",
]


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ReplayProjectionError("vehicle asset manifest is ambiguous")
        result[key] = value
    return result


def _safe_relative_ref(value: object) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ReplayProjectionError("vehicle asset reference is unsafe")
    parsed = urlsplit(value)
    pure = PurePosixPath(value)
    if (
        parsed.scheme
        or parsed.netloc
        or parsed.query
        or parsed.fragment
        or pure.is_absolute()
        or value.startswith("~")
        or _WINDOWS_ABSOLUTE.match(value)
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise ReplayProjectionError("vehicle asset reference is unsafe")
    return pure


def resolve_vehicle_asset_ref(
    reference: object,
    *,
    project_root: Path,
) -> Path:
    """Resolve one repository-controlled vehicle resource without path fallback."""
    pure = _safe_relative_ref(reference)
    if pure.parts[: len(_STATIC_ASSET_PREFIX.parts)] != _STATIC_ASSET_PREFIX.parts:
        raise ReplayProjectionError("vehicle asset reference is outside the allowlist")
    root = project_root.resolve(strict=True)
    allowed_root = (root / Path(*_STATIC_ASSET_PREFIX.parts)).resolve(strict=True)
    try:
        target = (root / Path(*pure.parts)).resolve(strict=True)
        target.relative_to(allowed_root)
    except (OSError, ValueError) as error:
        raise ReplayProjectionError("vehicle asset reference is unsafe") from error
    if target.is_symlink() or not target.is_file():
        raise ReplayProjectionError("vehicle asset reference is not a regular file")
    return target


def _dimensions(value: object) -> dict[str, float]:
    if not isinstance(value, dict) or set(value) != _DIMENSION_FIELDS:
        raise ReplayProjectionError("vehicle model dimensions are invalid")
    projected: dict[str, float] = {}
    for field in sorted(_DIMENSION_FIELDS):
        item = value[field]
        if (
            not isinstance(item, (int, float))
            or isinstance(item, bool)
            or not math.isfinite(item)
            or float(item) <= 0
        ):
            raise ReplayProjectionError("vehicle model dimensions are invalid")
        projected[field] = float(item)
    if not (
        2.5 <= projected["length"] <= 8.0
        and 1.4 <= projected["width"] <= 2.6
        and 1.2 <= projected["height"] <= 3.2
    ):
        raise ReplayProjectionError("vehicle model dimensions are unrealistic")
    return {
        "length": projected["length"],
        "width": projected["width"],
        "height": projected["height"],
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_vehicle_asset_manifest(*, project_root: Path) -> dict[str, Any]:
    """Load and verify the immutable in-repository vehicle asset manifest."""
    root = project_root.resolve(strict=True)
    manifest_path = root / Path(*_MANIFEST_REF.parts)
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ReplayProjectionError("vehicle asset manifest is unavailable")
    try:
        manifest = json.loads(
            manifest_path.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_object,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReplayProjectionError("vehicle asset manifest is invalid") from error
    if not isinstance(manifest, dict) or set(manifest) != {
        "schema_version",
        "manifest_version",
        "asset",
        "canonical_instances",
    }:
        raise ReplayProjectionError("vehicle asset manifest shape is invalid")
    if (
        manifest["schema_version"] != "scenarioforge.vehicle-model-manifest/v1"
        or manifest["manifest_version"] != "1.0.0"
    ):
        raise ReplayProjectionError("vehicle asset manifest version is invalid")

    asset = manifest["asset"]
    if not isinstance(asset, dict) or set(asset) != {
        "asset_id",
        "version",
        "resource_ref",
        "runtime_ref",
        "sha256",
        "license",
        "source",
        "coordinate_system",
        "local_forward_axis",
        "bounding_box_m",
        "features",
    }:
        raise ReplayProjectionError("vehicle asset contract is invalid")
    if (
        asset["asset_id"] != "scenarioforge.original-sedan"
        or asset["version"] != "1.0.0"
        or asset["coordinate_system"] != "right-handed-x-forward-y-up"
        or asset["local_forward_axis"] != "+x"
        or asset["features"] != _FEATURES
        or asset["runtime_ref"] != "app.js"
        or asset["license"]
        != {
            "spdx_id": "CC0-1.0",
            "copyright": "Dedicated to the public domain by the ScenarioForge project",
        }
        or asset["source"]
        != {
            "kind": "original-project-asset",
            "name": "ScenarioForge Sedan v1",
            "source_ref": "repo:Scenario_forge",
        }
    ):
        raise ReplayProjectionError("vehicle asset contract is invalid")
    _safe_relative_ref(asset["runtime_ref"])
    _dimensions(asset["bounding_box_m"])
    resource = resolve_vehicle_asset_ref(asset["resource_ref"], project_root=root)
    if not isinstance(asset["sha256"], str) or not _SHA256.fullmatch(asset["sha256"]):
        raise ReplayProjectionError("vehicle asset digest is invalid")
    if _sha256(resource) != asset["sha256"]:
        raise ReplayProjectionError("vehicle asset digest does not match")

    instances = manifest["canonical_instances"]
    if not isinstance(instances, list) or not instances:
        raise ReplayProjectionError("canonical vehicle instances are invalid")
    identities: set[tuple[str, str]] = set()
    for item in instances:
        if not isinstance(item, dict) or set(item) != {
            "scenario_id",
            "participant_id",
            "role",
            "declared_dimensions_m",
        }:
            raise ReplayProjectionError("canonical vehicle instance is invalid")
        scenario_id = item["scenario_id"]
        participant_id = item["participant_id"]
        if (
            not isinstance(scenario_id, str)
            or _SAFE_ID.fullmatch(scenario_id) is None
            or not isinstance(participant_id, str)
            or _SAFE_ID.fullmatch(participant_id) is None
            or item["role"] not in {"ego", "controlled", "social"}
        ):
            raise ReplayProjectionError("canonical vehicle instance is invalid")
        identity = (scenario_id, participant_id)
        if identity in identities:
            raise ReplayProjectionError("canonical vehicle instances are duplicated")
        identities.add(identity)
        _dimensions(item["declared_dimensions_m"])
    return copy.deepcopy(manifest)


def vehicle_dimensions_for(
    scenario_id: str,
    participant_id: str,
    *,
    project_root: Path,
) -> dict[str, float]:
    manifest = load_vehicle_asset_manifest(project_root=project_root)
    for instance in manifest["canonical_instances"]:
        if (
            instance["scenario_id"] == scenario_id
            and instance["participant_id"] == participant_id
        ):
            return copy.deepcopy(instance["declared_dimensions_m"])
    raise ReplayProjectionError("canonical vehicle dimensions are unavailable")


__all__ = [
    "load_vehicle_asset_manifest",
    "resolve_vehicle_asset_ref",
    "vehicle_dimensions_for",
]
