from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from jsonschema import Draft202012Validator

from .canonical import canonical_bytes, freeze_json
from .models import ScenarioDocument, ScenarioInstance
from .schema import SCENARIO_SPEC_SCHEMA


@dataclass(frozen=True)
class InputLimits:
    byte_limit: int = 65_536
    max_depth: int = 16
    max_object_members: int = 64
    max_array_items: int = 64
    max_string_bytes: int = 1_024
    max_absolute_number: float = 1_000_000.0


class StrictJSONError(ValueError):
    def __init__(self, message: str, *, stage: str, code: str, path: str = "$") -> None:
        super().__init__(message)
        self.stage = stage
        self.code = code
        self.path = path


def _duplicate_rejecting_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise StrictJSONError(
                f"duplicate object key: {key}",
                stage="strict_parse",
                code="duplicate_key",
            )
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise StrictJSONError(
        f"non-finite JSON number: {value}",
        stage="strict_parse",
        code="non_finite_number",
    )


def strict_loads(payload: bytes) -> Any:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise StrictJSONError(
            "input is not valid UTF-8",
            stage="strict_parse",
            code="invalid_utf8",
        ) from error
    try:
        return json.loads(
            text,
            object_pairs_hook=_duplicate_rejecting_object,
            parse_constant=_reject_constant,
        )
    except StrictJSONError:
        raise
    except (json.JSONDecodeError, RecursionError) as error:
        raise StrictJSONError(
            "input is not strict JSON",
            stage="strict_parse",
            code="invalid_json",
        ) from error


def _format_path(parts: Iterable[object]) -> str:
    path = "$"
    for part in parts:
        if isinstance(part, int):
            path += f"[{part}]"
        else:
            path += f".{part}"
    return path


def _walk_limits(value: Any, limits: InputLimits, *, path: str = "$", depth: int = 1) -> None:
    if depth > limits.max_depth:
        raise StrictJSONError(
            "JSON structure exceeds maximum depth",
            stage="schema_validation",
            code="max_depth_exceeded",
            path=path,
        )
    if isinstance(value, dict):
        if len(value) > limits.max_object_members:
            raise StrictJSONError(
                "JSON object exceeds member limit",
                stage="schema_validation",
                code="object_members_exceeded",
                path=path,
            )
        for key, item in value.items():
            if len(key.encode("utf-8")) > limits.max_string_bytes:
                raise StrictJSONError(
                    "JSON key exceeds string byte limit",
                    stage="schema_validation",
                    code="string_bytes_exceeded",
                    path=path,
                )
            _walk_limits(item, limits, path=f"{path}.{key}", depth=depth + 1)
    elif isinstance(value, list):
        if len(value) > limits.max_array_items:
            raise StrictJSONError(
                "JSON array exceeds item limit",
                stage="schema_validation",
                code="array_items_exceeded",
                path=path,
            )
        for index, item in enumerate(value):
            _walk_limits(item, limits, path=f"{path}[{index}]", depth=depth + 1)
    elif isinstance(value, str):
        if len(value.encode("utf-8")) > limits.max_string_bytes:
            raise StrictJSONError(
                "JSON string exceeds byte limit",
                stage="schema_validation",
                code="string_bytes_exceeded",
                path=path,
            )
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(value) or abs(value) > limits.max_absolute_number:
            raise StrictJSONError(
                "JSON number exceeds the allowed finite range",
                stage="schema_validation",
                code="number_range_exceeded",
                path=path,
            )


_WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")
_FORBIDDEN_KEYS = ("secret", "token", "password", "authorization", "executable", "command", "module", "pythonpath")


def _walk_forbidden(value: Any, *, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            lowered = key.lower()
            if any(forbidden in lowered for forbidden in _FORBIDDEN_KEYS):
                raise StrictJSONError(
                    "field can carry secret or executable control content",
                    stage="schema_validation",
                    code="forbidden_content",
                    path=f"{path}.{key}",
                )
            _walk_forbidden(item, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _walk_forbidden(item, path=f"{path}[{index}]")
    elif isinstance(value, str):
        lowered = value.lower()
        path_like = (
            value.startswith("/")
            or bool(_WINDOWS_ABSOLUTE.match(value))
            or any(part == ".." for part in value.replace("\\", "/").split("/"))
            or lowered.startswith(("file:", "http://", "https://"))
        )
        if path_like:
            raise StrictJSONError(
                "host path, parent traversal, URI, or network URL is forbidden",
                stage="schema_validation",
                code="forbidden_content",
                path=path,
            )


def _semantic_validate(value: Mapping[str, Any]) -> None:
    participants = value["participants"]
    ids = [participant["id"] for participant in participants]
    if len(ids) != len(set(ids)):
        raise StrictJSONError(
            "participant IDs must be unique",
            stage="schema_validation",
            code="schema_validation_failed",
            path="$.participants",
        )
    ego = [participant for participant in participants if participant["role"] == "ego"]
    social = [participant for participant in participants if participant["role"] == "social"]
    if len(ego) != 1 or not social:
        raise StrictJSONError(
            "scenario requires exactly one ego and at least one social vehicle",
            stage="schema_validation",
            code="schema_validation_failed",
            path="$.participants",
        )
    participant_ids = set(ids)
    for index, event in enumerate(value["events"]):
        if event["participant_id"] not in participant_ids:
            raise StrictJSONError(
                "event participant does not exist",
                stage="schema_validation",
                code="schema_validation_failed",
                path=f"$.events[{index}].participant_id",
            )
    if value["parameters"]["brake_tick"] >= value["constraints"]["max_steps"]:
        raise StrictJSONError(
            "brake_tick must occur before max_steps",
            stage="schema_validation",
            code="schema_validation_failed",
            path="$.parameters.brake_tick",
        )


def validate_scenario_spec(value: Any, limits: InputLimits) -> Mapping[str, Any]:
    _walk_limits(value, limits)
    _walk_forbidden(value)
    validator = Draft202012Validator(SCENARIO_SPEC_SCHEMA)
    error = next(iter(sorted(validator.iter_errors(value), key=lambda item: list(item.absolute_path))), None)
    if error is not None:
        raise StrictJSONError(
            error.message,
            stage="schema_validation",
            code="schema_validation_failed",
            path=_format_path(error.absolute_path),
        )
    assert isinstance(value, Mapping)
    _semantic_validate(value)
    return value


def _read_regular_nofollow(path: Path, byte_limit: int) -> bytes:
    try:
        initial = path.lstat()
    except OSError as error:
        raise StrictJSONError(
            "input is not an accessible regular file",
            stage="limited_read",
            code="not_regular_file",
        ) from error
    if not stat.S_ISREG(initial.st_mode):
        raise StrictJSONError(
            "input is not a regular file",
            stage="limited_read",
            code="not_regular_file",
        )
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise StrictJSONError(
            "input is not an accessible regular file",
            stage="limited_read",
            code="not_regular_file",
        ) from error
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (initial.st_dev, initial.st_ino):
            raise StrictJSONError(
                "input changed during no-follow open",
                stage="limited_read",
                code="read_boundary_changed",
            )
        chunks: list[bytes] = []
        remaining = byte_limit + 1
        while remaining:
            chunk = os.read(descriptor, min(remaining, 65_536))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
    finally:
        os.close(descriptor)
    if len(payload) > byte_limit:
        raise StrictJSONError(
            "input exceeds the configured byte limit",
            stage="limited_read",
            code="byte_limit_exceeded",
        )
    return payload


def load_scenario(path: Path | str, *, limits: InputLimits | None = None) -> ScenarioDocument:
    effective_limits = limits or InputLimits()
    source_path = Path(path)
    payload = _read_regular_nofollow(source_path, effective_limits.byte_limit)
    value = validate_scenario_spec(strict_loads(payload), effective_limits)
    normalized = canonical_bytes(value)
    return ScenarioDocument(
        value=freeze_json(value),
        raw_digest=hashlib.sha256(payload).hexdigest(),
        canonical_digest=hashlib.sha256(normalized).hexdigest(),
        canonical_payload=normalized,
        source_path=source_path,
    )


def instantiate_scenario(document: ScenarioDocument) -> ScenarioInstance:
    return ScenarioInstance.from_spec(document.value, document.canonical_digest)
