"""Behavioral tests for the six-Demo durable inference service."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

APP_BACKEND = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(APP_BACKEND))

from studio.app.persistence import PersistentStudioState
from studio.app.six_demo_service import SIX_DEMO_IDS, SixDemoService


class SixDemoServiceTests(unittest.TestCase):
    def test_submitted_scene_version_is_durable_and_readable_by_run_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "studio-state.json"
            state = PersistentStudioState(state_path)
            service = SixDemoService(
                state,
                execute=lambda run: {
                    "provider": "local-environment",
                    "responseSha256": f"digest-{run['runId']}",
                    "demoId": run["request"]["demoId"],
                },
                run_id_factory=lambda: "run-six-demo",
            )
            try:
                scene_version = {
                    "sceneVersionId": "scene-version-7",
                    "sceneId": "scene-4",
                    "navigationInstruction": "turn right",
                }

                submitted = service.submit_run(
                    scene_version,
                    demo_id="navigation-lab",
                    parameters={"seed": 42},
                )
                scene_version["navigationInstruction"] = "mutated after submission"

                self.assertEqual(submitted["runId"], "run-six-demo")
                self.assertIn(submitted["status"], {"queued", "running", "completed"})
                self.assertTrue(service.wait_for_idle(timeout=2))

                saved = service.get_run("run-six-demo")
                self.assertEqual(saved["status"], "completed")
                self.assertEqual(saved["sceneId"], "scene-4")
                self.assertEqual(saved["sceneVersionId"], "scene-version-7")
                self.assertEqual(saved["result"]["demoId"], "navigation-lab")
                self.assertNotIn("request", saved)

                restarted = PersistentStudioState(state_path)
                persisted = restarted.get_run("run-six-demo")
                self.assertEqual(persisted["request"]["sceneVersion"]["navigationInstruction"], "turn right")
            finally:
                service.close()

    def test_service_rejects_credential_like_parameters_before_queue_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "studio-state.json"
            state = PersistentStudioState(state_path)
            service = SixDemoService(state, execute=lambda run: {"provider": "local-environment"})
            try:
                with self.assertRaisesRegex(ValueError, "credential-like"):
                    service.submit_run(
                        {"sceneVersionId": "scene-version-1", "sceneId": "scene-1"},
                        demo_id="scene-workbench",
                        parameters={"apiKey": "must-not-be-stored"},
                    )
                self.assertFalse(state_path.exists())
            finally:
                service.close()

    def test_executor_credential_fields_are_removed_before_result_persistence_and_readback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "studio-state.json"
            state = PersistentStudioState(state_path)
            service = SixDemoService(
                state,
                execute=lambda run: {
                    "provider": "local-environment",
                    "apiKey": "test-value",
                    "output": {
                        "summary": "safe",
                        "authorization": "test-value",
                        "items": [{"token": "test-value", "score": 0.98}],
                    },
                },
                run_id_factory=lambda: "run-redacted-result",
            )
            try:
                service.submit_run(
                    {"sceneVersionId": "scene-version-1", "sceneId": "scene-1"},
                    demo_id="scene-workbench",
                )
                self.assertTrue(service.wait_for_idle(timeout=2))

                persisted = PersistentStudioState(state_path).get_run("run-redacted-result")
                readback = service.get_run("run-redacted-result")
                self.assertEqual(persisted["result"], {"provider": "local-environment", "output": {"summary": "safe", "items": [{"score": 0.98}]}})
                self.assertEqual(readback["result"], persisted["result"])
            finally:
                service.close()

    def test_executor_error_text_is_removed_before_failure_persistence_and_readback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "studio-state.json"
            state = PersistentStudioState(state_path)

            def execute(_: dict[str, object]) -> dict[str, str]:
                error = RuntimeError("provider failure apiKey=test-value authorization=test-value token=test-value")
                error.status_code = 429
                error.detail = "provider failure apiKey=test-value authorization=test-value token=test-value"
                raise error

            service = SixDemoService(state, execute=execute, run_id_factory=lambda: "run-redacted-error")
            try:
                service.submit_run(
                    {"sceneVersionId": "scene-version-1", "sceneId": "scene-1"},
                    demo_id="scene-workbench",
                )
                self.assertTrue(service.wait_for_idle(timeout=2))

                persisted = PersistentStudioState(state_path).get_run("run-redacted-error")
                readback = service.get_run("run-redacted-error")
                expected_error = {"message": "Inference execution failed", "statusCode": 429, "retryable": False}
                self.assertEqual(persisted["status"], "failed")
                self.assertEqual(persisted["error"], expected_error)
                self.assertEqual(readback["error"], expected_error)
            finally:
                service.close()

    def test_all_six_demos_share_the_single_durable_fifo_queue(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = PersistentStudioState(Path(directory) / "studio-state.json")
            run_ids = iter(f"run-{index}" for index in range(1, 7))
            executed: list[str] = []

            def execute(run: dict[str, object]) -> dict[str, str]:
                demo_id = str(run["request"]["demoId"])
                executed.append(demo_id)
                return {"provider": "local-environment", "responseSha256": demo_id}

            service = SixDemoService(state, execute=execute, run_id_factory=lambda: next(run_ids))
            try:
                demo_ids = sorted(SIX_DEMO_IDS)
                for demo_id in demo_ids:
                    service.submit_run(
                        {"sceneVersionId": "scene-version-1", "sceneId": "scene-1"},
                        demo_id=demo_id,
                    )

                self.assertTrue(service.wait_for_idle(timeout=2))
                self.assertEqual(executed, demo_ids)
                self.assertEqual(
                    [service.get_run(f"run-{index}")["result"]["responseSha256"] for index in range(1, 7)],
                    demo_ids,
                )
            finally:
                service.close()


if __name__ == "__main__":
    unittest.main()
