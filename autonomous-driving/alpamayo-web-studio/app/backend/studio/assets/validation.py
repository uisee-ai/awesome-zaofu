"""Pure validation for uploaded image metadata.

This module deliberately accepts metadata and bytes only; it never accepts a URL
or performs network I/O, so user-controlled input cannot trigger server-side
requests.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
AcceptedImageContentType = Literal["image/jpeg", "image/png"]


class AssetUploadValidationError(ValueError):
    """A rejected upload with a stable, client-safe reason code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class AssetUpload:
    filename: str
    content_type: str
    size_bytes: int


def validate_asset_upload(upload: AssetUpload) -> AssetUpload:
    """Accept a bounded JPEG/PNG upload whose filename agrees with its MIME type."""
    if upload.content_type not in ("image/jpeg", "image/png"):
        raise AssetUploadValidationError("UNSUPPORTED_MIME", "只支持 JPEG 或 PNG 图片")
    if upload.size_bytes <= 0:
        raise AssetUploadValidationError("EMPTY_FILE", "上传文件不能为空")
    if upload.size_bytes > MAX_UPLOAD_BYTES:
        raise AssetUploadValidationError("FILE_TOO_LARGE", "图片不能超过 10 MiB")

    suffixes = (".jpg", ".jpeg") if upload.content_type == "image/jpeg" else (".png",)
    if not upload.filename.lower().endswith(suffixes):
        raise AssetUploadValidationError("EXTENSION_MISMATCH", "图片扩展名必须与 MIME 类型一致")
    return upload
