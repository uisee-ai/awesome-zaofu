from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scenarioforge.replay import (
    ReplayProjectionError,
    load_vehicle_asset_manifest,
    resolve_vehicle_asset_ref,
    vehicle_dimensions_for,
)


ROOT = Path(__file__).resolve().parents[3]
MODEL_MODULE = ROOT / "src/scenarioforge/web/static/app.js"
SCENARIOS = ROOT / "tests/fixtures/p1/scenarios"


def _canonical_vehicle_dimensions() -> dict[tuple[str, str], dict[str, float]]:
    expected: dict[tuple[str, str], dict[str, float]] = {}
    for path in sorted(SCENARIOS.glob("*.json")):
        if path.name.startswith("_"):
            continue
        scenario = json.loads(path.read_text(encoding="utf-8"))
        for actor in scenario["actors"]:
            if actor["kind"] != "vehicle":
                continue
            expected[(path.stem, actor["id"])] = {
                "length": actor["dimensions"]["length_m"],
                "width": actor["dimensions"]["width_m"],
                "height": actor["dimensions"]["height_m"],
            }
    return expected


def test_vehicle_manifest_binds_version_digest_license_source_and_real_bounds() -> None:
    manifest = load_vehicle_asset_manifest(project_root=ROOT)

    assert set(manifest) == {
        "schema_version",
        "manifest_version",
        "asset",
        "canonical_instances",
    }
    assert manifest["schema_version"] == "scenarioforge.vehicle-model-manifest/v1"
    assert manifest["manifest_version"] == "1.0.0"
    asset = manifest["asset"]
    assert set(asset) == {
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
    }
    assert asset["asset_id"] == "scenarioforge.original-sedan"
    assert asset["version"] == "1.0.0"
    assert asset["coordinate_system"] == "right-handed-x-forward-y-up"
    assert asset["local_forward_axis"] == "+x"
    assert asset["bounding_box_m"] == {
        "length": 4.8,
        "width": 1.9,
        "height": 1.6,
    }
    assert asset["features"] == [
        "front",
        "rear",
        "body",
        "windows",
        "wheels",
        "headlights",
        "brake_lights",
    ]
    assert asset["license"] == {
        "spdx_id": "CC0-1.0",
        "copyright": "Dedicated to the public domain by the ScenarioForge project",
    }
    assert asset["source"] == {
        "kind": "original-project-asset",
        "name": "ScenarioForge Sedan v1",
        "source_ref": "repo:Scenario_forge",
    }
    resource = resolve_vehicle_asset_ref(asset["resource_ref"], project_root=ROOT)
    assert resource == MODEL_MODULE.resolve()
    assert hashlib.sha256(resource.read_bytes()).hexdigest() == asset["sha256"]


def test_manifest_dimensions_match_every_read_only_canonical_vehicle_fixture() -> None:
    expected = _canonical_vehicle_dimensions()
    manifest = load_vehicle_asset_manifest(project_root=ROOT)
    observed = {
        (item["scenario_id"], item["participant_id"]): item["declared_dimensions_m"]
        for item in manifest["canonical_instances"]
    }

    assert observed == expected
    assert {
        key: vehicle_dimensions_for(*key, project_root=ROOT) for key in sorted(expected)
    } == expected


@pytest.mark.parametrize(
    "reference",
    [
        "https://example.invalid/sedan.glb",
        "http://example.invalid/sedan.glb",
        "file:///tmp/sedan.glb",
        "/tmp/sedan.glb",
        "../../sedan.glb",
        "~/sedan.glb",
        "src/scenarioforge/web/static/assets/../app.js",
        "C:\\Users\\driver\\sedan.glb",
    ],
)
def test_offline_asset_resolution_rejects_network_file_and_local_paths(
    reference: str,
) -> None:
    with pytest.raises(ReplayProjectionError, match="vehicle asset reference"):
        resolve_vehicle_asset_ref(reference, project_root=ROOT)


def test_vehicle_model_is_not_a_box_placeholder_and_declares_visible_parts() -> None:
    source = MODEL_MODULE.read_text(encoding="utf-8")
    model_source = source.split("// ScenarioForge Sedan v1", maxsplit=1)[1].split(
        "document.querySelectorAll", maxsplit=1
    )[0]

    assert "BoxGeometry" not in model_source
    assert "BufferGeometry" in model_source
    assert "CylinderGeometry" in model_source
    for feature in (
        "vehicle-body",
        "vehicle-window",
        "vehicle-wheel",
        "vehicle-front",
        "vehicle-rear",
    ):
        assert feature in model_source
    for forbidden in ("http://", "https://", "file://"):
        assert forbidden not in model_source
