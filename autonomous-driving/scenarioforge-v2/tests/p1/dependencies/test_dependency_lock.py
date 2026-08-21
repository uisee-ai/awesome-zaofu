from __future__ import annotations

import json
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
ENVIRONMENT_FIXTURES = ROOT / "tests" / "fixtures" / "p1" / "environment"


def test_p1_simulator_stack_is_a_default_frozen_dependency_group() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))

    assert project["project"]["requires-python"] == "==3.11.15"
    assert project["dependency-groups"]["simulation"] == [
        "eclipse-sumo==1.19.0",
        "smarts[sumo]==2.0.1",
    ]
    assert project["dependency-groups"]["browser"] == ["playwright==1.61.0"]
    assert project["project"]["dependencies"][1] == "metadrive-simulator==0.4.3"
    assert project["tool"]["uv"]["default-groups"] == [
        "dev",
        "web",
        "browser",
        "simulation",
    ]

    packages = {package["name"]: package for package in lock["package"]}
    expected_versions = {
        "eclipse-sumo": "1.19.0",
        "metadrive-simulator": "0.4.3",
        "playwright": "1.61.0",
        "smarts": "2.0.1",
    }
    assert {name: packages[name]["version"] for name in expected_versions} == (
        expected_versions
    )
    for name in expected_versions:
        assert packages[name]["wheels"]
        assert all(
            wheel["hash"].startswith("sha256:") for wheel in packages[name]["wheels"]
        )


def test_versioned_environment_and_asset_fixtures_are_exact() -> None:
    runtime_environment = json.loads(
        (ENVIRONMENT_FIXTURES / "runtime-environment.v1.json").read_text(
            encoding="utf-8"
        )
    )
    asset_identities = json.loads(
        (ENVIRONMENT_FIXTURES / "asset-identities.v1.json").read_text(
            encoding="utf-8"
        )
    )

    assert runtime_environment == {
        "schema_version": "scenarioforge.p1.runtime-environment/v1",
        "python": {"implementation": "CPython", "version": "3.11.15"},
        "platform": {"operating_system": "Linux", "architecture": "x86_64"},
        "distributions": [
            {"name": "smarts", "version": "2.0.1", "role": "primary_backend"},
            {
                "name": "eclipse-sumo",
                "version": "1.19.0",
                "role": "traffic_simulator",
            },
            {
                "name": "metadrive-simulator",
                "version": "0.4.3",
                "role": "regression_backend",
            },
            {
                "name": "playwright",
                "version": "1.61.0",
                "role": "browser_automation",
            },
        ],
        "compatibility": {
            "smarts_python": ">=3.8",
            "smarts_sumo": "eclipse-sumo>=1.12.0",
        },
    }
    assert asset_identities == {
        "schema_version": "scenarioforge.p1.asset-identities/v1",
        "assets": [
            {
                "asset_id": "smarts-distribution",
                "distribution": "smarts",
                "version": "2.0.1",
                "identity_source": "distribution_metadata",
            },
            {
                "asset_id": "sumo-binary-bundle",
                "distribution": "eclipse-sumo",
                "version": "1.19.0",
                "identity_source": "distribution_metadata",
            },
            {
                "asset_id": "metadrive-assets",
                "distribution": "metadrive-simulator",
                "version": "0.4.3",
                "identity_source": "metadrive/assets/version.txt",
            },
            {
                "asset_id": "chromium-runtime",
                "distribution": "playwright",
                "version": "1.61.0",
                "identity_source": "distribution_metadata",
            },
        ],
    }
