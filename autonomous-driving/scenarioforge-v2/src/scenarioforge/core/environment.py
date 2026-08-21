from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import platform
from pathlib import Path

from .canonical import freeze_json
from .models import EnvironmentFingerprint


def _tree_digest(root: Path) -> str:
    if not root.is_dir():
        raise RuntimeError(
            "MetaDrive assets are not installed; run `python -m metadrive.pull_asset` "
            "during environment provisioning before starting a Worker"
        )
    digest = hashlib.sha256()
    for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        payload = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def simulator_fingerprint() -> dict[str, str]:
    spec = importlib.util.find_spec("metadrive")
    if spec is None or spec.origin is None:
        raise RuntimeError("metadrive-simulator 0.4.3 is not installed")
    assets = Path(spec.origin).parent / "assets"
    asset_version_path = assets / "version.txt"
    if not asset_version_path.is_file():
        raise RuntimeError("MetaDrive asset version file is missing")
    asset_version = asset_version_path.read_text(encoding="utf-8").strip()

    return {
        "distribution": "metadrive-simulator",
        "version": importlib.metadata.version("metadrive-simulator"),
        "asset_version": asset_version,
        "asset_digest": _tree_digest(assets),
    }


def environment_fingerprint(lockfile: Path) -> EnvironmentFingerprint:
    lockfile = Path(lockfile)
    if not lockfile.is_file():
        raise RuntimeError(f"dependency lockfile is missing: {lockfile.name}")

    return EnvironmentFingerprint(
        schema_version="scenarioforge.environment-fingerprint/v1",
        os=platform.system(),
        architecture=platform.machine(),
        python=freeze_json(
            {
                "implementation": platform.python_implementation(),
                "version": platform.python_version(),
            }
        ),
        simulator=freeze_json(simulator_fingerprint()),
        rendering=freeze_json({"headless": True, "gpu_required": False}),
        dependency_lock=freeze_json(
            {
                "format": "uv.lock",
                "digest": hashlib.sha256(lockfile.read_bytes()).hexdigest(),
            }
        ),
    )
