from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import stat
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.release._common import EvidenceError  # noqa: E402


DEFAULT_LOCK = PROJECT_ROOT / "config/metadrive-assets.lock.json"
REQUIRED_ASSET = Path("textures/grass1/GroundGrassGreen002_COL_1K.jpg")
MAX_UNCOMPRESSED_BYTES = 1_073_741_824


def _lock_artifact(lock_path: Path) -> tuple[dict[str, Any], str]:
    if lock_path.is_symlink() or not lock_path.is_file():
        raise EvidenceError("asset lock is missing or unsafe")
    try:
        lock = json.loads(lock_path.read_bytes())
        artifact = lock["artifacts"][0]
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as error:
        raise EvidenceError("asset lock has an invalid schema") from error
    if not isinstance(artifact, dict):
        raise EvidenceError("asset lock has an invalid artifact")
    return artifact, hashlib.sha256(lock_path.read_bytes()).hexdigest()


def _validate_members(archive: zipfile.ZipFile) -> None:
    total = 0
    for member in archive.infolist():
        name = PurePosixPath(member.filename)
        mode = member.external_attr >> 16
        if (
            name.is_absolute()
            or not name.parts
            or ".." in name.parts
            or "\\" in member.filename
            or stat.S_ISLNK(mode)
        ):
            raise EvidenceError(f"unsafe archive entry: {member.filename}")
        total += member.file_size
        if total > MAX_UNCOMPRESSED_BYTES:
            raise EvidenceError("asset archive exceeds the uncompressed size limit")
        if member.compress_size == 0 and member.file_size > 0:
            raise EvidenceError(f"unsafe archive compression ratio: {member.filename}")
        if member.compress_size and member.file_size / member.compress_size > 200:
            raise EvidenceError(f"unsafe archive compression ratio: {member.filename}")


def _asset_root(staging: Path) -> Path:
    candidates = (staging, staging / "assets", staging / "metadrive/assets")
    for candidate in candidates:
        if (candidate / "version.txt").is_file() and (candidate / REQUIRED_ASSET).is_file():
            return candidate
    raise EvidenceError("asset archive is incomplete")


def install_asset_archive(
    archive_path: Path,
    target: Path,
    *,
    lock_path: Path = DEFAULT_LOCK,
) -> dict[str, object]:
    """Install one allowlisted archive without using any network fallback."""

    if archive_path.is_symlink() or not archive_path.is_file():
        raise EvidenceError("asset archive is missing or unsafe")
    if target.exists() or target.is_symlink():
        raise EvidenceError("asset install target must not already exist")
    artifact, lock_digest = _lock_artifact(lock_path)
    archive_bytes = archive_path.read_bytes()
    archive_digest = hashlib.sha256(archive_bytes).hexdigest()
    if archive_path.stat().st_size != artifact.get("size_bytes"):
        raise EvidenceError("asset archive size does not match the allowlist")
    if archive_digest != artifact.get("sha256"):
        raise EvidenceError("asset archive digest does not match the allowlist")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".scenarioforge-assets-", dir=target.parent) as temporary:
        staging = Path(temporary)
        with zipfile.ZipFile(archive_path) as archive:
            _validate_members(archive)
            archive.extractall(staging)
        root = _asset_root(staging)
        if (root / "version.txt").read_text(encoding="utf-8").strip() != "0.4.3":
            raise EvidenceError("asset archive version does not match MetaDrive 0.4.3")
        if root == staging:
            completed = staging / ".completed"
            completed.mkdir()
            for child in list(staging.iterdir()):
                if child != completed:
                    shutil.move(str(child), completed / child.name)
            root = completed
        shutil.move(str(root), target)
    return {
        "schema_version": "scenarioforge.asset-install-receipt.v1",
        "status": "passed",
        "artifact_id": artifact.get("id"),
        "archive_sha256": archive_digest,
        "asset_lock_sha256": lock_digest,
        "asset_version": "0.4.3",
        "network_access": "not_attempted",
        "auto_download": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install the allowlisted MetaDrive asset archive")
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    args = parser.parse_args(argv)
    receipt = install_asset_archive(args.archive, args.target, lock_path=args.lock)
    print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
