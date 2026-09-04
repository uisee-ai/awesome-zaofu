from __future__ import annotations

import copy
import datetime as dt
import json
import math
import uuid
from collections.abc import Mapping
from typing import Any

SCHEMA_VERSION = "highwaypilot-replay/v1"
TOP_LEVEL_FIELDS = {
    "schema_version",
    "episode_id",
    "initial_frame",
    "actions",
    "strategy",
    "seed",
    "effective_config",
    "rng_contract",
    "versions",
    "reward_decomposition",
    "result",
    "termination_reason",
    "ownership",
}
VERSION_FIELDS = {"application", "highway_env", "gymnasium", "python", "git", "platform"}
OWNERSHIP_FIELDS = {"project_id", "temporary_session_id", "created_at"}
ACTION_FIELDS = {"index", "action", "frame", "reward"}


class ReplayValidationError(ValueError):
    """A replay is not an unambiguous instance of highwaypilot-replay/v1."""


class LibraryError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status: int = 400,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.retryable = retryable

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "status": self.status,
            "retryable": self.retryable,
        }


class EpisodeNotFound(LibraryError):
    def __init__(self) -> None:
        super().__init__("EPISODE_NOT_FOUND", "episode is unavailable", status=404)

    def as_dict(self) -> dict[str, str]:
        # Deliberately identical for absent and wrong-session temporary records.
        return {"code": self.code, "message": self.message}


class SimulatedCrash(RuntimeError):
    """Test-only interruption point used to exercise durable recovery."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ReplayValidationError(f"duplicate key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ReplayValidationError(f"non-finite number: {value}")


def parse_replay_json(raw: bytes | bytearray | memoryview | str) -> dict[str, Any]:
    try:
        text = bytes(raw).decode("utf-8") if not isinstance(raw, str) else raw
    except UnicodeDecodeError as error:
        raise ReplayValidationError("replay must be valid UTF-8") from error
    try:
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except ReplayValidationError:
        raise
    except (json.JSONDecodeError, TypeError) as error:
        raise ReplayValidationError("replay must contain one complete JSON document") from error
    return validate_replay(value)


def _require_exact_fields(value: Mapping[str, Any], expected: set[str], path: str) -> None:
    actual = set(value)
    unknown = actual - expected
    missing = expected - actual
    if unknown:
        raise ReplayValidationError(f"{path} has unknown field: {sorted(unknown)[0]}")
    if missing:
        raise ReplayValidationError(f"{path} is missing field: {sorted(missing)[0]}")


def _require_mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ReplayValidationError(f"{path} must be an object")
    return value


def _require_json_value(value: Any, path: str) -> None:
    if value is None or isinstance(value, (str, bool)):
        return
    if isinstance(value, int):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ReplayValidationError(f"{path} contains a non-finite number")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _require_json_value(item, f"{path}[{index}]")
        return
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ReplayValidationError(f"{path} object keys must be strings")
        for key, item in value.items():
            _require_json_value(item, f"{path}.{key}")
        return
    raise ReplayValidationError(f"{path} is not a JSON value")


def _nonempty_string(value: Any, path: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ReplayValidationError(f"{path} must be a non-empty string")


def validate_replay(document: Any) -> dict[str, Any]:
    replay = _require_mapping(document, "replay")
    _require_exact_fields(replay, TOP_LEVEL_FIELDS, "replay")
    if replay["schema_version"] != SCHEMA_VERSION:
        raise ReplayValidationError(f"schema_version must be {SCHEMA_VERSION}")
    _nonempty_string(replay["episode_id"], "episode_id")
    if any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for character in replay["episode_id"]):
        raise ReplayValidationError("episode_id contains an unsafe character")
    if isinstance(replay["seed"], bool) or not isinstance(replay["seed"], int):
        raise ReplayValidationError("seed must be an integer")
    for field in ("initial_frame", "strategy", "effective_config", "rng_contract"):
        _require_mapping(replay[field], field)
    versions = _require_mapping(replay["versions"], "versions")
    _require_exact_fields(versions, VERSION_FIELDS, "versions")
    for key, value in versions.items():
        _nonempty_string(value, f"versions.{key}")
    ownership = _require_mapping(replay["ownership"], "ownership")
    _require_exact_fields(ownership, OWNERSHIP_FIELDS, "ownership")
    for key, value in ownership.items():
        _nonempty_string(value, f"ownership.{key}")
    rewards = _require_mapping(replay["reward_decomposition"], "reward_decomposition")
    for key, value in rewards.items():
        _nonempty_string(key, "reward_decomposition key")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ReplayValidationError(f"reward_decomposition.{key} must be finite")
    actions = replay["actions"]
    if not isinstance(actions, list):
        raise ReplayValidationError("actions must be an array")
    for expected_index, action_value in enumerate(actions):
        action = _require_mapping(action_value, f"actions[{expected_index}]")
        _require_exact_fields(action, ACTION_FIELDS, f"actions[{expected_index}]")
        if action["index"] != expected_index:
            raise ReplayValidationError("action indexes must be contiguous from zero")
        _nonempty_string(action["action"], f"actions[{expected_index}].action")
        _require_mapping(action["frame"], f"actions[{expected_index}].frame")
        action_reward = _require_mapping(action["reward"], f"actions[{expected_index}].reward")
        for key, value in action_reward.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ReplayValidationError(f"actions[{expected_index}].reward.{key} must be finite")
    _nonempty_string(replay["result"], "result")
    _nonempty_string(replay["termination_reason"], "termination_reason")
    _require_json_value(replay, "replay")
    return copy.deepcopy(dict(replay))


def canonical_replay_bytes(document: Any) -> bytes:
    replay = validate_replay(document)
    return json.dumps(
        replay,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


class EpisodeRecorder:
    def __init__(
        self,
        *,
        session_id: str,
        project_id: str,
        initial_frame: Mapping[str, Any],
        strategy: Mapping[str, Any],
        seed: int,
        effective_config: Mapping[str, Any],
        rng_contract: Mapping[str, Any],
        versions: Mapping[str, str],
        episode_id: str | None = None,
        created_at: str | None = None,
    ) -> None:
        self._document: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "episode_id": episode_id or f"episode-{uuid.uuid4().hex}",
            "initial_frame": copy.deepcopy(dict(initial_frame)),
            "actions": [],
            "strategy": copy.deepcopy(dict(strategy)),
            "seed": seed,
            "effective_config": copy.deepcopy(dict(effective_config)),
            "rng_contract": copy.deepcopy(dict(rng_contract)),
            "versions": copy.deepcopy(dict(versions)),
            "reward_decomposition": {},
            "result": "recording",
            "termination_reason": "not_terminated",
            "ownership": {
                "project_id": project_id,
                "temporary_session_id": session_id,
                "created_at": created_at or dt.datetime.now(dt.timezone.utc).isoformat(),
            },
        }
        self._finished = False

    def set_strategy(self, strategy: Mapping[str, Any]) -> None:
        """Update strategy metadata without changing the recorded ownership."""
        if self._finished:
            return
        self._document["strategy"] = copy.deepcopy(dict(strategy))

    def append(self, action: str, frame: Mapping[str, Any], reward: Mapping[str, float]) -> None:
        if self._finished:
            raise RuntimeError("episode is already finished")
        item = {
            "index": len(self._document["actions"]),
            "action": action,
            "frame": copy.deepcopy(dict(frame)),
            "reward": copy.deepcopy(dict(reward)),
        }
        self._document["actions"].append(item)
        totals = self._document["reward_decomposition"]
        for key, value in reward.items():
            totals[key] = totals.get(key, 0) + value

    def finish(self, *, result: str, termination_reason: str) -> dict[str, Any]:
        if self._finished:
            raise RuntimeError("episode is already finished")
        self._document["result"] = result
        self._document["termination_reason"] = termination_reason
        validated = validate_replay(self._document)
        self._finished = True
        return validated

    def document(self) -> dict[str, Any]:
        """Return the current temporary record without ending the episode."""
        draft = copy.deepcopy(self._document)
        draft["result"] = "recording"
        draft["termination_reason"] = "not_terminated"
        return validate_replay(draft)


class TemporaryEpisodeStore:
    """In-memory records whose ownership remains bound to one socket session."""

    def __init__(self) -> None:
        self._episodes: dict[str, dict[str, Any]] = {}

    def put(self, replay: Mapping[str, Any]) -> dict[str, Any]:
        validated = validate_replay(replay)
        existing = self._episodes.get(validated["episode_id"])
        if existing is not None and existing != validated:
            raise LibraryError(
                "TEMPORARY_EPISODE_CONFLICT",
                "temporary episode id already has different content",
                status=409,
            )
        self._episodes[validated["episode_id"]] = validated
        return copy.deepcopy(validated)

    def get(self, episode_id: str, *, session_id: str) -> dict[str, Any]:
        replay = self._episodes.get(episode_id)
        if replay is None or replay["ownership"]["temporary_session_id"] != session_id:
            raise EpisodeNotFound()
        return copy.deepcopy(replay)

    def discard_session(self, session_id: str) -> None:
        self._episodes = {
            episode_id: replay
            for episode_id, replay in self._episodes.items()
            if replay["ownership"]["temporary_session_id"] != session_id
        }
