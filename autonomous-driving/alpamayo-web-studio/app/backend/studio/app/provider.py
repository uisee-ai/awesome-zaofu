"""Demo-aware Alpamayo provider adapter with protected raw-output sidecars."""

from __future__ import annotations

from base64 import b64encode
from collections.abc import Callable, Mapping
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fastapi import HTTPException
from pydantic import ValidationError

from studio.app.contracts import ProviderInferencePayload


_DEMO_INSTRUCTIONS = {
    "scene-workbench": "Analyze the complete driving scene and produce the safest near-term action.",
    "navigation-lab": "Evaluate the requested navigation instruction and explain how it changes the trajectory.",
    "camera-ablation": "Analyze the scene with the declared camera subset and identify coverage risks.",
    "scene-vqa": "Answer the supplied visual driving question using only visible evidence.",
    "auto-label-studio": "Generate concise scene risk, participant, lane, and action labels for human review.",
    "regression-judge": "Assess the scene as a regression case and identify safety-relevant output differences.",
}


class AlpamayoProvider:
    def __init__(self, *, image_loader: Callable[[], bytes], artifact_dir: Path) -> None:
        self._image_loader = image_loader
        self._artifact_dir = artifact_dir

    def invoke(
        self,
        scene: Mapping[str, Any],
        *,
        demo_id: str,
        parameters: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if demo_id not in _DEMO_INSTRUCTIONS:
            raise HTTPException(status_code=422, detail="Unsupported inference demo")

        mode = os.environ.get("ALPAMAYO_STUDIO_PROVIDER_MODE", "litellm").strip().lower()
        if mode == "mock":
            provider_response = {
                "model": "alpamayo-studio-deterministic-mock",
                "choices": [{"message": {"content": json.dumps(_mock_payload(demo_id, parameters or {}))}}],
            }
            return self._validated_result(provider_response, provider="mock", demo_id=demo_id)
        if mode != "litellm":
            raise HTTPException(status_code=503, detail="Unsupported inference provider mode")

        base_url = os.environ.get("LITELLM_BASE_URL", "").rstrip("/")
        api_key = os.environ.get("LITELLM_API_KEY", "")
        model_name = os.environ.get("LITELLM_MODEL_NAME", "")
        if not base_url or not api_key or not model_name:
            raise HTTPException(status_code=503, detail="Inference provider is not configured")

        request_body = json.dumps(
            {
                "model": model_name,
                "messages": self.build_messages(scene, demo_id=demo_id, parameters=parameters or {}),
                "max_tokens": 2_048,
                "temperature": 0.2,
                "response_format": {"type": "json_object"},
            },
            separators=(",", ":"),
        ).encode("utf-8")
        request = Request(
            f"{base_url}/v1/chat/completions",
            data=request_body,
            headers={"content-type": "application/json", "Authorization": f"Bearer {api_key}"},
            method="POST",
        )

        for attempt in range(2):
            try:
                with urlopen(request, timeout=300) as response:
                    provider_response = json.loads(response.read().decode("utf-8"))
            except (HTTPError, URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError):
                raise HTTPException(status_code=502, detail="Inference provider request failed") from None

            try:
                return self._validated_result(provider_response, provider="litellm", demo_id=demo_id)
            except (TypeError, ValueError, ValidationError):
                if attempt == 1:
                    raise HTTPException(status_code=502, detail="Inference provider returned an invalid result contract") from None

        raise AssertionError("unreachable")

    def build_messages(
        self,
        scene: Mapping[str, Any],
        *,
        demo_id: str,
        parameters: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        cameras = scene.get("cameras")
        if not isinstance(cameras, list) or not cameras:
            raise HTTPException(status_code=422, detail="Inference scene must contain camera frames")
        first_camera = cameras[0]
        frames = first_camera.get("frames") if isinstance(first_camera, Mapping) else None
        first_frame = frames[0] if isinstance(frames, list) and frames else None
        if not isinstance(first_frame, Mapping) or not isinstance(first_frame.get("assetRef"), str):
            raise HTTPException(status_code=422, detail="Inference scene must contain an authorized camera asset")

        image = self._image_loader()
        prompt = {
            "demoId": demo_id,
            "task": _DEMO_INSTRUCTIONS[demo_id],
            "navigationInstruction": scene.get("navigationInstruction", ""),
            "cameraIds": [camera.get("cameraId") for camera in cameras if isinstance(camera, Mapping)],
            "parameters": dict(parameters),
            "outputContract": {
                "vqaAnswer": "non-empty string",
                "chainOfCausation": "non-empty string",
                "metaAction": "non-empty string",
                "trajectory": "exactly 64 objects: timeSeconds 0.1..6.4, position[3], rotation[3][3]",
                "labels": "string array",
                "warnings": "string array",
            },
        }
        return [
            {
                "role": "system",
                "content": "You are an autonomous-driving research assistant. Return one JSON object only.",
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": json.dumps(prompt, separators=(",", ":"))},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64encode(image).decode('ascii')}"},
                    },
                ],
            },
        ]

    def _validated_result(self, provider_response: Any, *, provider: str, demo_id: str) -> dict[str, Any]:
        content = _message_content(provider_response)
        payload = ProviderInferencePayload.model_validate(_json_object(content))
        encoded_response = json.dumps(provider_response, sort_keys=True, separators=(",", ":")).encode("utf-8")
        digest = sha256(encoded_response).hexdigest()
        raw_output_ref = self._persist_raw_output(digest, provider_response)
        return {
            "provider": provider,
            "modelName": str(provider_response.get("model", "unknown")),
            "responseSha256": digest,
            "rawOutputRef": raw_output_ref,
            "demoId": demo_id,
            "trajectoryHorizonSeconds": 6.4,
            **payload.model_dump(),
        }

    def _persist_raw_output(self, digest: str, provider_response: Mapping[str, Any]) -> str:
        self._artifact_dir.mkdir(parents=True, exist_ok=True)
        target = self._artifact_dir / f"{digest}.json"
        temporary = self._artifact_dir / f".{digest}.{os.getpid()}.tmp"
        try:
            temporary.write_text(
                json.dumps(provider_response, sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
            os.chmod(temporary, 0o600)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        return f"provider-responses/{digest}.json"


def _message_content(provider_response: Any) -> str:
    if not isinstance(provider_response, Mapping):
        raise TypeError("provider response must be an object")
    choices = provider_response.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], Mapping):
        raise ValueError("provider response must contain choices")
    message = choices[0].get("message")
    if not isinstance(message, Mapping) or not isinstance(message.get("content"), str):
        raise ValueError("provider response must contain message content")
    content = message["content"].strip()
    if not content:
        raise ValueError("provider response content is empty")
    return content


def _json_object(content: str) -> Mapping[str, Any]:
    normalized = content.strip()
    if normalized.startswith("```"):
        normalized = normalized.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    start = normalized.find("{")
    end = normalized.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("provider content does not contain a JSON object")
    parsed = json.loads(normalized[start : end + 1])
    if not isinstance(parsed, Mapping):
        raise ValueError("provider content must decode to an object")
    return parsed


def _mock_payload(demo_id: str, parameters: Mapping[str, Any]) -> dict[str, Any]:
    lateral_offsets = {
        "scene-workbench": 0.0,
        "navigation-lab": 0.35,
        "camera-ablation": -0.25,
        "scene-vqa": 0.05,
        "auto-label-studio": 0.1,
        "regression-judge": -0.1,
    }
    offset = lateral_offsets[demo_id]
    trajectory = [
        {
            "timeSeconds": round(index * 0.1, 1),
            "position": [round(index * 0.82, 3), round(offset + 0.0025 * index * index, 3), 0.0],
            "rotation": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
        }
        for index in range(1, 65)
    ]
    question = str(parameters.get("question", "What is the safest near-term action?"))
    return {
        "vqaAnswer": f"{question} Maintain lane position and monitor the vehicle ahead.",
        "chainOfCausation": "The lane remains open, traffic is visible ahead, and no immediate obstacle crosses the ego path.",
        "metaAction": "MAINTAIN_LANE_AND_PREPARE_TO_SLOW",
        "trajectory": trajectory,
        "labels": ["drivable-lane", "lead-vehicle", "moderate-risk", demo_id],
        "warnings": ["Reduced camera coverage"] if demo_id == "camera-ablation" else [],
    }
