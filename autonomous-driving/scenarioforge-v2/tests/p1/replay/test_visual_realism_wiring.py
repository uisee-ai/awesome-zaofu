from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
APP = ROOT / "src/scenarioforge/web/static/app.js"


def test_web_replay_uses_the_controlled_vehicle_model_and_complete_road_cues() -> None:
    source = APP.read_text(encoding="utf-8")

    assert "ScenarioForge Sedan v1" in source
    assert "createVehicleModel" in source
    assert "new THREE.BoxGeometry(4.4, 1.25, 1.8)" not in source
    for behavior in (
        "renderCurbs",
        "renderStopLines",
        "renderTrafficSignals",
        "updateTrafficSignals",
    ):
        assert behavior in source
    assert "roadElements" in source
    assert "vehicleModelFeatures" in source


def test_follow_camera_reports_calculated_view_error_instead_of_a_fixed_zero() -> None:
    source = APP.read_text(encoding="utf-8")

    assert "followCameraQuality" in source
    assert 'dataset.lookDirectionErrorDeg = "0"' not in source
    assert "quality.viewDirectionErrorDeg" in source


def test_vehicle_asset_is_embedded_in_the_existing_offline_application_bundle() -> None:
    source = APP.read_text(encoding="utf-8")

    assert "CC0-1.0" in source
    assert "CANONICAL_VEHICLE_DIMENSIONS" in source
