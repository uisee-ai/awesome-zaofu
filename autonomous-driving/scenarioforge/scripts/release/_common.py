from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SHA256 = re.compile(r"[0-9a-f]{64}")


class EvidenceError(RuntimeError):
    """Raised when release evidence is missing, mutable, or inconsistent."""


def _regular_single_link(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return False
    return stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1


def _checked_files(root: Path) -> list[Path]:
    if root.is_symlink() or not root.is_dir():
        raise EvidenceError(f"unsafe or missing directory: {root}")
    files: list[Path] = []
    for entry in sorted(root.rglob("*"), key=lambda value: value.as_posix()):
        if entry.is_symlink():
            raise EvidenceError(f"unsafe symbolic link: {entry}")
        if entry.is_dir():
            continue
        if not _regular_single_link(entry):
            raise EvidenceError(f"unsafe filesystem entry: {entry}")
        files.append(entry)
    if not files:
        raise EvidenceError(f"empty artifact directory: {root}")
    return files


def digest_path(path: Path) -> str:
    """Digest a regular file or a complete, path-bound directory tree."""

    if _regular_single_link(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()
    files = _checked_files(path)
    digest = hashlib.sha256()
    for entry in files:
        relative = entry.relative_to(path).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(entry.stat().st_size.to_bytes(8, "big"))
        digest.update(hashlib.sha256(entry.read_bytes()).digest())
    return digest.hexdigest()


def path_size(path: Path) -> int:
    if _regular_single_link(path):
        return path.stat().st_size
    return sum(entry.stat().st_size for entry in _checked_files(path))


def artifact_descriptor(project_root: Path, path: Path) -> dict[str, object]:
    try:
        relative = path.relative_to(project_root).as_posix()
    except ValueError as error:
        raise EvidenceError(f"artifact is outside project root: {path}") from error
    return {
        "path": relative,
        "kind": "file" if _regular_single_link(path) else "directory",
        "sha256": digest_path(path),
        "size_bytes": path_size(path),
    }


def canonical_json_bytes(payload: object) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _sidecar_path(path: Path) -> Path:
    return path.with_suffix(".sha256")


def read_digest_sidecar(path: Path) -> str:
    sidecar = _sidecar_path(path)
    if not _regular_single_link(path) or not _regular_single_link(sidecar):
        raise EvidenceError(f"evidence or digest sidecar is missing or unsafe: {path}")
    expected = f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
    actual = sidecar.read_text(encoding="ascii")
    if actual != expected:
        raise EvidenceError(f"evidence digest mismatch: {path}")
    digest = actual.split(" ", 1)[0]
    if not _SHA256.fullmatch(digest):
        raise EvidenceError(f"invalid evidence digest: {path}")
    return digest


def write_digest_sidecar(path: Path) -> str:
    if not _regular_single_link(path):
        raise EvidenceError(f"artifact is missing or unsafe: {path}")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    sidecar = _sidecar_path(path)
    data = f"{digest}  {path.name}\n".encode("ascii")
    if sidecar.exists():
        if not _regular_single_link(sidecar) or sidecar.read_bytes() != data:
            raise EvidenceError(f"artifact digest sidecar differs: {path}")
    else:
        _exclusive_write(sidecar, data)
    path.chmod(0o444)
    return digest


def read_verified_json(path: Path) -> dict[str, Any]:
    read_digest_sidecar(path)
    try:
        payload = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as error:
        raise EvidenceError(f"invalid JSON evidence: {path}") from error
    if not isinstance(payload, dict):
        raise EvidenceError(f"JSON evidence must be an object: {path}")
    return payload


def _exclusive_write(path: Path, data: bytes) -> None:
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow, 0o600)
    try:
        os.write(descriptor, data)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    path.chmod(0o444)


def write_immutable_json(path: Path, payload: dict[str, Any]) -> str:
    """Create canonical JSON plus a digest sidecar, or verify an identical prior write."""

    if path.is_symlink() or path.parent.is_symlink():
        raise EvidenceError(f"unsafe evidence path: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    data = canonical_json_bytes(payload)
    digest = hashlib.sha256(data).hexdigest()
    sidecar = _sidecar_path(path)
    digest_data = f"{digest}  {path.name}\n".encode("ascii")
    if path.exists() or sidecar.exists():
        if not _regular_single_link(path) or not _regular_single_link(sidecar):
            raise EvidenceError(f"existing evidence is unsafe: {path}")
        if path.read_bytes() != data or sidecar.read_bytes() != digest_data:
            raise EvidenceError(f"immutable evidence differs from requested content: {path}")
        return digest
    try:
        _exclusive_write(path, data)
        _exclusive_write(sidecar, digest_data)
    except Exception:
        if path.exists() and not sidecar.exists() and _regular_single_link(path):
            path.unlink()
        raise
    return digest
