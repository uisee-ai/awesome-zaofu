from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from scenarioforge.core import InputLimits, StrictJSONError, load_scenario, strict_loads
from scenarioforge.core.models import ScenarioDocument

from .errors import SecurityViolation


@dataclass(frozen=True)
class ArtifactVerification:
    path: str
    size_bytes: int
    digest: str
    validation: str

    def to_dict(self) -> dict[str, str | int]:
        return {
            "path": self.path,
            "size_bytes": self.size_bytes,
            "digest": self.digest,
            "validation": self.validation,
        }


def load_untrusted_scenario(
    path: Path | str,
    *,
    limits: InputLimits | None = None,
) -> ScenarioDocument:
    try:
        return load_scenario(path, limits=limits)
    except StrictJSONError as error:
        raise SecurityViolation(
            "untrusted scenario input was rejected",
            code=error.code,
        ) from error


def _resolved_directory(path: Path, *, label: str) -> Path:
    if path.is_symlink():
        raise SecurityViolation(f"{label} cannot be a symbolic link", code="link_or_special_file")
    try:
        mode = path.lstat().st_mode
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise SecurityViolation(f"{label} is not an accessible directory", code="path_boundary_escape") from error
    if not stat.S_ISDIR(mode):
        raise SecurityViolation(f"{label} is not a directory", code="link_or_special_file")
    return resolved


def _require_descendant(path: Path, root: Path, *, label: str) -> None:
    try:
        path.relative_to(root)
    except ValueError as error:
        raise SecurityViolation(f"{label} escapes the workspace", code="path_boundary_escape") from error
    if path == root:
        raise SecurityViolation(f"{label} cannot be the workspace root", code="path_boundary_escape")


def _reject_links_and_special_files(root: Path) -> None:
    for path in root.rglob("*"):
        mode = path.lstat().st_mode
        if path.is_symlink() or not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
            raise SecurityViolation(
                "isolated directory contains a link or special file",
                code="link_or_special_file",
            )


def validate_isolated_directories(
    input_snapshot: Path,
    output_staging: Path,
    *,
    workspace: Path,
) -> None:
    workspace_resolved = _resolved_directory(Path(workspace), label="workspace")
    input_resolved = _resolved_directory(Path(input_snapshot), label="InputSnapshot")
    output_resolved = _resolved_directory(Path(output_staging), label="OutputStaging")
    _require_descendant(input_resolved, workspace_resolved, label="InputSnapshot")
    _require_descendant(output_resolved, workspace_resolved, label="OutputStaging")
    common = Path(os.path.commonpath([input_resolved, output_resolved]))
    if common in {input_resolved, output_resolved}:
        raise SecurityViolation(
            "InputSnapshot and OutputStaging overlap",
            code="path_overlap",
        )
    _reject_links_and_special_files(input_resolved)
    _reject_links_and_special_files(output_resolved)


def verify_snapshot_binding(input_snapshot: Path, *, expected_digest: str) -> str:
    # Import lazily so importing the public security package does not recurse
    # through runtime.__init__ -> supervisor -> security.
    from scenarioforge.runtime.snapshot import SnapshotError, validate_input_snapshot

    try:
        actual = validate_input_snapshot(input_snapshot)
    except (SnapshotError, StrictJSONError, OSError, KeyError, TypeError, ValueError) as error:
        raise SecurityViolation(
            "frozen InputSnapshot failed integrity validation",
            code="snapshot_tampered",
        ) from error
    if actual != expected_digest:
        raise SecurityViolation(
            "frozen InputSnapshot digest does not match the RunRequest",
            code="snapshot_tampered",
        )
    return actual


def _read_regular_nofollow(path: Path, *, byte_limit: int) -> bytes:
    try:
        initial = path.lstat()
    except OSError as error:
        raise SecurityViolation("artifact is missing", code="artifact_set_invalid") from error
    if not stat.S_ISREG(initial.st_mode) or path.is_symlink():
        raise SecurityViolation(
            "artifact is a link or special file",
            code="link_or_special_file",
        )
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise SecurityViolation(
            "artifact cannot be opened without following links",
            code="link_or_special_file",
        ) from error
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (
            initial.st_dev,
            initial.st_ino,
        ):
            raise SecurityViolation("artifact changed during open", code="artifact_tampered")
        chunks: list[bytes] = []
        remaining = byte_limit + 1
        while remaining:
            chunk = os.read(descriptor, min(remaining, 65_536))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        after = os.fstat(descriptor)
        if (after.st_dev, after.st_ino, after.st_size) != (
            opened.st_dev,
            opened.st_ino,
            opened.st_size,
        ):
            raise SecurityViolation("artifact changed during read", code="artifact_tampered")
    finally:
        os.close(descriptor)
    if len(payload) > byte_limit or initial.st_size > byte_limit:
        raise SecurityViolation(
            "artifact exceeds its frozen size limit",
            code="artifact_size_limit_exceeded",
        )
    return payload


def verify_output_artifacts(
    root: Path,
    *,
    required_names: tuple[str, ...],
    max_file_bytes: int,
    artifact_limit_bytes: int,
    expected_digests: Mapping[str, str] | None = None,
) -> tuple[ArtifactVerification, ...]:
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise SecurityViolation("OutputStaging is not a regular directory", code="link_or_special_file")
    if len(set(required_names)) != len(required_names) or any(
        not name or Path(name).name != name or name in {".", ".."} for name in required_names
    ):
        raise SecurityViolation("artifact contract contains an unsafe path", code="artifact_set_invalid")
    actual_names = tuple(sorted(path.name for path in root.iterdir()))
    if actual_names != tuple(sorted(required_names)):
        raise SecurityViolation("artifact set is incomplete or unexpected", code="artifact_set_invalid")
    total = 0
    verified: list[ArtifactVerification] = []
    for name in sorted(required_names):
        payload = _read_regular_nofollow(root / name, byte_limit=max_file_bytes)
        total += len(payload)
        if total > artifact_limit_bytes:
            raise SecurityViolation(
                "artifact set exceeds the aggregate size limit",
                code="artifact_size_limit_exceeded",
            )
        try:
            strict_loads(payload)
        except StrictJSONError as error:
            raise SecurityViolation("artifact is not strict JSON", code="artifact_invalid_json") from error
        digest = hashlib.sha256(payload).hexdigest()
        if expected_digests is not None and name in expected_digests and digest != expected_digests[name]:
            raise SecurityViolation(
                "artifact digest does not match frozen evidence",
                code="artifact_digest_mismatch",
            )
        verified.append(
            ArtifactVerification(
                path=name,
                size_bytes=len(payload),
                digest=digest,
                validation="verified",
            )
        )
    return tuple(verified)
