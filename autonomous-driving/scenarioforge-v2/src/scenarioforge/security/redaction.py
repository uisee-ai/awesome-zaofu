from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .errors import SecurityViolation


_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(secret|token|password|api[_-]?key)\s*=\s*([^\s,;]+)"
)


@dataclass(frozen=True)
class SanitizedLog:
    text: str
    truncated: bool


def redact_log(
    value: str,
    *,
    sensitive_values: tuple[str, ...] = (),
    redacted_paths: tuple[Path, ...] = (),
    limit_bytes: int,
) -> SanitizedLog:
    if limit_bytes <= 0:
        raise SecurityViolation("log byte limit must be positive", code="invalid_resource_policy")
    sanitized = value
    for secret in sensitive_values:
        if secret:
            sanitized = sanitized.replace(secret, "<redacted>")
    sanitized = _SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}=<redacted>", sanitized)
    for path in sorted((str(item) for item in redacted_paths), key=len, reverse=True):
        if path:
            sanitized = sanitized.replace(path, "<project>")
    payload = sanitized.encode("utf-8")
    if len(payload) <= limit_bytes:
        return SanitizedLog(text=sanitized, truncated=False)
    suffix = b"<truncated>"
    if limit_bytes <= len(suffix):
        return SanitizedLog(
            text=suffix[:limit_bytes].decode("ascii"),
            truncated=True,
        )
    retained = payload[: max(0, limit_bytes - len(suffix))]
    text = retained.decode("utf-8", errors="ignore") + suffix.decode("ascii")
    return SanitizedLog(text=text, truncated=True)
