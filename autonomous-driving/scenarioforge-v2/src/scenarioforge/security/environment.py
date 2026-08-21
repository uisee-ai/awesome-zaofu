from __future__ import annotations

import os
from collections.abc import Mapping

from .errors import SecurityViolation


FIXED_WORKER_ENVIRONMENT = {
    "PATH": os.defpath,
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
}


def build_worker_environment(overrides: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return a secret-free environment; caller overrides may only restate fixed values."""
    if overrides:
        invalid_keys = set(overrides) - set(FIXED_WORKER_ENVIRONMENT)
        changed_values = {
            key
            for key in set(overrides) & set(FIXED_WORKER_ENVIRONMENT)
            if overrides[key] != FIXED_WORKER_ENVIRONMENT[key]
        }
        if invalid_keys or changed_values:
            raise SecurityViolation(
                "Worker environment contains a non-whitelisted key or value",
                code="unexpected_environment",
            )
    return dict(FIXED_WORKER_ENVIRONMENT)
