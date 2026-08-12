"""Contract tests for the Studio process-independent FIFO runtime."""

from __future__ import annotations

import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

APP_BACKEND = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(APP_BACKEND))

from studio.app.persistence import PersistentStudioState, SingleConcurrencyInferenceQueue


class PersistenceAndQueueTests(unittest.TestCase):
    def test_scenes_and_completed_results_survive_a_new_state_instance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "studio-state.json"
            state = PersistentStudioState(state_path)
            state.save_scene({"sceneId": "scene-1", "name": "Golden road", "status": "ready"})
            state.save_run(
                {
                    "runId": "run-1",
                    "sceneId": "scene-1",
                    "status": "queued",
                    "queueSequence": 1,
                    "request": {"scene": {"name": "Golden road"}},
                }
            )
            claimed = state.claim_next_run()
            self.assertEqual(claimed["runId"], "run-1")
            state.complete_run("run-1", {"provider": "litellm", "responseSha256": "digest"}, claimed["leaseId"])

            restarted = PersistentStudioState(state_path)
            self.assertEqual(restarted.get_scene("scene-1")["name"], "Golden road")
            self.assertEqual(restarted.get_run("run-1")["status"], "completed")
            self.assertEqual(restarted.get_run("run-1")["result"]["responseSha256"], "digest")

    def test_all_inference_work_runs_in_fifo_order_with_one_active_executor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = PersistentStudioState(Path(directory) / "studio-state.json")
            first_started = threading.Event()
            release_first = threading.Event()
            second_started = threading.Event()
            active = 0
            maximum_active = 0
            started: list[str] = []
            active_lock = threading.Lock()

            def execute(run: dict[str, object]) -> dict[str, str]:
                nonlocal active, maximum_active
                with active_lock:
                    active += 1
                    maximum_active = max(maximum_active, active)
                    started.append(str(run["runId"]))
                if run["runId"] == "run-1":
                    first_started.set()
                    release_first.wait(timeout=2)
                else:
                    second_started.set()
                with active_lock:
                    active -= 1
                return {"provider": "test", "responseSha256": str(run["runId"])}

            queue = SingleConcurrencyInferenceQueue(state, execute)
            queue.enqueue("run-1", {"scene": {"name": "first"}})
            queue.enqueue("run-2", {"scene": {"name": "second"}})
            self.assertTrue(first_started.wait(timeout=1))
            self.assertFalse(second_started.wait(timeout=0.1))
            self.assertEqual(state.get_run("run-2")["status"], "queued")

            release_first.set()
            self.assertTrue(queue.wait_for_idle(timeout=2))
            self.assertEqual(started, ["run-1", "run-2"])
            self.assertEqual(maximum_active, 1)
            self.assertEqual(state.get_run("run-1")["status"], "completed")
            self.assertEqual(state.get_run("run-2")["status"], "completed")

    def test_independent_queue_instances_share_one_fifo_lease(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "studio-state.json"
            seed_state = PersistentStudioState(state_path, lease_seconds=0.08)
            seed_state.save_run(
                {
                    "runId": "run-1",
                    "status": "queued",
                    "queueSequence": 1,
                    "request": {"scene": {"name": "shared"}},
                }
            )
            seed_state.save_run(
                {
                    "runId": "run-2",
                    "status": "queued",
                    "queueSequence": 2,
                    "request": {"scene": {"name": "shared"}},
                }
            )
            first_instance = PersistentStudioState(state_path, lease_seconds=0.08)
            second_instance = PersistentStudioState(state_path, lease_seconds=0.08)
            started = threading.Event()
            release = threading.Event()
            executions: list[str] = []
            executions_lock = threading.Lock()
            active = 0
            maximum_active = 0

            def execute(run: dict[str, object]) -> dict[str, str]:
                nonlocal active, maximum_active
                run_id = str(run["runId"])
                with executions_lock:
                    active += 1
                    maximum_active = max(maximum_active, active)
                    executions.append(run_id)
                    started.set()
                if run_id == "run-1":
                    release.wait(timeout=2)
                with executions_lock:
                    active -= 1
                return {"provider": "test", "responseSha256": run_id}

            first_queue = SingleConcurrencyInferenceQueue(first_instance, execute)
            second_queue = SingleConcurrencyInferenceQueue(second_instance, execute)
            try:
                self.assertTrue(started.wait(timeout=1))
                time.sleep(0.25)
                self.assertEqual(executions, ["run-1"])
                self.assertEqual(maximum_active, 1)
                release.set()
                self.assertTrue(first_queue.wait_for_idle(timeout=2))
                self.assertTrue(second_queue.wait_for_idle(timeout=2))
                self.assertEqual(executions, ["run-1", "run-2"])
                self.assertEqual(maximum_active, 1)
                restarted = PersistentStudioState(state_path, lease_seconds=0.08)
                self.assertEqual(restarted.get_run("run-1")["status"], "completed")
                self.assertEqual(restarted.get_run("run-2")["status"], "completed")
            finally:
                release.set()
                first_queue.close()
                second_queue.close()

    def test_stale_lease_owner_cannot_complete_a_newer_claim(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "studio-state.json"
            original_owner = PersistentStudioState(state_path, lease_seconds=0.05)
            original_owner.save_run(
                {
                    "runId": "fenced",
                    "status": "queued",
                    "queueSequence": 1,
                    "request": {"scene": {"name": "shared"}},
                }
            )
            first_claim = original_owner.claim_next_run()
            time.sleep(0.08)
            replacement_owner = PersistentStudioState(state_path, lease_seconds=0.05)
            second_claim = replacement_owner.claim_next_run()

            self.assertNotEqual(first_claim["leaseId"], second_claim["leaseId"])
            self.assertIsNone(
                original_owner.complete_run(
                    "fenced",
                    {"provider": "stale", "responseSha256": "old"},
                    first_claim["leaseId"],
                )
            )
            replacement_owner.complete_run(
                "fenced",
                {"provider": "current", "responseSha256": "new"},
                second_claim["leaseId"],
            )
            finished = PersistentStudioState(state_path, lease_seconds=0.05).get_run("fenced")
            self.assertEqual(finished["result"]["provider"], "current")


if __name__ == "__main__":
    unittest.main()
