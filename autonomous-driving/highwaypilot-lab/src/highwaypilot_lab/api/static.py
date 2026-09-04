"""Closed static-file allowlist with traversal and symlink containment checks."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from urllib.parse import unquote


MIME_TYPES = {
    ".html": "text/html",
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".css": "text/css",
    ".json": "application/json",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".glb": "model/gltf-binary",
    ".gltf": "model/gltf+json",
    ".wasm": "application/wasm",
}


class StaticAssetNotFound(FileNotFoundError):
    pass


class StaticAssetStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve(strict=True)
        if not self.root.is_dir():
            raise ValueError("static root must be a directory")

    @staticmethod
    def _safe_relative_path(asset_path: str, raw_path: bytes) -> PurePosixPath:
        raw = raw_path.decode("latin-1")
        decoded = raw
        for _ in range(3):
            decoded = unquote(decoded)
            if any(part == ".." for part in PurePosixPath(decoded).parts):
                raise StaticAssetNotFound(asset_path)
        relative = PurePosixPath(asset_path or "index.html")
        if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
            raise StaticAssetNotFound(asset_path)
        return relative

    def read(self, asset_path: str, raw_path: bytes) -> tuple[bytes, str]:
        relative = self._safe_relative_path(asset_path, raw_path)
        mime_type = MIME_TYPES.get(relative.suffix.lower())
        if mime_type is None:
            raise StaticAssetNotFound(asset_path)
        unresolved = self.root.joinpath(*relative.parts)
        try:
            target = unresolved.resolve(strict=True)
        except (OSError, RuntimeError) as error:
            raise StaticAssetNotFound(asset_path) from error
        if not target.is_relative_to(self.root) or not target.is_file():
            raise StaticAssetNotFound(asset_path)
        return target.read_bytes(), mime_type
