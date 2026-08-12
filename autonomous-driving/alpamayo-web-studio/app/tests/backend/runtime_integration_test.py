"""Integration-focused coverage for the assembled Studio runtime boundaries."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

APP_BACKEND = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(APP_BACKEND))

from studio.app.contracts import ProviderInferencePayload
from studio.app.persistence import PersistentStudioState, SingleConcurrencyInferenceQueue
from studio.app.provider import AlpamayoProvider
from studio.app.six_demo_service import SixDemoService


def test_mock_provider_returns_complete_demo_specific_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPAMAYO_STUDIO_PROVIDER_MODE", "mock")
    with tempfile.TemporaryDirectory() as directory:
        provider = AlpamayoProvider(
            image_loader=lambda: b"\x89PNG\r\n\x1a\nmock",
            artifact_dir=Path(directory) / "provider-responses",
        )
        scene = {"cameras": [{"cameraId": 0, "frames": [{"assetRef": "fixture.png"}]}]}

        workbench = provider.invoke(scene, demo_id="scene-workbench")
        vqa = provider.invoke(scene, demo_id="scene-vqa", parameters={"question": "What is ahead?"})

        assert ProviderInferencePayload.model_validate(workbench)
        assert ProviderInferencePayload.model_validate(vqa)
        assert len(workbench["trajectory"]) == 64
        assert workbench["demoId"] == "scene-workbench"
        assert vqa["demoId"] == "scene-vqa"
        assert workbench["responseSha256"] != vqa["responseSha256"]
        assert "What is ahead?" in vqa["vqaAnswer"]
        raw_output = Path(directory) / vqa["rawOutputRef"]
        assert raw_output.is_file()
        assert raw_output.stat().st_mode & 0o777 == 0o600


def test_shared_queue_dispatches_generic_and_six_demo_runs_by_run_type() -> None:
    with tempfile.TemporaryDirectory() as directory:
        state = PersistentStudioState(Path(directory) / "studio-state.json")
        executed: list[str] = []

        def dispatch(run: dict[str, object]) -> dict[str, str]:
            request = run["request"]
            assert isinstance(request, dict)
            run_type = str(request["runType"])
            executed.append(run_type)
            return {"provider": "test", "responseSha256": run_type}

        queue = SingleConcurrencyInferenceQueue(state, dispatch)
        service = SixDemoService(state, queue=queue, run_id_factory=lambda: "run-demo")
        try:
            queue.enqueue("run-generic", {"runType": "generic", "payload": {}})
            service.submit_run(
                {"sceneVersionId": "scene-version-1", "sceneId": "scene-1"},
                demo_id="scene-vqa",
            )

            assert queue.wait_for_idle(timeout=2)
            assert executed == ["generic", "six-demo"]
            assert state.get_run("run-generic")["result"]["responseSha256"] == "generic"
            assert service.get_run("run-demo")["result"]["responseSha256"] == "six-demo"
        finally:
            service.close()
            assert queue.is_alive
            queue.close()
