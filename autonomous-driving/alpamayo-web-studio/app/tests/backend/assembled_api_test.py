"""Behavioral proof for the assembled FastAPI, queue, and six-demo boundary."""

from __future__ import annotations

import importlib
import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient

APP_ROOT = Path(__file__).resolve().parents[2]
APP_BACKEND = APP_ROOT / "backend"
sys.path.insert(0, str(APP_BACKEND))


def test_one_scene_runs_all_six_demos_through_one_dispatcher(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ALPAMAYO_STUDIO_PROVIDER_MODE", "mock")
    monkeypatch.setenv("ALPAMAYO_STUDIO_STATE_PATH", str(tmp_path / "studio-state.json"))
    monkeypatch.setenv("ALPAMAYO_STUDIO_PROVIDER_ARTIFACT_DIR", str(tmp_path / "provider-responses"))
    monkeypatch.setenv("ALPAMAYO_STUDIO_APP_ROOT", str(APP_ROOT))

    sys.modules.pop("studio.app.main", None)
    main = importlib.import_module("studio.app.main")
    demos = ["workbench", "navigation", "ablation", "vqa", "auto-label", "regression-judge"]
    try:
        with TestClient(main.app) as client:
            health = client.get("/api/health")
            assert health.status_code == 200
            assert health.json()["status"] == "ready"

            scene_response = client.post("/api/scenes", json={"name": "E2E road", "source": "golden"})
            assert scene_response.status_code == 200
            scene = scene_response.json()
            assert scene["previewUrl"] == "/api/assets/golden-road"
            assert client.get(scene["previewUrl"]).content.startswith(b"\x89PNG")

            completed = []
            for demo in demos:
                response = client.post(
                    f"/api/scenes/{scene['sceneId']}/runs",
                    json={"demoId": demo, "parameters": {"question": f"question-{demo}"}},
                )
                assert response.status_code == 200
                run_id = response.json()["runId"]
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    saved = client.get(f"/api/runs/{run_id}").json()
                    if saved["status"] in {"completed", "failed"}:
                        break
                    time.sleep(0.02)
                assert saved["status"] == "completed"
                assert saved["demoId"] == saved["result"]["demoId"]
                assert saved["parameters"] == {"question": f"question-{demo}"}
                assert "request" not in saved
                assert saved["result"]["demoId"] != completed[-1]["result"]["demoId"] if completed else True
                assert len(saved["result"]["trajectory"]) == 64
                assert saved["result"]["rawOutputRef"].startswith("provider-responses/")
                completed.append(saved)

            listed = client.get("/api/runs", params={"sceneId": scene["sceneId"]}).json()["items"]
            assert len(listed) == 6
            assert {run["demoId"] for run in listed} == {run["result"]["demoId"] for run in listed}
            assert all("parameters" in run and "request" not in run for run in listed)
            assert main.six_demo_service._queue is main.inference_queue
    finally:
        if main.inference_queue.is_alive:
            main.inference_queue.close()
