from __future__ import annotations

import contextlib
import copy
import fcntl
import gzip
import hashlib
import json
import os
import threading
import uuid
import zlib
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any, BinaryIO

from .replay import (
    EpisodeNotFound,
    LibraryError,
    ReplayValidationError,
    SimulatedCrash,
    TemporaryEpisodeStore,
    canonical_replay_bytes,
    parse_replay_json,
)

DEFAULT_MAX_REPLAY_BYTES = 5_000_000
DEFAULT_MAX_EPISODES = 100
DEFAULT_MAX_TOTAL_BYTES = 100_000_000

_LOCKS_GUARD = threading.Lock()
_PROJECT_LOCKS: dict[str, threading.RLock] = {}


def _project_lock(path: Path) -> threading.RLock:
    key = str(path.resolve())
    with _LOCKS_GUARD:
        return _PROJECT_LOCKS.setdefault(key, threading.RLock())


class ProjectEpisodeLibrary:
    """Durable project-level replay storage with journaled, atomic commits."""

    def __init__(
        self,
        project_root: str | os.PathLike[str],
        *,
        max_replay_bytes: int = DEFAULT_MAX_REPLAY_BYTES,
        max_episodes: int = DEFAULT_MAX_EPISODES,
        max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
    ) -> None:
        self.project_root = Path(project_root)
        self.root = self.project_root / ".highwaypilot" / "episodes"
        self.max_replay_bytes = max_replay_bytes
        self.max_episodes = max_episodes
        self.max_total_bytes = max_total_bytes
        self._lock = _project_lock(self.root)

    @property
    def _index_path(self) -> Path:
        return self.root / "index.json"

    def _ensure_root(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    @contextlib.contextmanager
    def _mutation_transaction(self) -> Iterator[None]:
        """Serialize project mutations across threads and worker processes."""
        self._ensure_root()
        with self._lock:
            lock_stream: BinaryIO = (self.root / ".library.lock").open("a+b")
            try:
                fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX)
                yield
            finally:
                fcntl.flock(lock_stream.fileno(), fcntl.LOCK_UN)
                lock_stream.close()

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _write_json_atomic(self, path: Path, value: Mapping[str, Any]) -> None:
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        try:
            with temporary.open("xb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            self._fsync_directory(path.parent)
        finally:
            temporary.unlink(missing_ok=True)

    def _load_index(self) -> dict[str, dict[str, Any]]:
        if not self._index_path.exists():
            return {}
        try:
            value = json.loads(self._index_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise LibraryError("LIBRARY_INDEX_CORRUPT", "library index is corrupt", status=500) from error
        if not isinstance(value, dict) or any(not isinstance(item, dict) for item in value.values()):
            raise LibraryError("LIBRARY_INDEX_CORRUPT", "library index is corrupt", status=500)
        return value

    def _write_index(self, index: Mapping[str, Any]) -> None:
        self._write_json_atomic(self._index_path, index)

    def _metadata(self, replay: Mapping[str, Any], *, name: str, raw: bytes) -> dict[str, Any]:
        return {
            "episode_id": replay["episode_id"],
            "name": name,
            "file": f"{replay['episode_id']}.json",
            "sha256": hashlib.sha256(raw).hexdigest(),
            "canonical_bytes": len(raw),
            "created_at": replay["ownership"]["created_at"],
        }

    def _check_quota(self, index: Mapping[str, Mapping[str, Any]], raw_size: int) -> None:
        if raw_size > self.max_replay_bytes:
            raise LibraryError("LIBRARY_REPLAY_TOO_LARGE", "canonical replay exceeds 5,000,000 bytes", status=413)
        if len(index) >= self.max_episodes:
            raise LibraryError("LIBRARY_QUOTA_EXCEEDED", "project episode count quota exceeded", status=409)
        used = sum(int(item.get("canonical_bytes", 0)) for item in index.values())
        if used + raw_size > self.max_total_bytes:
            raise LibraryError("LIBRARY_QUOTA_EXCEEDED", "project replay byte quota exceeded", status=409)

    def save_temporary(
        self,
        temporary: TemporaryEpisodeStore,
        episode_id: str,
        *,
        session_id: str,
        name: str | None = None,
    ) -> dict[str, Any]:
        replay = temporary.get(episode_id, session_id=session_id)
        return self.save(replay, name=name)

    def save(
        self,
        replay: Mapping[str, Any],
        *,
        name: str | None = None,
        crash_after_stage: str | None = None,
    ) -> dict[str, Any]:
        raw = canonical_replay_bytes(replay)
        parsed = parse_replay_json(raw)
        episode_id = parsed["episode_id"]
        display_name = name or episode_id
        if not display_name.strip():
            raise LibraryError("LIBRARY_INVALID_NAME", "episode name must not be empty")
        self._ensure_root()

        with self._mutation_transaction():
            index = self._load_index()
            metadata = self._metadata(parsed, name=display_name, raw=raw)
            existing = index.get(episode_id)
            if existing is not None:
                if existing.get("sha256") == metadata["sha256"]:
                    return copy.deepcopy(existing)
                raise LibraryError("LIBRARY_CONFLICT", "episode id already has different content", status=409)
            self._check_quota(index, len(raw))

            target = self.root / metadata["file"]
            if target.exists():
                raise LibraryError(
                    "LIBRARY_RECOVERY_REQUIRED" if self._matches(target, metadata) else "LIBRARY_CONFLICT",
                    "unindexed target requires journal recovery" if self._matches(target, metadata) else "target contains different content",
                    status=409,
                )

            token = uuid.uuid4().hex
            temporary = self.root / f".{episode_id}.{token}.tmp"
            journal_path = self.root / f"{episode_id}.{token}.journal.json"
            journal: dict[str, Any] = {
                "version": 1,
                "stage": "prepared",
                "episode_id": episode_id,
                "temporary": temporary.name,
                "target": target.name,
                "length": len(raw),
                "sha256": metadata["sha256"],
                "metadata": metadata,
            }
            try:
                with temporary.open("xb") as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
                self._write_json_atomic(journal_path, journal)
                if crash_after_stage == "prepared":
                    raise SimulatedCrash("prepared")

                os.replace(temporary, target)
                self._fsync_directory(self.root)
                journal["stage"] = "renamed"
                self._write_json_atomic(journal_path, journal)
                if crash_after_stage == "renamed":
                    raise SimulatedCrash("renamed")

                index[episode_id] = metadata
                self._write_index(index)
                journal["stage"] = "indexed"
                self._write_json_atomic(journal_path, journal)
                if crash_after_stage == "indexed":
                    raise SimulatedCrash("indexed")

                journal_path.unlink()
                self._fsync_directory(self.root)
                return copy.deepcopy(metadata)
            except SimulatedCrash:
                raise
            except Exception:
                # A journal is recovery authority; otherwise no target was committed.
                if not journal_path.exists():
                    temporary.unlink(missing_ok=True)
                raise

    def list(self) -> list[dict[str, Any]]:
        self._ensure_root()
        with self._mutation_transaction():
            index = self._load_index()
            return [copy.deepcopy(index[key]) for key in sorted(index)]

    def get(self, episode_id: str) -> dict[str, Any]:
        self._ensure_root()
        with self._mutation_transaction():
            metadata = self._load_index().get(episode_id)
            if metadata is None:
                raise EpisodeNotFound()
            target = self.root / metadata["file"]
            if not self._matches(target, metadata):
                raise LibraryError("LIBRARY_DATA_CORRUPT", "stored replay failed its content hash", status=500)
            return parse_replay_json(target.read_bytes())

    def rename(self, episode_id: str, name: str) -> dict[str, Any]:
        if not isinstance(name, str) or not name.strip():
            raise LibraryError("LIBRARY_INVALID_NAME", "episode name must not be empty")
        self._ensure_root()
        with self._mutation_transaction():
            index = self._load_index()
            if episode_id not in index:
                raise EpisodeNotFound()
            index[episode_id]["name"] = name
            self._write_index(index)
            return copy.deepcopy(index[episode_id])

    def delete(self, episode_id: str, *, confirm: bool) -> None:
        if not confirm:
            raise LibraryError("LIBRARY_CONFIRMATION_REQUIRED", "deletion requires ordinary confirmation")
        self._ensure_root()
        with self._mutation_transaction():
            index = self._load_index()
            metadata = index.get(episode_id)
            if metadata is None:
                raise EpisodeNotFound()
            target = self.root / metadata["file"]
            target.unlink(missing_ok=True)
            del index[episode_id]
            self._write_index(index)
            self._fsync_directory(self.root)

    def export(self, episode_id: str, *, gzip_transport: bool = False) -> bytes:
        replay = self.get(episode_id)
        raw = canonical_replay_bytes(replay)
        return gzip.compress(raw, mtime=0) if gzip_transport else raw

    @contextlib.contextmanager
    def import_transaction(self) -> Iterator[None]:
        self._ensure_root()
        lock_stream: BinaryIO = (self.root / ".import.lock").open("a+b")
        try:
            try:
                fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise LibraryError(
                    "LIBRARY_IMPORT_BUSY",
                    "another import is in progress",
                    status=409,
                    retryable=True,
                ) from error
            yield
        finally:
            try:
                fcntl.flock(lock_stream.fileno(), fcntl.LOCK_UN)
            finally:
                lock_stream.close()

    def import_replay(self, payload: bytes | bytearray | memoryview) -> dict[str, Any]:
        raw_input = bytes(payload)
        with self.import_transaction():
            if len(raw_input) > self.max_replay_bytes:
                raise LibraryError("LIBRARY_REPLAY_TOO_LARGE", "compressed input exceeds 5,000,000 bytes", status=413)
            try:
                raw = self._decode_transport(raw_input)
                replay = parse_replay_json(raw)
            except LibraryError:
                raise
            except ReplayValidationError as error:
                raise LibraryError("LIBRARY_IMPORT_INVALID", str(error)) from error
            return self.save(replay)

    def _decode_transport(self, payload: bytes) -> bytes:
        if not payload.startswith(b"\x1f\x8b"):
            return payload
        remaining = payload
        output = bytearray()
        while remaining:
            if not remaining.startswith(b"\x1f\x8b"):
                raise LibraryError("LIBRARY_IMPORT_INVALID", "gzip contains trailing unparsed data")
            decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
            try:
                member_input = remaining
                while member_input:
                    capacity = self.max_replay_bytes - len(output) + 1
                    chunk = decompressor.decompress(member_input, capacity)
                    output.extend(chunk)
                    if len(output) > self.max_replay_bytes:
                        raise LibraryError("LIBRARY_REPLAY_TOO_LARGE", "decompressed replay exceeds 5,000,000 bytes", status=413)
                    member_input = decompressor.unconsumed_tail
                    if not member_input:
                        break
            except zlib.error as error:
                raise LibraryError("LIBRARY_IMPORT_INVALID", "invalid gzip transport") from error
            if not decompressor.eof:
                raise LibraryError("LIBRARY_IMPORT_INVALID", "incomplete gzip transport")
            remaining = decompressor.unused_data
        decoded = bytes(output)
        if decoded.startswith(b"\x1f\x8b"):
            raise LibraryError("LIBRARY_IMPORT_INVALID", "nested compression is not allowed")
        return decoded

    @staticmethod
    def _matches(path: Path, metadata: Mapping[str, Any]) -> bool:
        try:
            raw = path.read_bytes()
        except OSError:
            return False
        return len(raw) == metadata.get("canonical_bytes", metadata.get("length")) and hashlib.sha256(raw).hexdigest() == metadata.get("sha256")

    def _quarantine(self, path: Path) -> None:
        if path.exists():
            os.replace(path, path.with_name(f"{path.name}.quarantine-{uuid.uuid4().hex}"))
            self._fsync_directory(self.root)

    def recover(self) -> None:
        self._ensure_root()
        with self._mutation_transaction():
            for journal_path in sorted(self.root.glob("*.journal.json")):
                self._recover_journal(journal_path)

    def _recover_journal(self, journal_path: Path) -> None:
        try:
            journal = json.loads(journal_path.read_text(encoding="utf-8"))
            stage = journal["stage"]
            episode_id = journal["episode_id"]
            metadata = journal["metadata"]
            temporary = self.root / journal["temporary"]
            target = self.root / journal["target"]
        except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError):
            self._quarantine(journal_path)
            return

        index = self._load_index()
        if stage == "prepared":
            if self._matches(target, metadata):
                self._quarantine(target)
            temporary.unlink(missing_ok=True)
            journal_path.unlink(missing_ok=True)
            self._fsync_directory(self.root)
            return

        if stage in {"renamed", "indexed"}:
            if not self._matches(target, metadata):
                self._quarantine(target)
                if index.get(episode_id, {}).get("sha256") == metadata.get("sha256"):
                    del index[episode_id]
                    self._write_index(index)
                temporary.unlink(missing_ok=True)
                journal_path.unlink(missing_ok=True)
                self._fsync_directory(self.root)
                return
            existing = index.get(episode_id)
            if existing is not None and existing.get("sha256") != metadata.get("sha256"):
                self._quarantine(target)
            else:
                index[episode_id] = metadata
                self._write_index(index)
            temporary.unlink(missing_ok=True)
            journal_path.unlink(missing_ok=True)
            self._fsync_directory(self.root)
            return

        self._quarantine(journal_path)
