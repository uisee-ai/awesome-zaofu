import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  createSceneCreationController,
  type SceneCreationRequest,
} from "../../../web/src/features/scene-create/scene-creation-controller.js";

const appRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");

const uploadedAsset = {
  assetId: "asset-front-0",
  filename: "front-0.jpg",
  mimeType: "image/jpeg" as const,
  sizeBytes: 1024,
};

function request(): SceneCreationRequest {
  return {
    name: "urban-right-turn-001",
    navigationInstruction: "Turn right at the intersection",
    cameras: [{ cameraId: 0, assets: [uploadedAsset] }],
  };
}

test("scene creation controller submits uploaded assets and navigation only to the Studio Backend", async () => {
  let received: SceneCreationRequest | undefined;
  const controller = createSceneCreationController(async (submitted) => {
    received = submitted;
    return { sceneId: "scene-1", sceneVersionId: "scene-version-1" };
  });

  const created = await controller.create(request());

  assert.deepEqual(created, { sceneId: "scene-1", sceneVersionId: "scene-version-1" });
  assert.deepEqual(received, request());
  assert.deepEqual(controller.snapshot(), { phase: "created", sceneVersionId: "scene-version-1" });
});

test("backend stores an immutable SceneVersion snapshot for each creation", () => {
  const result = spawnSync(
    "python3",
    [
      "-c",
      [
        "from studio.assets import AssetUpload",
        "from studio.scenes.create import CreateSceneRequest, InMemorySceneRepository, UploadedSceneAsset, create_scene",
        "from studio.schemas.scene import CameraInput, FrameInput, SceneInput",
        "repository = InMemorySceneRepository()",
        "scene_input = SceneInput(name='urban-right-turn-001', cameras=[CameraInput(camera_id=0, frames=[FrameInput(content_type='image/jpeg', filename='front-0.jpg')])])",
        "request = CreateSceneRequest(scene_input=scene_input, navigation_instruction='Turn right at the intersection', uploaded_assets=[UploadedSceneAsset(asset_id='asset-front-0', upload=AssetUpload(filename='front-0.jpg', content_type='image/jpeg', size_bytes=1024))])",
        "created = create_scene(repository, request)",
        "scene_input.cameras[0].frames[0] = FrameInput(content_type='image/jpeg', filename='changed.jpg')",
        "assert created.scene_version.scene_input.cameras[0].frames[0].filename == 'front-0.jpg'",
        "assert created.scene_version.navigation_instruction == 'Turn right at the intersection'",
        "assert created.scene.current_version_id == created.scene_version.id",
        "assert len(repository.scene_versions(created.scene.id)) == 1",
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

test("backend requires every uploaded asset and scene frame to have a unique one-to-one match", () => {
  const result = spawnSync(
    "python3",
    [
      "-c",
      [
        "from studio.assets import AssetUpload",
        "from studio.scenes.create import CreateSceneRequest, InMemorySceneRepository, SceneCreationError, UploadedSceneAsset, create_scene",
        "from studio.schemas.scene import CameraInput, FrameInput, SceneInput",
        "def asset(asset_id, filename):",
        "    return UploadedSceneAsset(asset_id=asset_id, upload=AssetUpload(filename=filename, content_type='image/jpeg', size_bytes=1024))",
        "def request(frames, assets):",
        "    return CreateSceneRequest(scene_input=SceneInput(name='one-to-one', cameras=[CameraInput(camera_id=0, frames=frames)]), navigation_instruction='Continue ahead', uploaded_assets=assets)",
        "def expect_error(expected_code, invalid_request):",
        "    try:",
        "        create_scene(InMemorySceneRepository(), invalid_request)",
        "    except SceneCreationError as error:",
        "        assert error.code == expected_code, error.code",
        "    else:",
        "        raise AssertionError('invalid asset-to-frame mapping was accepted')",
        "expect_error('DUPLICATE_FRAME_FILENAME', request([FrameInput(content_type='image/jpeg', filename='front.jpg'), FrameInput(content_type='image/jpeg', filename='front.jpg')], [asset('asset-front', 'front.jpg'), asset('asset-unreferenced', 'unreferenced.jpg')]))",
        "expect_error('UNREFERENCED_ASSET', request([FrameInput(content_type='image/jpeg', filename='front.jpg')], [asset('asset-front', 'front.jpg'), asset('asset-unreferenced', 'unreferenced.jpg')]))",
        "created = create_scene(InMemorySceneRepository(), request([FrameInput(content_type='image/jpeg', filename='front.jpg'), FrameInput(content_type='image/jpeg', filename='side.jpg')], [asset('asset-front', 'front.jpg'), asset('asset-side', 'side.jpg')]))",
        "assert created.scene_version.asset_ids == ('asset-front', 'asset-side')",
        "assert len(set(created.scene_version.asset_ids)) == 2",
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
