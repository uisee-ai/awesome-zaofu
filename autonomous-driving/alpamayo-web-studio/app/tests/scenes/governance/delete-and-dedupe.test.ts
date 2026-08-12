import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  createSceneDeletionController,
  SceneDeletionError,
} from "../../../web/src/features/scene-governance/scene-deletion-controller.js";

const appRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");

test("scene deletion controller requires a second confirmation before calling the Studio Backend", async () => {
  const submitted: string[] = [];
  const controller = createSceneDeletionController(async (sceneId) => {
    submitted.push(sceneId);
  });

  controller.requestDeletion("scene-1");
  assert.deepEqual(controller.snapshot(), { phase: "awaiting_confirmation", sceneId: "scene-1" });
  assert.deepEqual(submitted, []);

  await controller.confirmDeletion();

  assert.deepEqual(submitted, ["scene-1"]);
  assert.deepEqual(controller.snapshot(), { phase: "deleted", sceneId: "scene-1" });
});

test("scene deletion controller cannot confirm before a deletion was requested", async () => {
  const controller = createSceneDeletionController(async () => undefined);

  await assert.rejects(
    controller.confirmDeletion(),
    (error: unknown) => error instanceof SceneDeletionError && error.code === "CONFIRMATION_REQUIRED",
  );
});

test("backend keeps deleted scenes recoverable, requires an administrator confirmation, and deduplicates by content hash", () => {
  const result = spawnSync(
    "python3",
    [
      "-c",
      [
        "from studio.governance import GovernanceError, InMemorySceneGovernance",
        "governance = InMemorySceneGovernance()",
        "governance.add_scene('scene-1', 'urban-right-turn-001')",
        "first_asset = governance.store_asset(b'same-image-content')",
        "duplicate_asset = governance.store_asset(b'same-image-content')",
        "assert first_asset == duplicate_asset",
        "assert governance.asset_count() == 1",
        "try:",
        "    governance.request_deletion('scene-1', actor_id='viewer-1', is_administrator=False)",
        "except GovernanceError as error:",
        "    assert error.code == 'ADMIN_REQUIRED'",
        "else:",
        "    raise AssertionError('non-administrator could request deletion')",
        "confirmation = governance.request_deletion('scene-1', actor_id='admin-1', is_administrator=True)",
        "assert governance.active_scene('scene-1') is not None",
        "try:",
        "    governance.confirm_deletion('scene-1', actor_id='admin-1', confirmation_id='wrong-token', is_administrator=True)",
        "except GovernanceError as error:",
        "    assert error.code == 'CONFIRMATION_REQUIRED'",
        "else:",
        "    raise AssertionError('deletion completed without its confirmation token')",
        "deleted = governance.confirm_deletion('scene-1', actor_id='admin-1', confirmation_id=confirmation.id, is_administrator=True)",
        "assert deleted.deleted_at is not None",
        "assert deleted.deleted_by == 'admin-1'",
        "assert governance.active_scene('scene-1') is None",
        "assert governance.scene_record('scene-1') == deleted",
      ].join("\n"),
    ],
    {
      cwd: appRoot,
      encoding: "utf8",
      env: { ...process.env, PYTHONPATH: path.join(appRoot, "backend") },
    },
  );

  assert.equal(result.status, 0, result.stderr);
});
