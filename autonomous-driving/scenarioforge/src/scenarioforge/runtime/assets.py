from __future__ import annotations

import hashlib
import importlib.metadata
from dataclasses import dataclass
from pathlib import Path

METADRIVE_DISTRIBUTION = "metadrive-simulator"
METADRIVE_VERSION = "0.4.3"
REQUIRED_ASSET = Path("textures/grass1/GroundGrassGreen002_COL_1K.jpg")


class RuntimePreflightError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        self.network_attempted = False
        super().__init__(message)


@dataclass(frozen=True)
class MetaDriveRuntime:
    distribution: str
    version: str
    asset_version: str
    asset_root: Path
    asset_lock_sha256: str | None
    network_policy: str = "denied"
    auto_download: bool = False


def _installed_asset_root() -> Path:
    try:
        distribution = importlib.metadata.distribution(METADRIVE_DISTRIBUTION)
    except importlib.metadata.PackageNotFoundError as error:
        raise RuntimePreflightError(
            "backend_missing", f"{METADRIVE_DISTRIBUTION}=={METADRIVE_VERSION} is not installed"
        ) from error
    if distribution.version != METADRIVE_VERSION:
        raise RuntimePreflightError(
            "backend_version_mismatch",
            f"expected {METADRIVE_DISTRIBUTION}=={METADRIVE_VERSION}, got {distribution.version}",
        )
    return Path(distribution.locate_file("metadrive/assets"))


def _asset_lock_digest() -> str | None:
    lock = Path.cwd() / "config/metadrive-assets.lock.json"
    if not lock.is_file() or lock.is_symlink():
        return None
    return hashlib.sha256(lock.read_bytes()).hexdigest()


def check_metadrive_runtime(*, asset_root: Path | None = None) -> MetaDriveRuntime:
    root = asset_root if asset_root is not None else _installed_asset_root()
    if root.is_symlink() or not root.is_dir():
        raise RuntimePreflightError("assets_missing", f"MetaDrive assets directory is missing: {root}")
    version_file = root / "version.txt"
    if version_file.is_symlink() or not version_file.is_file():
        raise RuntimePreflightError("assets_missing", "MetaDrive assets/version.txt is missing")
    try:
        asset_version = version_file.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as error:
        raise RuntimePreflightError("assets_unreadable", str(error)) from error
    if asset_version != METADRIVE_VERSION:
        raise RuntimePreflightError(
            "assets_version_mismatch",
            f"expected MetaDrive assets {METADRIVE_VERSION}, got {asset_version}",
        )
    required_asset = root / REQUIRED_ASSET
    if required_asset.is_symlink() or not required_asset.is_file():
        raise RuntimePreflightError(
            "assets_incomplete", f"required MetaDrive asset is missing: {REQUIRED_ASSET.as_posix()}"
        )
    return MetaDriveRuntime(
        distribution=METADRIVE_DISTRIBUTION,
        version=METADRIVE_VERSION,
        asset_version=asset_version,
        asset_root=root,
        asset_lock_sha256=_asset_lock_digest(),
    )
