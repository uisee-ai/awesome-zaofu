import assert from "node:assert/strict";
import test from "node:test";

import {
  CameraAblationService,
  type CameraAblationInferenceResult,
} from "../../backend/studio/ablation/camera-ablation-service.js";
import {
  CameraAblationController,
  type CameraAblationClient,
} from "../../web/src/features/ablation/camera-ablation-controller.js";

const rotation = [
  [1, 0, 0],
  [0, 1, 0],
  [0, 0, 1],
] as const;

function trajectory(offsetY = 0) {
  return Array.from({ length: 64 }, (_, index) => ({
    timeSeconds: Number(((index + 1) * 0.1).toFixed(1)),
    position: [index * 0.5, offsetY + index * 0.1, 0] as const,
    rotation,
  }));
}

function output(offsetY = 0): CameraAblationInferenceResult {
  return {
    chainOfCausation: "根据可见车道与交通参与者保持预测轨迹。",
    metaAction: "减速并保持车道。",
    trajectory: trajectory(offsetY),
  };
}

test("creates preset or custom ablations from an existing scene without uploading, and records sorted camera IDs", async () => {
  const service = new CameraAblationService(
    {
      id: "scene-right-turn",
      cameraIds: [0, 1, 2, 3, 4, 5, 6],
      navigationInstruction: "Turn right at the intersection",
    },
    async ({ cameraIds }) => output(cameraIds.length === 7 ? 0 : 1),
  );

  const standard = await service.run({ preset: "standard-four", parameters: { temperature: 0.1 }, seed: 4 });
  const custom = await service.run({ cameraIds: [2, 1], parameters: { temperature: 0.1 }, seed: 4 });

  assert.deepEqual(standard.cameraIds, [0, 1, 2, 6]);
  assert.deepEqual(custom.cameraIds, [1, 2]);
  assert.equal(custom.sceneId, "scene-right-turn");
  assert.equal(custom.uploadRequired, false);
  assert.notEqual(custom.id, standard.id);
});

test("presents baseline and ablation trajectories side by side with camera composition, result details, and coverage risk", async () => {
  const service = new CameraAblationService(
    {
      id: "scene-right-turn",
      cameraIds: [0, 1, 2, 3, 4, 5, 6],
      navigationInstruction: "Turn right at the intersection",
    },
    async ({ cameraIds }) => output(cameraIds.length === 7 ? 0 : 2),
  );
  const client: CameraAblationClient = { run: (request) => service.run(request) };
  const controller = new CameraAblationController(client);

  const view = await controller.compare({
    baseline: { preset: "all-cameras", parameters: { temperature: 0.1 }, seed: 7 },
    ablation: { cameraIds: [1], parameters: { temperature: 0.1 }, seed: 7 },
  });

  assert.deepEqual(view.baseline.cameraIds, [0, 1, 2, 3, 4, 5, 6]);
  assert.deepEqual(view.ablation.cameraIds, [1]);
  assert.equal(view.baseline.trajectory.points.length, 64);
  assert.equal(view.ablation.trajectory.points.length, 64);
  assert.equal(view.comparison.averageLateralDifference, 2);
  assert.match(view.ablation.risks[0].message, /右转/);
  assert.match(view.ablation.risks[0].message, /Camera ID 2/);
  assert.equal(view.baseline.result.chainOfCausation, "根据可见车道与交通参与者保持预测轨迹。");
  assert.equal(view.ablation.result.metaAction, "减速并保持车道。");
});

test("rejects camera combinations that are absent from the selected scene", async () => {
  const service = new CameraAblationService(
    { id: "scene-front", cameraIds: [0, 1, 2] },
    async () => output(),
  );

  await assert.rejects(
    service.run({ cameraIds: [1, 6], parameters: {}, seed: 1 }),
    (error: unknown) => error instanceof Error && error.message.includes("不存在于当前场景"),
  );
});
