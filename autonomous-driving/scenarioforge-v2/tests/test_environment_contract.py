from __future__ import annotations

import hashlib
import importlib.util
import platform
import sys
import tomllib
from pathlib import Path

from scenarioforge.core import environment_fingerprint


ROOT = Path(__file__).resolve().parents[1]


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        payload = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def test_pyproject_and_uv_lock_pin_the_supported_environment() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))

    assert project["project"]["requires-python"] == "==3.11.15"
    assert project["project"]["dependencies"] == [
        "jsonschema==4.25.1",
        "metadrive-simulator==0.4.3",
        "PyYAML==6.0.3",
    ]
    assert project["dependency-groups"]["dev"] == ["pytest==9.0.3"]
    assert project["tool"]["pytest"]["ini_options"] == {
        "addopts": "--strict-config --strict-markers",
        "pythonpath": ["src"],
        "testpaths": ["tests"],
    }

    pyyaml_packages = [package for package in lock["package"] if package["name"] == "pyyaml"]
    assert len(pyyaml_packages) == 1
    assert pyyaml_packages[0]["version"] == "6.0.3"

    packages = {package["name"]: package for package in lock["package"]}
    assert packages["scenarioforge"]["source"] == {"editable": "."}
    assert packages["jsonschema"]["version"] == "4.25.1"
    assert packages["metadrive-simulator"]["version"] == "0.4.3"
    assert packages["pytest"]["version"] == "9.0.3"
    for name in ("jsonschema", "metadrive-simulator", "pyyaml", "pytest"):
        assert packages[name]["sdist"]["hash"].startswith("sha256:")
        assert all(wheel["hash"].startswith("sha256:") for wheel in packages[name]["wheels"])


def test_environment_fingerprint_is_linux_x86_64_headless_without_gpu() -> None:
    assert "metadrive" not in sys.modules
    fingerprint = environment_fingerprint(ROOT / "uv.lock")
    assert "metadrive" not in sys.modules

    spec = importlib.util.find_spec("metadrive")
    assert spec is not None and spec.origin is not None
    assets = Path(spec.origin).parent / "assets"
    expected = {
        "schema_version": "scenarioforge.environment-fingerprint/v1",
        "os": "Linux",
        "architecture": "x86_64",
        "python": {
            "implementation": platform.python_implementation(),
            "version": "3.11.15",
        },
        "simulator": {
            "distribution": "metadrive-simulator",
            "version": "0.4.3",
            "asset_version": "0.4.3",
            "asset_digest": _tree_digest(assets),
        },
        "rendering": {"headless": True, "gpu_required": False},
        "dependency_lock": {
            "format": "uv.lock",
            "digest": hashlib.sha256((ROOT / "uv.lock").read_bytes()).hexdigest(),
        },
    }
    assert fingerprint.to_dict() == expected
