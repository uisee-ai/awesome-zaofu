"""FastAPI composition for the same-port local HighwayPilot service."""

from __future__ import annotations

import asyncio
import contextlib
import json
import threading
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response

from highwaypilot_lab.protocol import (
    ProtocolMessageError,
    ResumeCommit,
    ResumeOffer,
    SessionCommand,
    parse_client_message,
)
from highwaypilot_lab.config import UINT32_MAX, ConfigError, parse_config
from highwaypilot_lab.episodes import EpisodeNotFound, EpisodeRecorder, LibraryError, ProjectEpisodeLibrary
from highwaypilot_lab.strategies import (
    AUTONOMOUS_STRATEGIES,
    EvaluationCancelled,
    run_evaluation_episode,
    run_four_policy_comparison,
    run_paired_strategy_evaluation,
)
from highwaypilot_lab.security import LoopbackBoundaryMiddleware, validate_bind_address
from highwaypilot_lab.session import ResumeError, Session, SessionRegistry

from .static import StaticAssetNotFound, StaticAssetStore


class RuntimeService:
    """Own API-facing references without weakening session-scoped authority."""

    def __init__(self, project_root: str | Path) -> None:
        self.project_root = Path(project_root)
        self.registry = SessionRegistry()
        self._sessions: dict[str, Session] = {}
        self._evaluation_jobs: dict[str, dict[str, Any]] = {}
        self.library = ProjectEpisodeLibrary(self.project_root)

    @property
    def session_count(self) -> int:
        return len(self._sessions)

    def session(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    async def cleanup_expired(self) -> list[str]:
        expired = await self.registry.cleanup_expired()
        for session_id in expired:
            self._sessions.pop(session_id, None)
        return expired

    async def close_all(self) -> None:
        jobs = list(self._evaluation_jobs.values())
        for job in jobs:
            job["cancel"].set()
            task = job.get("task")
            if isinstance(task, asyncio.Task):
                task.cancel()
        for job in jobs:
            task = job.get("task")
            if isinstance(task, asyncio.Task):
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        await self.registry.close_all()
        self._sessions.clear()

    def evaluation(self, evaluation_id: str) -> dict[str, Any] | None:
        return self._evaluation_jobs.get(evaluation_id)

    @staticmethod
    def evaluation_snapshot(job: Mapping[str, Any]) -> dict[str, Any]:
        with job["lock"]:
            return {
                "evaluation_id": job["evaluation_id"],
                "status": job["status"],
                "progress": dict(job["progress"]),
                "result": job["result"],
                "error": job["error"],
            }

    def start_evaluation(
        self,
        config: Mapping[str, Any],
        *,
        seeds: list[int],
        strategy_ids: list[str],
        manual_actions: list[str] | None,
        max_steps: int,
    ) -> dict[str, Any]:
        if any(
            job["status"] in {"queued", "running", "cancelling"}
            for job in self._evaluation_jobs.values()
        ):
            raise ValueError("another strategy evaluation is already active")
        while len(self._evaluation_jobs) >= 20:
            removable = next(
                (
                    key
                    for key, job in self._evaluation_jobs.items()
                    if job["status"] in {"completed", "cancelled", "failed"}
                ),
                None,
            )
            if removable is None:
                raise ValueError("strategy evaluation capacity is exhausted")
            del self._evaluation_jobs[removable]
        evaluation_id = f"evaluation-{uuid.uuid4().hex}"
        total = len(seeds) * len(strategy_ids)
        job: dict[str, Any] = {
            "evaluation_id": evaluation_id,
            "status": "queued",
            "progress": {"completed": 0, "total": total},
            "result": None,
            "error": None,
            "lock": threading.Lock(),
            "cancel": threading.Event(),
            "config": dict(config),
            "seeds": list(seeds),
            "strategy_ids": list(strategy_ids),
            "manual_actions": None if manual_actions is None else list(manual_actions),
            "max_steps": max_steps,
        }
        self._evaluation_jobs[evaluation_id] = job

        async def execute() -> None:
            def progress(completed: int, expected: int) -> None:
                with job["lock"]:
                    job["progress"] = {"completed": completed, "total": expected}

            with job["lock"]:
                job["status"] = "running"
            try:
                result = await asyncio.to_thread(
                    run_paired_strategy_evaluation,
                    job["config"],
                    seeds=job["seeds"],
                    strategy_ids=job["strategy_ids"],
                    manual_actions=job["manual_actions"],
                    model_dir=self.project_root / "models" / "construction-dqn-v1",
                    max_steps=job["max_steps"],
                    progress=progress,
                    cancelled=job["cancel"].is_set,
                )
                with job["lock"]:
                    job["result"] = result
                    job["status"] = "completed"
            except EvaluationCancelled as error:
                with job["lock"]:
                    job["status"] = "cancelled"
                    job["error"] = str(error)
            except asyncio.CancelledError:
                with job["lock"]:
                    job["status"] = "cancelled"
                    job["error"] = "service stopped"
                raise
            except Exception as error:
                with job["lock"]:
                    job["status"] = "failed"
                    job["error"] = str(error)

        job["task"] = asyncio.create_task(execute())
        return self.evaluation_snapshot(job)

    def cancel_evaluation(self, evaluation_id: str) -> dict[str, Any] | None:
        job = self._evaluation_jobs.get(evaluation_id)
        if job is None:
            return None
        with job["lock"]:
            if job["status"] in {"queued", "running"}:
                job["cancel"].set()
                job["status"] = "cancelling"
        return self.evaluation_snapshot(job)

    def create_session(self, config: Mapping[str, Any]) -> dict[str, Any]:
        created = self.registry.create(config, model_dir=self.project_root / "models" / "construction-dqn-v1")
        session = created.session
        self._sessions[session.session_id] = session
        return {
            "protocol_version": "highwaypilot-ws/v1",
            "session_id": session.session_id,
            "resume_token": created.resume_token.reveal(),
            "connection_status": "connected",
            "session_status": session.session_status,
            "simulation_status": session.simulation_status,
            "attachment_epoch": session.attachment_epoch,
            "simulation_generation": session.simulation_generation,
            "state_seq": session.state_seq,
            "effective_config": session.effective_config,
            "config_digest": session.snapshot().get("config_digest"),
            "snapshot": session.snapshot(),
        }


def _error(code: str, message: str, status: int) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


def _library_error(error: LibraryError) -> JSONResponse:
    return JSONResponse({"error": error.as_dict()}, status_code=error.status)


def _comparison_replay(
    episode: Mapping[str, Any],
    effective_config: Mapping[str, Any],
) -> dict[str, Any]:
    initial = episode["initial_snapshot"]
    recorder = EpisodeRecorder(
        session_id=f"strategy-comparison-{uuid.uuid4().hex}",
        project_id="highwaypilot-lab-v7",
        initial_frame=initial,
        strategy=episode["strategy"],
        seed=int(episode["seed"]),
        effective_config=effective_config,
        rng_contract=initial["rng"],
        versions={
            "application": "highwaypilot-lab/v1",
            "highway_env": "1.12.1",
            "gymnasium": "1.x",
            "python": "3.11+",
            "git": "working-tree",
            "platform": "local",
        },
    )
    for item in episode["decisions"]:
        recorder.append(
            str(item["decision"]["action"]),
            item["frame"],
            item["reward"]["components"],
        )
    final_status = episode["final_snapshot"]["status"]
    result = (
        "terminated"
        if final_status["terminated"]
        else "truncated"
        if final_status["truncated"]
        else "step_limit"
    )
    return recorder.finish(result=result, termination_reason=str(episode["result"]))


def create_app(
    *,
    runtime: RuntimeService | None = None,
    static_root: str | Path | None = None,
) -> FastAPI:
    runtime = runtime or RuntimeService(Path.cwd())
    assets = StaticAssetStore(static_root) if static_root is not None else None
    app = FastAPI(title="HighwayPilot Lab", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(LoopbackBoundaryMiddleware)
    app.state.runtime = runtime

    @app.on_event("startup")
    async def start_cleanup_task() -> None:
        async def cleanup_loop() -> None:
            while True:
                await asyncio.sleep(5)
                await runtime.cleanup_expired()

        app.state.cleanup_task = asyncio.create_task(cleanup_loop())

    @app.on_event("shutdown")
    async def stop_cleanup_task() -> None:
        task = getattr(app.state, "cleanup_task", None)
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await runtime.close_all()

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "bind_host": "127.0.0.1"}

    @app.get("/api/presets/{preset_id}")
    async def preset(preset_id: str) -> Response:
        if preset_id not in {"normal-v1", "congested-v1", "aggressive-v1", "dangerous-cut-in-v1"}:
            return _error("PRESET_NOT_FOUND", "preset is unavailable", 404)
        path = runtime.project_root / "configs" / "presets" / f"{preset_id}.json"
        try:
            raw = path.read_bytes()
            json.loads(raw)
        except (OSError, UnicodeError, json.JSONDecodeError):
            return _error("PRESET_NOT_FOUND", "preset is unavailable", 404)
        return Response(raw, media_type="application/json", headers={"X-Content-Type-Options": "nosniff"})

    @app.post("/api/sessions", status_code=201)
    async def create_session(request: Request) -> Response:
        try:
            payload = await request.json()
            if not isinstance(payload, Mapping) or set(payload) != {"config"}:
                raise ValueError("request fields mismatch")
            config = payload["config"]
            if not isinstance(config, Mapping):
                raise ValueError("config must be an object")
            result = runtime.create_session(config)
        except ConfigError as error:
            return JSONResponse({"error": {"code": "INVALID_CONFIG", "message": str(error), "issues": error.issues}}, status_code=422)
        except (ValueError, TypeError, UnicodeError, json.JSONDecodeError) as error:
            return _error("INVALID_CONFIG", str(error), 422)
        return JSONResponse(result, status_code=201, headers={"Cache-Control": "no-store"})

    @app.post("/api/config/validate")
    async def validate_configuration(request: Request) -> Response:
        try:
            payload = await request.json()
            if not isinstance(payload, Mapping):
                raise ValueError("config must be an object")
            return JSONResponse({"effective_config": parse_config(payload), "valid": True})
        except ConfigError as error:
            return JSONResponse({"valid": False, "error": {"code": "INVALID_CONFIG", "message": str(error), "issues": error.issues}}, status_code=422)
        except (ValueError, TypeError, UnicodeError, json.JSONDecodeError) as error:
            return _error("INVALID_CONFIG", str(error), 422)

    @app.get("/api/episodes")
    async def list_episodes() -> Response:
        try:
            items = runtime.library.list()
        except LibraryError as error:
            return _library_error(error)
        used = sum(int(item.get("canonical_bytes", 0)) for item in items)
        return JSONResponse({"items": items, "quota": {"used_bytes": used, "max_bytes": runtime.library.max_total_bytes, "count": len(items), "max_count": runtime.library.max_episodes}})

    @app.get("/api/episodes/{episode_id}")
    async def get_episode(episode_id: str) -> Response:
        try:
            return JSONResponse(runtime.library.get(episode_id))
        except (EpisodeNotFound, LibraryError) as error:
            return _library_error(error)

    @app.post("/api/episodes")
    async def save_episode(request: Request) -> Response:
        try:
            payload = await request.json()
            if not isinstance(payload, Mapping) or set(payload) - {"replay", "name"} or "replay" not in payload:
                raise ValueError("request must contain replay and optional name")
            result = runtime.library.save(payload["replay"], name=payload.get("name"))
            return JSONResponse(result, status_code=201)
        except (LibraryError, ValueError, TypeError, KeyError) as error:
            return _library_error(error) if isinstance(error, LibraryError) else _error("LIBRARY_INVALID", str(error), 422)

    @app.post("/api/sessions/{session_id}/episodes/save")
    async def save_session_episode(session_id: str, request: Request) -> Response:
        session = runtime.session(session_id)
        if session is None:
            return _error("SESSION_NOT_FOUND", "session is unavailable", 404)
        try:
            payload = await request.json()
            if not isinstance(payload, Mapping) or set(payload) - {"name"}:
                raise ValueError("request may contain only name")
            result = runtime.library.save(session.temporary_episode(), name=payload.get("name"))
            return JSONResponse(result, status_code=201)
        except LibraryError as error:
            return _library_error(error)
        except (ValueError, TypeError) as error:
            return _error("LIBRARY_INVALID", str(error), 422)

    @app.post("/api/episodes/import")
    async def import_episode(request: Request) -> Response:
        try:
            result = runtime.library.import_replay(await request.body())
            return JSONResponse(result, status_code=201)
        except LibraryError as error:
            return _library_error(error)

    @app.get("/api/episodes/{episode_id}/export")
    async def export_episode(episode_id: str, gzip_transport: bool = False) -> Response:
        try:
            body = runtime.library.export(episode_id, gzip_transport=gzip_transport)
            media = "application/gzip" if gzip_transport else "application/json"
            return Response(body, media_type=media, headers={"Content-Disposition": f'attachment; filename="{episode_id}.json' + ('.gz"' if gzip_transport else '"')})
        except (EpisodeNotFound, LibraryError) as error:
            return _library_error(error)

    @app.patch("/api/episodes/{episode_id}")
    async def rename_episode(episode_id: str, request: Request) -> Response:
        try:
            payload = await request.json()
            result = runtime.library.rename(episode_id, payload.get("name"))
            return JSONResponse(result)
        except (EpisodeNotFound, LibraryError, ValueError, TypeError, AttributeError) as error:
            return _library_error(error) if isinstance(error, LibraryError) else _error("LIBRARY_INVALID", str(error), 422)

    @app.delete("/api/episodes/{episode_id}")
    async def delete_episode(episode_id: str, confirm: bool = False) -> Response:
        try:
            runtime.library.delete(episode_id, confirm=confirm)
            return Response(status_code=204)
        except (EpisodeNotFound, LibraryError) as error:
            return _library_error(error)

    @app.post("/api/strategy-comparisons")
    async def strategy_comparison(request: Request) -> Response:
        try:
            payload = await request.json()
            if not isinstance(payload, Mapping) or set(payload) - {"config", "manual_actions", "max_steps"} or "config" not in payload:
                raise ValueError("request must contain config and optional manual_actions/max_steps")
            actions = payload.get("manual_actions", ["IDLE"] * 500)
            if not isinstance(actions, list) or not all(isinstance(action, str) for action in actions):
                raise ValueError("manual_actions must be a string array")
            max_steps = payload.get("max_steps", 500)
            effective_config = parse_config(payload["config"])
            result = await asyncio.to_thread(
                run_four_policy_comparison,
                effective_config,
                manual_actions=actions,
                model_dir=runtime.project_root / "models" / "construction-dqn-v1",
                max_steps=max_steps,
            )
            for episode in result["episodes"]:
                episode["replay"] = _comparison_replay(episode, effective_config)
            return JSONResponse(result, status_code=200)
        except Exception as error:
            if isinstance(error, (ValueError, TypeError, KeyError)):
                return _error("COMPARISON_INVALID", str(error), 422)
            return _error("COMPARISON_FAILED", str(error), 500)

    @app.post("/api/strategy-evaluations", status_code=202)
    async def create_strategy_evaluation(request: Request) -> Response:
        try:
            payload = await request.json()
            allowed = {
                "config",
                "episodes_per_strategy",
                "seed_start",
                "strategies",
                "manual_actions",
                "max_steps",
            }
            if not isinstance(payload, Mapping) or set(payload) - allowed or "config" not in payload:
                raise ValueError("request contains unknown fields or omits config")
            effective = parse_config(payload["config"])
            count = payload.get("episodes_per_strategy", 20)
            if type(count) is not int or not 2 <= count <= 100:
                raise ValueError("episodes_per_strategy must be an integer between 2 and 100")
            seed_start = payload.get("seed_start", effective["seed"])
            if type(seed_start) is not int or not 0 <= seed_start <= UINT32_MAX:
                raise ValueError(f"seed_start must be an integer between 0 and {UINT32_MAX}")
            if seed_start + count - 1 > UINT32_MAX:
                raise ValueError("evaluation Seed range exceeds uint32")
            strategies = payload.get("strategies", list(AUTONOMOUS_STRATEGIES))
            if not isinstance(strategies, list) or not all(isinstance(item, str) for item in strategies):
                raise ValueError("strategies must be a string array")
            actions = payload.get("manual_actions")
            if actions is not None and (
                not isinstance(actions, list) or not actions or not all(isinstance(item, str) for item in actions)
            ):
                raise ValueError("manual_actions must be a non-empty string array when provided")
            max_steps = payload.get("max_steps", 500)
            if type(max_steps) is not int or max_steps <= 0:
                raise ValueError("max_steps must be a positive integer")
            snapshot = runtime.start_evaluation(
                effective,
                seeds=list(range(seed_start, seed_start + count)),
                strategy_ids=strategies,
                manual_actions=actions,
                max_steps=max_steps,
            )
            return JSONResponse(snapshot, status_code=202, headers={"Cache-Control": "no-store"})
        except ConfigError as error:
            return JSONResponse(
                {"error": {"code": "INVALID_CONFIG", "message": str(error), "issues": error.issues}},
                status_code=422,
            )
        except (ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
            return _error("EVALUATION_INVALID", str(error), 422)

    @app.get("/api/strategy-evaluations/{evaluation_id}")
    async def get_strategy_evaluation(evaluation_id: str) -> Response:
        job = runtime.evaluation(evaluation_id)
        if job is None:
            return _error("EVALUATION_NOT_FOUND", "strategy evaluation is unavailable", 404)
        return JSONResponse(runtime.evaluation_snapshot(job), headers={"Cache-Control": "no-store"})

    @app.delete("/api/strategy-evaluations/{evaluation_id}", status_code=202)
    async def cancel_strategy_evaluation(evaluation_id: str) -> Response:
        snapshot = runtime.cancel_evaluation(evaluation_id)
        if snapshot is None:
            return _error("EVALUATION_NOT_FOUND", "strategy evaluation is unavailable", 404)
        return JSONResponse(snapshot, status_code=202, headers={"Cache-Control": "no-store"})

    @app.get("/api/strategy-evaluations/{evaluation_id}/episodes/{episode_id}/replay")
    async def evaluation_episode_replay(evaluation_id: str, episode_id: str) -> Response:
        job = runtime.evaluation(evaluation_id)
        if job is None:
            return _error("EVALUATION_NOT_FOUND", "strategy evaluation is unavailable", 404)
        snapshot = runtime.evaluation_snapshot(job)
        result = snapshot.get("result")
        if snapshot["status"] != "completed" or not isinstance(result, Mapping):
            return _error("EVALUATION_NOT_READY", "strategy evaluation is not complete", 409)
        summary = next(
            (item for item in result["episodes"] if item["episode_id"] == episode_id),
            None,
        )
        if summary is None:
            return _error("EVALUATION_EPISODE_NOT_FOUND", "evaluation Episode is unavailable", 404)
        try:
            effective = dict(job["config"])
            effective["seed"] = summary["seed"]
            effective = parse_config(effective)
            episode = await asyncio.to_thread(
                run_evaluation_episode,
                effective,
                summary["strategy"]["id"],
                manual_actions=job["manual_actions"],
                model_dir=runtime.project_root / "models" / "construction-dqn-v1",
                max_steps=job["max_steps"],
            )
            if episode["result"] != summary["result"] or episode["config_digest"] != summary["config_digest"]:
                return _error("EVALUATION_REPLAY_DRIFT", "regenerated Episode differs from evaluation", 409)
            return JSONResponse(_comparison_replay(episode, effective), headers={"Cache-Control": "no-store"})
        except Exception as error:
            if isinstance(error, (ValueError, TypeError, KeyError)):
                return _error("EVALUATION_REPLAY_FAILED", str(error), 422)
            return _error("EVALUATION_REPLAY_FAILED", "failed to regenerate evaluation Episode", 500)

    @app.websocket("/ws/sessions/{session_id}")
    async def session_socket(websocket: WebSocket, session_id: str) -> None:
        session = runtime.session(session_id)
        if session is None:
            await websocket.close(code=4404, reason="session unavailable")
            return
        await websocket.accept()
        socket_id = f"socket-{uuid.uuid4().hex}"
        send_lock = asyncio.Lock()

        async def flush() -> None:
            async with send_lock:
                for event in session.drain_outbox():
                    await websocket.send_json(event)

        async def playback_pump() -> None:
            while True:
                await asyncio.sleep(0.2 / session.playback_rate)
                if session.simulation_status == "playing":
                    await session.tick_playback()
                    await flush()

        session.publish_snapshot(lossy_playing=False, reason="initial")
        await flush()
        pump = asyncio.create_task(playback_pump())
        try:
            while True:
                try:
                    message = parse_client_message(await websocket.receive_json())
                except (ProtocolMessageError, ValueError, TypeError):
                    await websocket.send_json(
                        {
                            "protocol_version": "highwaypilot-ws/v1",
                            "type": "command.error",
                            "error": {"code": "INVALID_MESSAGE", "message": "message was rejected"},
                        }
                    )
                    continue
                try:
                    if isinstance(message, SessionCommand):
                        result = await runtime.registry.submit(session_id, message)
                    elif isinstance(message, ResumeOffer):
                        result = await session.resume_offer(
                            message.resume_token,
                            message.resume_attempt_id,
                            socket_id,
                        )
                    elif isinstance(message, ResumeCommit):
                        result = await session.resume_commit(
                            message.resume_attempt_id,
                            message.offer_id,
                            socket_id,
                        )
                    else:  # pragma: no cover - closed union safety
                        result = None
                except ResumeError as error:
                    async with send_lock:
                        await websocket.send_json(
                            {
                                "protocol_version": "highwaypilot-ws/v1",
                                "type": "resume.error",
                                "error": {"code": error.code, "message": "resume was rejected"},
                            }
                        )
                    continue
                if result is None:
                    await websocket.close(code=4408, reason="backpressure")
                    return
                await flush()
        except WebSocketDisconnect:
            await session.detach()
        finally:
            pump.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await pump

    if assets is not None:
        @app.get("/{asset_path:path}")
        async def static_asset(request: Request, asset_path: str) -> Response:
            try:
                content, mime_type = assets.read(asset_path, request.scope.get("raw_path", b"/"))
            except StaticAssetNotFound:
                return _error("ASSET_NOT_FOUND", "static asset is unavailable", 404)
            return Response(
                content,
                media_type=mime_type,
                # The demo server serves freshly assembled bundles during
                # development. Prevent an open tab from retaining an older
                # index, CSS, or GLB after a renderer upgrade.
                headers={
                    "X-Content-Type-Options": "nosniff",
                    "Cache-Control": "no-store",
                },
            )

    return app


def run(*, host: str = "127.0.0.1", port: int = 8000, static_root: str | Path | None = None) -> None:
    bind_host, bind_port = validate_bind_address(host, port)
    uvicorn.run(create_app(static_root=static_root), host=bind_host, port=bind_port)
