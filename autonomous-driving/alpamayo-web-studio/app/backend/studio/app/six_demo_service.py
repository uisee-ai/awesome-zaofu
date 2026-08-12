"""Durable submission and readback boundary shared by all six Studio demos.

The service deliberately knows nothing about provider endpoints or credentials.
An application supplies the executor, which may obtain its provider configuration
from the local process environment.  This boundary persists a SceneVersion
snapshot and the eventual result through the existing FIFO, leased queue.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from typing import Any
from uuid import uuid4

from studio.app.persistence import PersistentStudioState, SingleConcurrencyInferenceQueue

SIX_DEMO_IDS = frozenset(
    {
        "scene-workbench",
        "navigation-lab",
        "camera-ablation",
        "scene-vqa",
        "auto-label-studio",
        "regression-judge",
    }
)

_SENSITIVE_KEY_PARTS = ("authorization", "secret", "password", "token", "api_key", "apikey")


class _SafeExecutorFailure(Exception):
    """An execution failure safe for durable queue error records."""

    def __init__(self, status_code: Any) -> None:
        self.status_code = status_code if isinstance(status_code, int) else 500
        self.detail = "Inference execution failed"
        super().__init__(self.detail)


class SixDemoService:
    """Submit immutable scene-version runs and read their durable public records."""

    def __init__(
        self,
        state: PersistentStudioState,
        *,
        execute: Callable[[dict[str, Any]], Mapping[str, Any]] | None = None,
        queue: SingleConcurrencyInferenceQueue | None = None,
        run_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._state = state
        if queue is None and execute is None:
            raise ValueError("execute is required when no shared queue is supplied")
        self._execute = execute
        self._owns_queue = queue is None
        self._queue = queue or SingleConcurrencyInferenceQueue(state, self._execute_without_credentials)
        self._run_id_factory = run_id_factory or (lambda: f"run-{uuid4().hex[:12]}")

    def submit_run(
        self,
        scene_version: Mapping[str, Any],
        *,
        demo_id: str,
        parameters: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Persist a scene-version snapshot and enqueue it on the shared FIFO worker.

        Only a local executor is injected into this service.  Credentials and
        provider configuration are not accepted as run input, preventing them
        from becoming part of durable queue records.
        """
        if demo_id not in SIX_DEMO_IDS:
            raise ValueError(f"Unknown six-demo id: {demo_id}")
        if not isinstance(scene_version.get("sceneVersionId"), str):
            raise ValueError("sceneVersionId is required")
        if not isinstance(scene_version.get("sceneId"), str):
            raise ValueError("sceneId is required")

        snapshot = deepcopy(dict(scene_version))
        effective_parameters = deepcopy(dict(parameters or {}))
        if _contains_sensitive_key(snapshot) or _contains_sensitive_key(effective_parameters):
            raise ValueError("credential-like fields cannot be persisted in a six-demo run")

        run_id = self._run_id_factory()
        if not isinstance(run_id, str) or not run_id:
            raise ValueError("run_id_factory must return a non-empty string")
        run = self._queue.enqueue(
            run_id,
            {
                "runType": "six-demo",
                "demoId": demo_id,
                "sceneVersion": snapshot,
                "parameters": effective_parameters,
            },
            scene_id=snapshot["sceneId"],
        )
        run["sceneVersionId"] = snapshot["sceneVersionId"]
        return _project_run(run)

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        """Return the saved run and result without exposing its execution input."""
        run = self._state.get_run(run_id)
        if run is None:
            return None
        return _project_run(run)

    def wait_for_idle(self, timeout: float) -> bool:
        return self._queue.wait_for_idle(timeout)

    def close(self) -> None:
        if self._owns_queue:
            self._queue.close()

    def _execute_without_credentials(self, run: dict[str, Any]) -> Mapping[str, Any]:
        """Prevent provider result metadata from crossing the durable queue boundary."""
        try:
            if self._execute is None:
                raise RuntimeError("shared queue owns execution")
            return _remove_sensitive_fields(self._execute(run))
        except Exception as error:
            raise _SafeExecutorFailure(getattr(error, "status_code", None)) from None


def _contains_sensitive_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(
            any(part in str(key).lower() for part in _SENSITIVE_KEY_PARTS) or _contains_sensitive_key(child)
            for key, child in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_sensitive_key(item) for item in value)
    return False


def _remove_sensitive_fields(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _remove_sensitive_fields(child)
            for key, child in value.items()
            if not any(part in str(key).lower() for part in _SENSITIVE_KEY_PARTS)
        }
    if isinstance(value, list):
        return [_remove_sensitive_fields(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_remove_sensitive_fields(item) for item in value)
    return deepcopy(value)


def _project_run(run: Mapping[str, Any]) -> dict[str, Any]:
    projected = deepcopy(dict(run))
    request = projected.pop("request", None)
    projected.pop("leaseId", None)
    if isinstance(request, Mapping) and request.get("runType") == "six-demo":
        scene_version = request.get("sceneVersion")
        if isinstance(scene_version, Mapping) and isinstance(scene_version.get("sceneVersionId"), str):
            projected["sceneVersionId"] = scene_version["sceneVersionId"]
        if isinstance(request.get("demoId"), str):
            projected["demoId"] = request["demoId"]
        parameters = request.get("parameters")
        if isinstance(parameters, Mapping):
            projected["parameters"] = deepcopy(dict(parameters))
    return projected
