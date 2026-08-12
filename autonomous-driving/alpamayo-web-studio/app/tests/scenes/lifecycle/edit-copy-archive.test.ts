import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  createSceneLifecycleController,
  type SceneLifecycleGateway,
} from "../../../web/src/features/scene-lifecycle/scene-lifecycle-controller.js";

const appRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");

test("editing, copying, and archiving scenes preserves audit history and immutable run versions", () => {
  const result = spawnSync(
    "python3",
    [
      "-c",
      [
        "from studio.assets import AssetUpload",
        "from studio.scenes.create import CreateSceneRequest, InMemorySceneRepository, UploadedSceneAsset, create_scene",
        "from studio.scenes.lifecycle import SceneLifecycleService",
        "from studio.schemas.scene import CameraInput, FrameInput, SceneInput",
        "repository = InMemorySceneRepository()",
        "created = create_scene(repository, CreateSceneRequest(scene_input=SceneInput(name='original', cameras=[CameraInput(camera_id=0, frames=[FrameInput(content_type='image/jpeg', filename='front.jpg')])]), navigation_instruction='Continue ahead', uploaded_assets=[UploadedSceneAsset(asset_id='asset-front', upload=AssetUpload(filename='front.jpg', content_type='image/jpeg', size_bytes=1024))]))",
        "original_version = created.scene_version",
        "lifecycle = SceneLifecycleService(repository)",
        "edited = lifecycle.edit_scene(created.scene.id, name='edited', navigation_instruction='Turn right', actor_id='alice')",
        "copied = lifecycle.copy_scene(created.scene.id, name='copied', actor_id='bob')",
        "archived = lifecycle.archive_scene(created.scene.id, actor_id='alice')",
        "assert edited.scene.current_version_id != original_version.id",
        "assert original_version.scene_input.name == 'original'",
        "assert original_version.navigation_instruction == 'Continue ahead'",
        "assert edited.scene_version.scene_input.name == 'edited'",
        "assert edited.scene_version.navigation_instruction == 'Turn right'",
        "assert copied.scene.id != created.scene.id",
        "assert copied.scene_version.scene_id == copied.scene.id",
        "assert copied.scene_version.id != original_version.id",
        "assert archived.is_archived is True",
        "assert [(record.action, record.actor_id) for record in lifecycle.audit_records()] == [('edited', 'alice'), ('copied', 'bob'), ('archived', 'alice')]",
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

test("scene lifecycle controller sends edit, copy, and archive requests only through the Studio Backend", async () => {
  const received: string[] = [];
  const gateway: SceneLifecycleGateway = {
    edit: async (request) => {
      received.push(`edit:${request.sceneId}:${request.name}`);
      return { sceneId: request.sceneId, sceneVersionId: "scene-version-2" };
    },
    copy: async (request) => {
      received.push(`copy:${request.sceneId}:${request.name}`);
      return { sceneId: "scene-2", sceneVersionId: "scene-version-3" };
    },
    archive: async (request) => {
      received.push(`archive:${request.sceneId}`);
      return { sceneId: request.sceneId, isArchived: true };
    },
  };
  const controller = createSceneLifecycleController(gateway);

  await controller.edit({ sceneId: "scene-1", name: "edited", navigationInstruction: "Turn right" });
  await controller.copy({ sceneId: "scene-1", name: "copied" });
  const archived = await controller.archive({ sceneId: "scene-1" });

  assert.deepEqual(received, ["edit:scene-1:edited", "copy:scene-1:copied", "archive:scene-1"]);
  assert.deepEqual(archived, { sceneId: "scene-1", isArchived: true });
  assert.deepEqual(controller.snapshot(), { phase: "archived", sceneId: "scene-1" });
});
