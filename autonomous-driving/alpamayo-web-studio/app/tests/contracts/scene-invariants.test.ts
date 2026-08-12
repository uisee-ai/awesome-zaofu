import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  SceneContractError,
  createInferenceResult,
  validateSceneInput,
  type SceneInput,
  type TrajectoryPoint,
} from "../../packages/contracts/src/index.js";

const cameraIds = [0, 1, 2, 6] as const;
const appRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");

function validScene(overrides: Partial<SceneInput> = {}): SceneInput {
  return {
    name: "golden intersection",
    cameras: cameraIds.map((cameraId) => ({
      cameraId,
      frames: Array.from({ length: 4 }, (_, frameIndex) => ({
        contentType: "image/jpeg",
        filename: `camera-${cameraId}-${frameIndex}.jpg`,
      })),
    })),
    history: {
      positions: Array.from({ length: 16 }, () => [0, 0, 0] as const),
      rotations: Array.from({ length: 16 }, () => [
        [1, 0, 0],
        [0, 1, 0],
        [0, 0, 1],
      ] as const),
    },
    ...overrides,
  };
}

function trajectory(): TrajectoryPoint[] {
  return Array.from({ length: 64 }, (_, index) => ({
    timeSeconds: Number(((index + 1) / 10).toFixed(1)),
    position: [index, 0, 0],
    rotation: [
      [1, 0, 0],
      [0, 1, 0],
      [0, 0, 1],
    ],
  }));
}

test("scene contract accepts synchronized JPEG/PNG camera frames", () => {
  const validated = validateSceneInput(validScene());

  assert.deepEqual(validated.warnings, []);
  assert.equal(validated.scene.cameras.length, 4);
  assert.equal(validated.scene.cameras[0]?.frames.length, 4);
});

test("scene contract rejects unsupported images, camera counts, and unequal frame counts", () => {
  assert.throws(
    () => validateSceneInput(validScene({ cameras: [] })),
    (error: unknown) => error instanceof SceneContractError && error.code === "CAMERA_COUNT",
  );

  const invalidType = validScene();
  invalidType.cameras[0]!.frames[0] = {
    contentType: "image/webp",
    filename: "unsupported.webp",
  };
  assert.throws(
    () => validateSceneInput(invalidType),
    (error: unknown) => error instanceof SceneContractError && error.code === "FRAME_FORMAT",
  );

  const unequalFrames = validScene();
  unequalFrames.cameras[1]!.frames.pop();
  assert.throws(
    () => validateSceneInput(unequalFrames),
    (error: unknown) => error instanceof SceneContractError && error.code === "FRAME_COUNT_MISMATCH",
  );
});

test("backend rejects an unsupported MIME even when its filename has a JPEG extension", () => {
  const validation = spawnSync(
    "python3",
    [
      "-c",
      [
        "from studio.schemas.scene import CameraInput, FrameInput, SceneInput, validate_scene_input",
        "scene = SceneInput(name='invalid MIME', cameras=[CameraInput(camera_id=0, frames=[FrameInput(content_type='image/webp', filename='frame.jpg')])])",
        "try:",
        "    validate_scene_input(scene)",
        "except ValueError:",
        "    raise SystemExit(0)",
        "raise SystemExit(1)",
      ].join("\n"),
    ],
    {
      cwd: appRoot,
      encoding: "utf8",
      env: { ...process.env, PYTHONPATH: path.join(appRoot, "backend") },
    },
  );

  assert.equal(validation.status, 0, validation.stderr);
});

test("backend accepts JPEG and PNG frames with matching filename extensions", () => {
  const validation = spawnSync(
    "python3",
    [
      "-c",
      [
        "from studio.schemas.scene import CameraInput, FrameInput, SceneInput, validate_scene_input",
        "scene = SceneInput(name='valid MIME', cameras=[CameraInput(camera_id=0, frames=[FrameInput(content_type='image/jpeg', filename='frame.jpg')]), CameraInput(camera_id=1, frames=[FrameInput(content_type='image/png', filename='frame.png')])])",
        "validate_scene_input(scene)",
      ].join("\n"),
    ],
    {
      cwd: appRoot,
      encoding: "utf8",
      env: { ...process.env, PYTHONPATH: path.join(appRoot, "backend") },
    },
  );

  assert.equal(validation.status, 0, validation.stderr);
});

test("missing history produces a prominent warning and defaults results to unreviewed", () => {
  const validated = validateSceneInput(validScene({ history: undefined }));
  const result = createInferenceResult({
    vqaAnswer: "The intersection is clear.",
    chainOfCausation: "No crossing traffic is present.",
    metaAction: "proceed_with_caution",
    trajectory: trajectory(),
  });

  assert.deepEqual(validated.warnings, [
    {
      code: "MISSING_HISTORY",
      severity: "warning",
      message: "车辆历史缺失；将使用静止车辆默认值，结果必须人工审核。",
    },
  ]);
  assert.equal(result.reviewStatus, "unreviewed");
});

test("results require VQA, CoC, Meta Action, and 64 future points at 0.1-second intervals", () => {
  const result = createInferenceResult({
    vqaAnswer: "Clear lane ahead.",
    chainOfCausation: "Lead vehicle is outside the predicted path.",
    metaAction: "continue",
    trajectory: trajectory(),
  });

  assert.equal(result.trajectory.length, 64);
  assert.equal(result.trajectory[63]?.timeSeconds, 6.4);

  assert.throws(
    () => createInferenceResult({ ...result, trajectory: trajectory().slice(0, 63) }),
    (error: unknown) => error instanceof SceneContractError && error.code === "TRAJECTORY_LENGTH",
  );
});
