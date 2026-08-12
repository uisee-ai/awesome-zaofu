"""Durable Studio state and the one-at-a-time inference execution boundary."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import contextmanager
from copy import deepcopy
import fcntl
import json
import os
from pathlib import Path
import threading
import time
from typing import Any
from uuid import uuid4


class PersistentStudioState:
    """A small, atomically-written state store suitable for the local Studio runtime.

    The on-disk record is deliberately a single JSON document: scene records and run
    results cross the same process-restart boundary as queued work, and `os.replace`
    prevents a partially-written document from becoming the next startup's state.
    """

    _LEASE_SECONDS = 360

    def __init__(self, path: Path, *, lease_seconds: float | None = None) -> None:
        self.path = path
        self._lock_path = path.with_name(f".{path.name}.lock")
        self._lock = threading.RLock()
        self._lease_seconds = lease_seconds if lease_seconds is not None else self._LEASE_SECONDS
        if self._lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        self._data = self._load()

    @property
    def lease_seconds(self) -> float:
        return self._lease_seconds

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {
                "version": 1,
                "assets": {},
                "scenes": {},
                "runs": {},
                "nextQueueSequence": 1,
                "activeLease": None,
            }
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise RuntimeError(f"Studio state cannot be loaded from {self.path}") from error
        if not isinstance(loaded, dict):
            raise RuntimeError("Studio state must be a JSON object")
        loaded.setdefault("version", 1)
        for key in ("assets", "scenes", "runs"):
            if not isinstance(loaded.get(key), dict):
                raise RuntimeError(f"Studio state field {key} must be an object")
        loaded.setdefault("nextQueueSequence", 1)
        loaded.setdefault("activeLease", None)
        return loaded

    @contextmanager
    def _transaction(self) -> Any:
        """Serialize a read-modify-write cycle across all state instances."""
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock_path.open("a+", encoding="utf-8") as lock_file:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                self._data = self._load()
                try:
                    yield
                finally:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _persist_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.{uuid4().hex}.tmp")
        encoded = json.dumps(self._data, sort_keys=True, separators=(",", ":"))
        try:
            temporary.write_text(encoded, encoding="utf-8")
            os.replace(temporary, self.path)
        finally:
            if temporary.exists():
                temporary.unlink(missing_ok=True)

    @staticmethod
    def _copy(value: Any) -> Any:
        return deepcopy(value)

    def save_asset(self, asset: Mapping[str, Any]) -> dict[str, Any]:
        asset_id = asset.get("assetId")
        if not isinstance(asset_id, str):
            raise ValueError("assetId is required")
        with self._transaction():
            self._data["assets"][asset_id] = self._copy(dict(asset))
            self._persist_locked()
            return self._copy(self._data["assets"][asset_id])

    def get_asset(self, asset_id: str) -> dict[str, Any] | None:
        with self._transaction():
            asset = self._data["assets"].get(asset_id)
            return self._copy(asset) if asset is not None else None

    def save_scene(self, scene: Mapping[str, Any]) -> dict[str, Any]:
        scene_id = scene.get("sceneId")
        if not isinstance(scene_id, str):
            raise ValueError("sceneId is required")
        with self._transaction():
            self._data["scenes"][scene_id] = self._copy(dict(scene))
            self._persist_locked()
            return self._copy(self._data["scenes"][scene_id])

    def get_scene(self, scene_id: str) -> dict[str, Any] | None:
        with self._transaction():
            scene = self._data["scenes"].get(scene_id)
            return self._copy(scene) if scene is not None else None

    def list_scenes(self) -> list[dict[str, Any]]:
        with self._transaction():
            return [self._copy(scene) for scene in self._data["scenes"].values()]

    def save_run(self, run: Mapping[str, Any]) -> dict[str, Any]:
        run_id = run.get("runId")
        if not isinstance(run_id, str):
            raise ValueError("runId is required")
        with self._transaction():
            saved = self._copy(dict(run))
            if not isinstance(saved.get("queueSequence"), int):
                saved["queueSequence"] = self._data["nextQueueSequence"]
                self._data["nextQueueSequence"] += 1
            self._data["runs"][run_id] = saved
            self._persist_locked()
            return self._copy(saved)

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._transaction():
            run = self._data["runs"].get(run_id)
            return self._copy(run) if run is not None else None

    def list_runs(self, *, scene_id: str | None = None) -> list[dict[str, Any]]:
        with self._transaction():
            runs = [
                self._copy(run)
                for run in self._data["runs"].values()
                if scene_id is None or run.get("sceneId") == scene_id
            ]
            runs.sort(key=lambda run: int(run.get("queueSequence", 0)), reverse=True)
            return runs

    def _recover_expired_lease_locked(self) -> bool:
        lease = self._data.get("activeLease")
        if not isinstance(lease, Mapping):
            recovered = False
            for run in self._data["runs"].values():
                if run.get("status") == "running":
                    run["status"] = "queued"
                    recovered = True
            return recovered
        try:
            expired = float(lease.get("expiresAt", 0)) <= time.time()
        except (TypeError, ValueError):
            expired = True
        if not expired:
            return False
        run_id = lease.get("runId")
        run = self._data["runs"].get(run_id) if isinstance(run_id, str) else None
        if isinstance(run, dict) and run.get("status") == "running":
            run["status"] = "queued"
        self._data["activeLease"] = None
        return True

    def claim_next_run(self) -> dict[str, Any] | None:
        """Atomically lease the oldest queued run for the one global executor."""
        with self._transaction():
            recovered = self._recover_expired_lease_locked()
            if self._data.get("activeLease") is not None:
                if recovered:
                    self._persist_locked()
                return None
            queued = [run for run in self._data["runs"].values() if run.get("status") == "queued"]
            if not queued:
                if recovered:
                    self._persist_locked()
                return None
            queued.sort(key=lambda run: int(run.get("queueSequence", 0)))
            run = queued[0]
            run["status"] = "running"
            run["attempts"] = int(run.get("attempts", 0)) + 1
            lease_id = uuid4().hex
            self._data["activeLease"] = {
                "runId": run["runId"],
                "leaseId": lease_id,
                "expiresAt": time.time() + self._lease_seconds,
            }
            self._persist_locked()
            claimed = self._copy(run)
            claimed["leaseId"] = lease_id
            return claimed

    def renew_lease(self, run_id: str, lease_id: str) -> bool:
        with self._transaction():
            lease = self._data.get("activeLease")
            if not isinstance(lease, Mapping) or lease.get("runId") != run_id or lease.get("leaseId") != lease_id:
                return False
            lease["expiresAt"] = time.time() + self._lease_seconds
            self._persist_locked()
            return True

    def complete_run(self, run_id: str, result: Mapping[str, Any], lease_id: str) -> dict[str, Any] | None:
        with self._transaction():
            run = self._data["runs"].get(run_id)
            lease = self._data.get("activeLease")
            if (
                run is None
                or not isinstance(lease, Mapping)
                or lease.get("runId") != run_id
                or lease.get("leaseId") != lease_id
            ):
                return None
            run.update({"status": "completed", "result": self._copy(dict(result))})
            run.pop("error", None)
            self._data["activeLease"] = None
            self._persist_locked()
            return self._copy(run)

    def fail_run(self, run_id: str, error: Mapping[str, Any], lease_id: str) -> dict[str, Any] | None:
        with self._transaction():
            run = self._data["runs"].get(run_id)
            lease = self._data.get("activeLease")
            if (
                run is None
                or not isinstance(lease, Mapping)
                or lease.get("runId") != run_id
                or lease.get("leaseId") != lease_id
            ):
                return None
            run.update({"status": "failed", "error": self._copy(dict(error))})
            self._data["activeLease"] = None
            self._persist_locked()
            return self._copy(run)

    def cancel_run(self, run_id: str) -> bool:
        with self._transaction():
            run = self._data["runs"].get(run_id)
            if run is None or run.get("status") != "queued":
                return False
            run["status"] = "cancelled"
            self._persist_locked()
            return True

    def recoverable_run_ids(self) -> list[str]:
        """Return durable queue items in submission order, recovering interrupted work."""
        with self._transaction():
            recovered = self._recover_expired_lease_locked()
            pending = [run for run in self._data["runs"].values() if run.get("status") == "queued"]
            if recovered:
                self._persist_locked()
            pending.sort(key=lambda run: int(run.get("queueSequence", 0)))
            return [str(run["runId"]) for run in pending]

    def is_idle(self) -> bool:
        with self._transaction():
            return not any(run.get("status") in {"queued", "running"} for run in self._data["runs"].values())


class SingleConcurrencyInferenceQueue:
    """A process-global FIFO worker backed by :class:`PersistentStudioState`."""

    def __init__(
        self,
        state: PersistentStudioState,
        execute: Callable[[dict[str, Any]], Mapping[str, Any]],
    ) -> None:
        self._state = state
        self._execute = execute
        self._condition = threading.Condition()
        self._active = False
        self._stopped = False
        self._worker = threading.Thread(target=self._work, name="studio-inference-queue", daemon=True)
        self._worker.start()

    @property
    def is_alive(self) -> bool:
        return self._worker.is_alive() and not self._stopped

    def enqueue(self, run_id: str, request: Mapping[str, Any], scene_id: str | None = None) -> dict[str, Any]:
        run = self._state.save_run(
            {
                "runId": run_id,
                "sceneId": scene_id,
                "status": "queued",
                "attempts": 0,
                "request": PersistentStudioState._copy(dict(request)),
            }
        )
        with self._condition:
            self._condition.notify_all()
        return run

    def cancel(self, run_id: str) -> bool:
        cancelled = self._state.cancel_run(run_id)
        if cancelled:
            with self._condition:
                self._condition.notify_all()
        return cancelled

    def wait_for_idle(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        with self._condition:
            while self._active or not self._state.is_idle():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(remaining)
            return True

    def close(self) -> None:
        with self._condition:
            self._stopped = True
            self._condition.notify_all()
        self._worker.join(timeout=1)

    def _work(self) -> None:
        while True:
            with self._condition:
                if self._stopped:
                    return
            run = self._state.claim_next_run()
            if run is None:
                with self._condition:
                    self._condition.wait(timeout=0.05)
                continue
            with self._condition:
                self._active = True
            run_id = str(run["runId"])
            lease_id = str(run["leaseId"])
            renewal_stop = threading.Event()
            renewer = threading.Thread(
                target=self._renew_until_stopped,
                args=(run_id, lease_id, renewal_stop),
                name="studio-inference-lease-renewer",
                daemon=True,
            )
            renewer.start()
            try:
                self._state.complete_run(run_id, self._execute(run), lease_id)
            except Exception as error:  # The next queued run must always receive the released lock.
                status_code = getattr(error, "status_code", None)
                self._state.fail_run(
                    run_id,
                    {
                        "message": str(getattr(error, "detail", error)),
                        "statusCode": status_code if isinstance(status_code, int) else 500,
                        "retryable": False,
                    },
                    lease_id,
                )
            finally:
                renewal_stop.set()
                renewer.join(timeout=max(self._state.lease_seconds, 0.1))
                with self._condition:
                    self._active = False
                    self._condition.notify_all()

    def _renew_until_stopped(self, run_id: str, lease_id: str, stop: threading.Event) -> None:
        interval = max(self._state.lease_seconds / 3, 0.01)
        while not stop.wait(interval):
            if not self._state.renew_lease(run_id, lease_id):
                return
