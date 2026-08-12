"""Validation for the repository's non-sensitive, replayable golden scene."""

from __future__ import annotations

import hashlib
import re
import struct
import zlib
from collections.abc import Mapping, Sequence
from typing import Any

EXPECTED_CAMERA_IDS = (0, 1, 2, 6)
FRAME_COUNT = 4
HISTORY_LENGTH = 16
SCHEMA_VERSION = "golden-scene-provenance.v1"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
SENSITIVE_KEY_PATTERN = re.compile(r"(?:secret|password|api[_-]?key|token)", re.IGNORECASE)
SENSITIVE_VALUE_PATTERN = re.compile(r"(?:data:|-----BEGIN|\bBearer\s+|\bsk-[A-Za-z0-9])", re.IGNORECASE)
BASE64_PAYLOAD_PATTERN = re.compile(r"^[A-Za-z0-9+/]{128,}={0,2}$")
REPLAY_GENERATOR = "synthetic-scene-renderer"
REPLAY_GENERATOR_VERSION = "1.0.0"
EXPECTED_ASSET_REFS = frozenset(
    f"renders/camera-{camera_id}/frame-{frame_index:03d}.png"
    for camera_id in EXPECTED_CAMERA_IDS
    for frame_index in range(FRAME_COUNT)
)


class GoldenSceneProvenanceError(ValueError):
    """Raised when a golden-scene fixture cannot be safely replayed."""


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise GoldenSceneProvenanceError(f"{name} must be an object")
    return value


def _non_empty_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GoldenSceneProvenanceError(f"{name} must be non-empty text")
    return value


def _reject_sensitive_content(value: object, path: str = "fixture") -> None:
    if isinstance(value, Mapping):
        for key, nested_value in value.items():
            key_text = str(key)
            if SENSITIVE_KEY_PATTERN.search(key_text):
                raise GoldenSceneProvenanceError(f"sensitive key is not allowed at {path}.{key_text}")
            _reject_sensitive_content(nested_value, f"{path}.{key_text}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, nested_value in enumerate(value):
            _reject_sensitive_content(nested_value, f"{path}[{index}]")
    elif isinstance(value, str):
        normalized = re.sub(r"\s+", "", value)
        if SENSITIVE_VALUE_PATTERN.search(value) or BASE64_PAYLOAD_PATTERN.fullmatch(normalized):
            raise GoldenSceneProvenanceError(f"sensitive or inline asset content is not allowed at {path}")


def _validate_history(history: Mapping[str, Any]) -> None:
    for field, width in (("positions", 3), ("rotations", 3)):
        values = history.get(field)
        if not isinstance(values, Sequence) or isinstance(values, (str, bytes)) or len(values) != HISTORY_LENGTH:
            raise GoldenSceneProvenanceError(f"history.{field} must contain {HISTORY_LENGTH} entries")
        if field == "positions" and any(not isinstance(point, Sequence) or len(point) != width for point in values):
            raise GoldenSceneProvenanceError("history.positions must contain XYZ triples")
        if field == "rotations" and any(
            not isinstance(matrix, Sequence)
            or len(matrix) != width
            or any(not isinstance(row, Sequence) or len(row) != width for row in matrix)
            for matrix in values
        ):
            raise GoldenSceneProvenanceError("history.rotations must contain 3x3 matrices")


def _png_chunk(chunk_type: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + chunk_type
        + payload
        + struct.pack(">I", zlib.crc32(chunk_type + payload) & 0xFFFFFFFF)
    )


def _generate_replay_asset(asset_ref: str, replay: Mapping[str, Any]) -> bytes:
    if asset_ref not in EXPECTED_ASSET_REFS:
        raise GoldenSceneProvenanceError(f"frame.assetRef does not resolve to a golden replay asset: {asset_ref}")

    entropy = hashlib.sha256(
        f"{REPLAY_GENERATOR}@{REPLAY_GENERATOR_VERSION}:{replay['seed']}:{asset_ref}".encode("utf-8")
    ).digest()
    raw_scanline = b"\x00" + entropy[:4]
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
        + _png_chunk(b"IDAT", zlib.compress(raw_scanline))
        + _png_chunk(b"IEND", b"")
    )


def _validate_cameras(cameras: object, replay: Mapping[str, Any]) -> None:
    if not isinstance(cameras, Sequence) or isinstance(cameras, (str, bytes)):
        raise GoldenSceneProvenanceError("scene.cameras must be an array")
    camera_records = [_mapping(camera, "scene.camera") for camera in cameras]
    if tuple(camera.get("cameraId") for camera in camera_records) != EXPECTED_CAMERA_IDS:
        raise GoldenSceneProvenanceError("golden scene must use cameras 0, 1, 2, and 6 in order")

    seen_asset_refs: set[str] = set()
    for camera in camera_records:
        frames = camera.get("frames")
        if not isinstance(frames, Sequence) or isinstance(frames, (str, bytes)) or len(frames) != FRAME_COUNT:
            raise GoldenSceneProvenanceError("each golden-scene camera must contain four frames")
        for frame in frames:
            record = _mapping(frame, "scene.camera.frame")
            asset_ref = _non_empty_text(record.get("assetRef"), "frame.assetRef")
            if asset_ref.startswith("/") or ".." in asset_ref.split("/"):
                raise GoldenSceneProvenanceError("frame.assetRef must be a relative replay asset reference")
            if record.get("contentType") not in {"image/jpeg", "image/png"}:
                raise GoldenSceneProvenanceError("frame.contentType must be JPEG or PNG")
            if not SHA256_PATTERN.fullmatch(str(record.get("sha256", ""))):
                raise GoldenSceneProvenanceError("frame.sha256 must be a SHA-256 digest")
            if asset_ref in seen_asset_refs:
                raise GoldenSceneProvenanceError("frame.assetRef must be unique across the golden scene")
            seen_asset_refs.add(asset_ref)
            generated_asset = _generate_replay_asset(asset_ref, replay)
            if hashlib.sha256(generated_asset).hexdigest() != record["sha256"]:
                raise GoldenSceneProvenanceError("frame.sha256 does not match the resolved replay asset")

    if seen_asset_refs != EXPECTED_ASSET_REFS:
        raise GoldenSceneProvenanceError("golden scene must resolve each of its sixteen replay assets exactly once")


def validate_golden_scene_provenance(manifest: Mapping[str, Any]) -> None:
    """Raise when manifest violates reproducibility or non-sensitive-data policy."""
    _reject_sensitive_content(manifest)
    if manifest.get("schemaVersion") != SCHEMA_VERSION:
        raise GoldenSceneProvenanceError(f"schemaVersion must be {SCHEMA_VERSION}")

    scene = _mapping(manifest.get("scene"), "scene")
    _non_empty_text(scene.get("navigationInstruction"), "scene.navigationInstruction")
    provenance = _mapping(manifest.get("provenance"), "provenance")
    _non_empty_text(provenance.get("sourceId"), "provenance.sourceId")
    _non_empty_text(provenance.get("sourceType"), "provenance.sourceType")
    authorization = _mapping(provenance.get("authorization"), "provenance.authorization")
    for field in ("reference", "approvedFor", "approvedByRole", "approvedAt"):
        _non_empty_text(authorization.get(field), f"provenance.authorization.{field}")
    if "internal demo" not in str(authorization["approvedFor"]).lower():
        raise GoldenSceneProvenanceError("authorization must be restricted to the internal demo")

    replay = _mapping(provenance.get("replay"), "provenance.replay")
    for field in ("generator", "generatorVersion", "checksumAlgorithm"):
        _non_empty_text(replay.get(field), f"provenance.replay.{field}")
    if replay["generator"] != REPLAY_GENERATOR or replay["generatorVersion"] != REPLAY_GENERATOR_VERSION:
        raise GoldenSceneProvenanceError("provenance.replay must identify the supported deterministic generator version")
    if replay["checksumAlgorithm"] != "sha256":
        raise GoldenSceneProvenanceError("provenance.replay.checksumAlgorithm must be sha256")
    if not isinstance(replay.get("seed"), int) or isinstance(replay["seed"], bool):
        raise GoldenSceneProvenanceError("provenance.replay.seed must be an integer")

    _validate_cameras(scene.get("cameras"), replay)
    _validate_history(_mapping(scene.get("history"), "scene.history"))
