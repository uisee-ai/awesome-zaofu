from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[2]

PYTHON_PINS = {
    "fastapi": "0.141.1",
    "httpx": "0.28.1",
    "metadrive-simulator": "0.4.3",
    "psutil": "7.2.2",
    "pydantic": "2.13.4",
    "python-multipart": "0.0.32",
    "pyyaml": "6.0.3",
    "rfc8785": "0.1.4",
    "uvicorn": "0.52.1",
}

WEB_PINS = {
    "react": "19.2.8",
    "react-dom": "19.2.8",
    "three": "0.185.1",
}

WEB_DEV_PINS = {
    "@playwright/test": "1.62.1",
    "@types/node": "26.1.2",
    "@types/react": "19.2.18",
    "@types/react-dom": "19.2.4",
    "@types/three": "0.185.3",
    "@vitejs/plugin-react": "6.0.5",
    "typescript": "7.0.2",
    "vite": "8.2.0",
    "vitest": "4.1.10",
}


def _exact_python_pins(requirements: list[str]) -> dict[str, str]:
    pins: dict[str, str] = {}
    for requirement in requirements:
        match = re.fullmatch(r"([A-Za-z0-9_-]+)(?:\[[^]]+\])?==([^; ]+)", requirement)
        assert match, f"Python dependency must be an exact pin: {requirement}"
        pins[match.group(1).lower()] = match.group(2)
    return pins


def test_python_manifest_lock_and_entrypoint_are_pinned() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    project = pyproject["project"]
    assert project["name"] == "scenarioforge"
    assert project["requires-python"] == ">=3.11,<3.12"
    assert _exact_python_pins(project["dependencies"]) == PYTHON_PINS
    assert project["scripts"] == {"scenarioforge": "scenarioforge.app:main"}
    assert pyproject["tool"]["pytest"]["ini_options"]["testpaths"] == ["tests"]
    assert pyproject["tool"]["ruff"] == {
        "target-version": "py311",
        "line-length": 100,
        "lint": {"select": ["E4", "E7", "E9", "F"]},
    }

    lock = (ROOT / "uv.lock").read_text(encoding="utf-8")
    assert 'requires-python = "==3.11.*"' in lock
    assert 'name = "metadrive-simulator"\nversion = "0.4.3"' in lock


def test_web_manifest_lock_and_test_root_are_pinned() -> None:
    package = json.loads((ROOT / "web/package.json").read_text(encoding="utf-8"))
    assert package["private"] is True
    assert package["engines"] == {"node": "24.14.1", "npm": "11.11.0"}
    assert package["packageManager"] == "npm@11.11.0"
    assert package["dependencies"] == WEB_PINS
    assert package["devDependencies"] == WEB_DEV_PINS
    assert all(not version.startswith(("^", "~", ">", "<", "*")) for version in WEB_PINS.values())
    assert all(
        not version.startswith(("^", "~", ">", "<", "*"))
        for version in WEB_DEV_PINS.values()
    )

    lock = json.loads((ROOT / "web/package-lock.json").read_text(encoding="utf-8"))
    assert lock["lockfileVersion"] == 3
    assert lock["packages"][""]["dependencies"] == WEB_PINS
    assert lock["packages"][""]["devDependencies"] == WEB_DEV_PINS

    playwright = (ROOT / "web/playwright.config.ts").read_text(encoding="utf-8")
    assert "testDir: '../tests/web'" in playwright


def test_metadrive_asset_allowlist_fails_closed_offline() -> None:
    manifest = json.loads(
        (ROOT / "config/metadrive-assets.lock.json").read_text(encoding="utf-8")
    )

    assert manifest == {
        "schema_version": "scenarioforge.metadrive-assets.v1",
        "backend": {
            "distribution": "metadrive-simulator",
            "version": "0.4.3",
        },
        "runtime_policy": {
            "network_access": "denied",
            "auto_download": False,
            "missing_or_mismatched": "fail_closed",
        },
        "artifacts": [
            {
                "id": "metadrive-assets-0.4.3",
                "source_url": "https://github.com/metadriverse/metadrive/releases/download/MetaDrive-0.4.3/assets.zip",
                "media_type": "application/zip",
                "size_bytes": 134074203,
                "sha256": "4f0da9f5143a1258131c5b55f77bdf170c0f9bce8a9f18dd41b3678df779eac9",
                "redistribution": "prohibited_until_release_license_review",
            }
        ],
    }


def test_scaffold_conventions_match_the_integrated_repository() -> None:
    package_init = (ROOT / "src/scenarioforge/__init__.py").read_text(encoding="utf-8")
    assert '__version__ = "0.1.0"' in package_init

    conventions = (ROOT / "docs/architecture/conventions.md").read_text(encoding="utf-8")
    assert "src/scenarioforge/" in conventions
    assert "scenarioforge.app:main" in conventions
    assert "tests/" in conventions
    assert "tests/web/" in conventions

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "libgl1" in readme

    integrated_roots = [
        ROOT / "src/scenarioforge/spec",
        ROOT / "src/scenarioforge/compiler",
        ROOT / "src/scenarioforge/runtime",
        ROOT / "src/scenarioforge/bundle",
        ROOT / "src/scenarioforge/oracle",
        ROOT / "tests/backend",
        ROOT / "tests/web",
        ROOT / "tests/release",
    ]
    assert all(path.is_dir() for path in integrated_roots)
    assert all(any(entry.is_file() for entry in path.iterdir()) for path in integrated_roots)
    assert not list((ROOT / "src/scenarioforge").rglob(".gitkeep"))
    assert not [
        path
        for path in (ROOT / "tests").rglob(".gitkeep")
        if path.parent != ROOT / "tests"
    ]
