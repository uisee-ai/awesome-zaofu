from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

import rfc8785
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class BundleIntegrityError(ValueError):
    def __init__(self, invariant: str, detail: str):
        self.invariant = invariant
        super().__init__(f"{invariant} failed before parse/use: {detail}")


class _BundleModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class BundleArtifact(_BundleModel):
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)


class BundleManifest(_BundleModel):
    schema_version: Literal["scenarioforge.run-bundle-manifest.v1"]
    bundle_id: str
    status: Literal["completed", "partial", "cancelled", "aborted"]
    scenario_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifacts: tuple[BundleArtifact, ...]


@dataclass(frozen=True)
class SealedBundle:
    path: Path
    manifest: BundleManifest
    manifest_digest: str


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_artifact_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"unsafe bundle artifact path: {value}")
    return path


def seal_bundle(
    root: Path,
    *,
    bundle_id: str,
    status: Literal["completed", "partial", "cancelled", "aborted"],
    scenario_digest: str,
    files: dict[str, bytes],
) -> SealedBundle:
    root.mkdir(parents=True, exist_ok=True)
    destination = root / bundle_id
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"bundle already exists: {bundle_id}")
    staging = root / f".staging-{bundle_id}-{uuid.uuid4().hex}"
    staging.mkdir(mode=0o700)
    try:
        artifacts: list[BundleArtifact] = []
        for relative_name in sorted(files):
            relative = _safe_artifact_path(relative_name)
            data = files[relative_name]
            path = staging.joinpath(*relative.parts)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            artifacts.append(
                BundleArtifact(path=relative.as_posix(), sha256=_digest(data), size_bytes=len(data))
            )
        manifest = BundleManifest(
            schema_version="scenarioforge.run-bundle-manifest.v1",
            bundle_id=bundle_id,
            status=status,
            scenario_digest=scenario_digest,
            artifacts=tuple(artifacts),
        )
        manifest_bytes = rfc8785.dumps(manifest.model_dump(mode="json")) + b"\n"
        manifest_digest = _digest(manifest_bytes)
        (staging / "manifest.json").write_bytes(manifest_bytes)
        (staging / "bundle.sha256").write_text(
            f"{manifest_digest}  manifest.json\n", encoding="ascii"
        )
        for path in sorted(staging.rglob("*"), reverse=True):
            path.chmod(0o555 if path.is_dir() else 0o444)
        staging.chmod(0o555)
        os.replace(staging, destination)
        return SealedBundle(path=destination, manifest=manifest, manifest_digest=manifest_digest)
    except Exception:
        if staging.exists():
            for path in staging.rglob("*"):
                try:
                    path.chmod(0o700 if path.is_dir() else 0o600)
                except OSError:
                    pass
            staging.chmod(0o700)
            shutil.rmtree(staging)
        raise


def verify_bundle(path: Path) -> BundleManifest:
    if path.is_symlink() or not path.is_dir():
        raise BundleIntegrityError("bundle_directory", "bundle is not a real directory")
    digest_path = path / "bundle.sha256"
    try:
        digest_text = digest_path.read_text(encoding="ascii")
    except (OSError, UnicodeError) as error:
        raise BundleIntegrityError("bundle_digest", str(error)) from error
    match = re.fullmatch(r"([0-9a-f]{64})  manifest\.json\n", digest_text)
    if not match:
        raise BundleIntegrityError("bundle_digest", "invalid bundle digest sidecar")
    manifest_path = path / "manifest.json"
    if manifest_path.is_symlink():
        raise BundleIntegrityError("manifest_digest", "manifest must not be a symlink")
    try:
        manifest_bytes = manifest_path.read_bytes()
    except OSError as error:
        raise BundleIntegrityError("manifest_digest", str(error)) from error
    if _digest(manifest_bytes) != match.group(1):
        raise BundleIntegrityError("manifest_digest", "manifest SHA-256 mismatch")
    try:
        manifest = BundleManifest.model_validate_json(manifest_bytes)
    except ValidationError as error:
        raise BundleIntegrityError("manifest_schema", str(error)) from error
    if manifest.bundle_id != path.name:
        raise BundleIntegrityError("bundle_identity", "directory name does not match bundle_id")
    seen: set[str] = set()
    for artifact in manifest.artifacts:
        try:
            relative = _safe_artifact_path(artifact.path)
        except ValueError as error:
            raise BundleIntegrityError(f"artifact_path:{artifact.path}", str(error)) from error
        if artifact.path in seen:
            raise BundleIntegrityError(f"artifact_path:{artifact.path}", "duplicate artifact")
        seen.add(artifact.path)
        artifact_path = path.joinpath(*relative.parts)
        if artifact_path.is_symlink() or not artifact_path.is_file():
            raise BundleIntegrityError(f"artifact_digest:{artifact.path}", "artifact is missing or a symlink")
        data = artifact_path.read_bytes()
        if _digest(data) != artifact.sha256:
            raise BundleIntegrityError(f"artifact_digest:{artifact.path}", "artifact SHA-256 mismatch")
        if len(data) != artifact.size_bytes:
            raise BundleIntegrityError(f"artifact_size:{artifact.path}", "artifact size mismatch")
    return manifest


def load_bundle_json(path: Path, artifact_name: str) -> object:
    manifest = verify_bundle(path)
    artifacts = {artifact.path: artifact for artifact in manifest.artifacts}
    if artifact_name not in artifacts:
        raise BundleIntegrityError(f"artifact_presence:{artifact_name}", "artifact is not in manifest")
    relative = _safe_artifact_path(artifact_name)
    data = path.joinpath(*relative.parts).read_bytes()
    try:
        return json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BundleIntegrityError(f"artifact_schema:{artifact_name}", str(error)) from error
