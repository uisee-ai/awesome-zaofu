"""Public FastAPI boundary for the local Alpamayo Studio runtime."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import asynccontextmanager
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from studio.app.contracts import CreateSceneRequest, DemoRunRequest, ReviewRunRequest
from studio.app.persistence import PersistentStudioState, SingleConcurrencyInferenceQueue
from studio.app.provider import AlpamayoProvider
from studio.app.six_demo_service import SixDemoService
from studio.fixtures.golden_scene import (
    EXPECTED_ASSET_REFS,
    GoldenSceneProvenanceError,
    validate_golden_scene_provenance,
)



@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    inference_queue.close()


app = FastAPI(title="Alpamayo Studio API", version="0.3.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.environ.get(
            "ALPAMAYO_STUDIO_WEB_ORIGINS",
            "http://localhost:3000,http://127.0.0.1:3000",
        ).split(",")
        if origin.strip()
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["content-type"],
)

_STATE_PATH = Path(os.environ.get("ALPAMAYO_STUDIO_STATE_PATH", "data/studio-state.json"))
_APP_ROOT = Path(os.environ.get("ALPAMAYO_STUDIO_APP_ROOT", Path(__file__).resolve().parents[3]))
_ASSET_DIR = Path(os.environ.get("ALPAMAYO_STUDIO_ASSET_DIR", _STATE_PATH.parent / "assets"))
_PROVIDER_ARTIFACT_DIR = Path(
    os.environ.get("ALPAMAYO_STUDIO_PROVIDER_ARTIFACT_DIR", _STATE_PATH.parent / "provider-responses")
)
_GOLDEN_SCENE_MANIFEST = _APP_ROOT / "fixtures/golden-scene/provenance.json"
_GOLDEN_ROAD_IMAGE = _APP_ROOT / "e2e/studio/fixtures/highway.png"
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_MAX_UPLOAD_BYTES = 10 * 1024 * 1024
_SENSITIVE_KEY_PARTS = ("authorization", "secret", "password", "token", "api_key")
_GOLDEN_ROAD_VISUAL = {
    "assetRef": "e2e/studio/fixtures/highway.png",
    "contentType": "image/png",
    "sourceUrl": "https://commons.wikimedia.org/wiki/File:Road_(24769469397).png",
    "license": "CC0-1.0",
}
_DEMO_SERVICE_IDS = {
    "workbench": "scene-workbench",
    "navigation": "navigation-lab",
    "ablation": "camera-ablation",
    "vqa": "scene-vqa",
    "auto-label": "auto-label-studio",
    "regression-judge": "regression-judge",
}

studio_state = PersistentStudioState(_STATE_PATH)


def public_value(value: Any, key: str = "") -> Any:
    """Return a response-safe projection without credentials or embedded image bytes."""
    normalized_key = key.lower()
    if any(part in normalized_key for part in _SENSITIVE_KEY_PARTS):
        return "[REDACTED]"
    if "base64" in normalized_key and isinstance(value, str):
        return "[REDACTED_BASE64]"
    if isinstance(value, Mapping):
        return {str(child_key): public_value(child_value, str(child_key)) for child_key, child_value in value.items()}
    if isinstance(value, list):
        return [public_value(item, key) for item in value]
    return value


def _authorized_golden_road_image() -> bytes:
    try:
        manifest = json.loads(_GOLDEN_SCENE_MANIFEST.read_text(encoding="utf-8"))
        if not isinstance(manifest, Mapping):
            raise ValueError("golden scene manifest must be an object")
        validate_golden_scene_provenance(manifest)
        image = _GOLDEN_ROAD_IMAGE.read_bytes()
        if not image.startswith(_PNG_SIGNATURE):
            raise ValueError("controlled golden road image must be PNG")
        provenance = manifest.get("provenance")
        road_visual = provenance.get("roadVisual") if isinstance(provenance, Mapping) else None
        if not isinstance(road_visual, Mapping):
            raise ValueError("golden scene manifest must bind a road visual")
        if any(road_visual.get(key) != value for key, value in _GOLDEN_ROAD_VISUAL.items()):
            raise ValueError("golden scene road visual provenance is not approved")
        if road_visual.get("sha256") != sha256(image).hexdigest():
            raise ValueError("golden scene road visual digest does not match the packaged asset")
        return image
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError, GoldenSceneProvenanceError):
        raise HTTPException(status_code=500, detail="Golden scene assets are unavailable") from None


def _controlled_visual_input() -> dict[str, Any]:
    try:
        manifest = json.loads(_GOLDEN_SCENE_MANIFEST.read_text(encoding="utf-8"))
        if not isinstance(manifest, Mapping):
            raise ValueError("golden scene manifest must be an object")
        validate_golden_scene_provenance(manifest)
        source_scene = manifest.get("scene")
        if not isinstance(source_scene, Mapping):
            raise ValueError("golden scene manifest must contain a scene")
        cameras = source_scene.get("cameras")
        if not isinstance(cameras, list):
            raise ValueError("golden scene must contain cameras")
        asset_refs = [
            frame.get("assetRef")
            for camera in cameras
            if isinstance(camera, Mapping) and isinstance(camera.get("frames"), list)
            for frame in camera["frames"]
            if isinstance(frame, Mapping)
        ]
        if len(asset_refs) != len(EXPECTED_ASSET_REFS) or set(asset_refs) != EXPECTED_ASSET_REFS:
            raise ValueError("golden scene must contain every approved asset")
        return {
            "assetRefs": sorted(asset_refs),
            "cameras": cameras,
            "navigationInstruction": str(source_scene.get("navigationInstruction", "")),
        }
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError, GoldenSceneProvenanceError):
        raise HTTPException(status_code=500, detail="Golden scene assets are unavailable") from None


provider = AlpamayoProvider(image_loader=_authorized_golden_road_image, artifact_dir=_PROVIDER_ARTIFACT_DIR)


def build_inference_messages(
    scene: Mapping[str, Any],
    *,
    demo_id: str = "scene-workbench",
    parameters: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    return provider.build_messages(scene, demo_id=demo_id, parameters=parameters or {})


def invoke_inference(
    scene: Mapping[str, Any],
    *,
    demo_id: str = "scene-workbench",
    parameters: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return provider.invoke(scene, demo_id=demo_id, parameters=parameters or {})


def _execute_dispatched_run(run: dict[str, Any]) -> dict[str, Any]:
    request = run.get("request")
    if not isinstance(request, Mapping):
        raise HTTPException(status_code=422, detail="Persisted inference request is invalid")
    run_type = request.get("runType")
    if run_type == "six-demo":
        scene_version = request.get("sceneVersion")
        demo_id = request.get("demoId")
        parameters = request.get("parameters")
        if not isinstance(scene_version, Mapping) or not isinstance(demo_id, str):
            raise HTTPException(status_code=422, detail="Persisted six-demo request is invalid")
        return invoke_inference(
            scene_version,
            demo_id=demo_id,
            parameters=parameters if isinstance(parameters, Mapping) else {},
        )
    if run_type == "generic":
        payload = request.get("payload")
        if not isinstance(payload, Mapping):
            raise HTTPException(status_code=422, detail="Persisted generic request is invalid")
        scene = payload.get("scene")
        return invoke_inference(scene if isinstance(scene, Mapping) else _controlled_visual_input())
    raise HTTPException(status_code=422, detail="Persisted run type is unsupported")


inference_queue = SingleConcurrencyInferenceQueue(studio_state, _execute_dispatched_run)
six_demo_service = SixDemoService(studio_state, queue=inference_queue)


def project_run(run: Mapping[str, Any]) -> dict[str, Any]:
    projected = dict(run)
    request = projected.pop("request", None)
    projected.pop("leaseId", None)
    if isinstance(request, Mapping) and request.get("runType") == "six-demo":
        scene_version = request.get("sceneVersion")
        if isinstance(scene_version, Mapping) and isinstance(scene_version.get("sceneVersionId"), str):
            projected["sceneVersionId"] = scene_version["sceneVersionId"]
        if isinstance(request.get("demoId"), str):
            projected["demoId"] = request["demoId"]
        if isinstance(request.get("parameters"), Mapping):
            projected["parameters"] = dict(request["parameters"])
    return public_value(projected)


def _provider_ready() -> bool:
    mode = os.environ.get("ALPAMAYO_STUDIO_PROVIDER_MODE", "litellm").strip().lower()
    if mode == "mock":
        return True
    return bool(
        mode == "litellm"
        and os.environ.get("LITELLM_BASE_URL")
        and os.environ.get("LITELLM_API_KEY")
        and os.environ.get("LITELLM_MODEL_NAME")
    )


@app.get("/")
def service_root() -> dict[str, Any]:
    return {
        "service": "alpamayo-studio-api",
        "version": app.version,
        "webOrigin": os.environ.get("ALPAMAYO_STUDIO_WEB_ORIGIN", "http://localhost:3000"),
    }


@app.get("/api/health")
def health() -> dict[str, Any]:
    provider_ready = _provider_ready()
    worker_ready = inference_queue.is_alive
    return {
        "status": "ready" if provider_ready and worker_ready else "degraded",
        "services": {
            "backend": "ready",
            "worker": "ready" if worker_ready else "unavailable",
            "provider": "ready" if provider_ready else "unconfigured",
        },
    }


@app.get("/api/model/status")
def model_status() -> dict[str, Any]:
    mode = os.environ.get("ALPAMAYO_STUDIO_PROVIDER_MODE", "litellm").strip().lower()
    return {
        "ready": _provider_ready(),
        "provider": "mock" if mode == "mock" else "litellm",
        "model": "alpamayo-studio-deterministic-mock" if mode == "mock" else os.environ.get("LITELLM_MODEL_NAME"),
    }


@app.get("/api/assets/golden-road")
def golden_road_asset() -> FileResponse:
    _authorized_golden_road_image()
    return FileResponse(_GOLDEN_ROAD_IMAGE, media_type="image/png", filename="golden-road.png")


@app.post("/api/assets")
async def upload_asset(file: UploadFile = File(...)) -> dict[str, Any]:
    content_type = (file.content_type or "").lower()
    suffix = Path(file.filename or "").suffix.lower()
    allowed_suffixes = {"image/jpeg": {".jpg", ".jpeg"}, "image/png": {".png"}}
    if content_type not in allowed_suffixes or suffix not in allowed_suffixes[content_type]:
        raise HTTPException(status_code=422, detail="Only matching JPEG and PNG uploads are accepted")
    content = await file.read(_MAX_UPLOAD_BYTES + 1)
    if not content or len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Image must be between 1 byte and 10 MiB")
    if content_type == "image/png" and not content.startswith(_PNG_SIGNATURE):
        raise HTTPException(status_code=422, detail="Uploaded PNG signature is invalid")
    if content_type == "image/jpeg" and not content.startswith(b"\xff\xd8"):
        raise HTTPException(status_code=422, detail="Uploaded JPEG signature is invalid")

    asset_id = f"asset-{uuid4().hex[:12]}"
    _ASSET_DIR.mkdir(parents=True, exist_ok=True)
    target = _ASSET_DIR / f"{asset_id}{suffix}"
    temporary = _ASSET_DIR / f".{asset_id}.{os.getpid()}.tmp"
    try:
        temporary.write_bytes(content)
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return studio_state.save_asset(
        {
            "assetId": asset_id,
            "name": Path(file.filename or target.name).name,
            "contentType": content_type,
            "sizeBytes": len(content),
            "sha256": sha256(content).hexdigest(),
            "contentRef": f"/api/assets/{asset_id}/content",
            "storagePath": str(target),
        }
    ) | {"storagePath": "[PROTECTED]"}


@app.get("/api/assets/{asset_id}/content")
def uploaded_asset_content(asset_id: str) -> FileResponse:
    asset = studio_state.get_asset(asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    storage_path = asset.get("storagePath")
    if not isinstance(storage_path, str):
        raise HTTPException(status_code=409, detail="Asset content is unavailable")
    path = Path(storage_path).resolve()
    if _ASSET_DIR.resolve() not in path.parents or not path.is_file():
        raise HTTPException(status_code=409, detail="Asset content is unavailable")
    return FileResponse(path, media_type=str(asset.get("contentType", "application/octet-stream")))


@app.post("/api/scenes")
def create_scene(payload: CreateSceneRequest) -> dict[str, Any]:
    scene_id = f"scene-{uuid4().hex[:12]}"
    visual_input = _controlled_visual_input()
    scene_version_id = f"scene-version-{uuid4().hex[:12]}"
    scene_version = {
        "sceneId": scene_id,
        "sceneVersionId": scene_version_id,
        "visualInput": {"assetRefs": visual_input["assetRefs"]},
        "navigationInstruction": visual_input["navigationInstruction"],
        "cameras": visual_input["cameras"],
    }
    return studio_state.save_scene(
        {
            "sceneId": scene_id,
            "sceneVersionId": scene_version_id,
            "sceneVersion": scene_version,
            "name": payload.name,
            "source": payload.source,
            "status": "ready",
            "previewUrl": "/api/assets/golden-road",
        }
    )


@app.get("/api/scenes")
def list_scenes() -> dict[str, Any]:
    return {"items": [public_value(scene) for scene in studio_state.list_scenes()]}


@app.get("/api/scenes/{scene_id}")
def get_scene(scene_id: str) -> dict[str, Any]:
    scene = studio_state.get_scene(scene_id)
    if scene is None:
        raise HTTPException(status_code=404, detail="Scene not found")
    return public_value(scene)


@app.post("/api/scenes/{scene_id}/runs")
def run_scene(scene_id: str, payload: DemoRunRequest) -> dict[str, Any]:
    scene = studio_state.get_scene(scene_id)
    if scene is None:
        raise HTTPException(status_code=404, detail="Scene not found")
    scene_version = scene.get("sceneVersion")
    if (
        not isinstance(scene_version, Mapping)
        or scene_version.get("sceneId") != scene_id
        or not isinstance(scene_version.get("sceneVersionId"), str)
    ):
        raise HTTPException(status_code=409, detail="Scene has no persisted SceneVersion")
    return six_demo_service.submit_run(
        scene_version,
        demo_id=_DEMO_SERVICE_IDS[payload.demoId],
        parameters=payload.parameters,
    )


@app.post("/api/runs")
def run_golden_scene(payload: dict[str, Any]) -> dict[str, Any]:
    run_id = f"run-{uuid4().hex[:12]}"
    return project_run(
        inference_queue.enqueue(run_id, {"runType": "generic", "payload": payload}, scene_id=None)
    )


@app.get("/api/runs")
def list_runs(scene_id: str | None = Query(default=None, alias="sceneId")) -> dict[str, Any]:
    return {"items": [project_run(run) for run in studio_state.list_runs(scene_id=scene_id)]}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    run = studio_state.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    request = run.get("request")
    if isinstance(request, Mapping) and request.get("runType") == "six-demo":
        saved = six_demo_service.get_run(run_id)
        if saved is not None:
            return public_value(saved)
    return project_run(run)


@app.post("/api/runs/{run_id}/cancel")
def cancel_run(run_id: str) -> dict[str, Any]:
    run = studio_state.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if not inference_queue.cancel(run_id):
        raise HTTPException(status_code=409, detail="Only queued runs can be cancelled")
    return project_run(studio_state.get_run(run_id) or run)


@app.post("/api/runs/{run_id}/reviews")
def review_run(run_id: str, payload: ReviewRunRequest) -> dict[str, Any]:
    run = studio_state.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    review = {"reviewId": f"review-{uuid4().hex[:12]}", **payload.model_dump()}
    reviews = run.get("reviews") if isinstance(run.get("reviews"), list) else []
    run["reviews"] = [*reviews, review]
    studio_state.save_run(run)
    return {"runId": run_id, "status": "saved", "review": review}


@app.post("/api/experiments")
def create_experiment(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "experimentId": f"experiment-{uuid4().hex[:12]}",
        "status": "created",
        "name": str(payload.get("name", "experiment")),
    }


@app.post("/api/evaluation-sets")
def create_evaluation_set(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "evaluationSetId": f"set-{uuid4().hex[:12]}",
        "status": "created",
        "name": str(payload.get("name", "evaluation set")),
    }


@app.post("/api/evaluation-runs")
def create_evaluation_run(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "evaluationRunId": f"evaluation-{uuid4().hex[:12]}",
        "status": "created",
        "name": str(payload.get("name", "evaluation run")),
    }
