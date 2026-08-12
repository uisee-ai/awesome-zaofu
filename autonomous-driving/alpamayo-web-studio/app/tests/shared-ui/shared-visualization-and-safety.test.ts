import assert from "node:assert/strict";
import test from "node:test";

import {
  createCameraVisualization,
  createInferenceVisualization,
  createRunStatusVisualization,
  createTrajectoryVisualization,
} from "../../web/src/components/studio/index.js";
import { RESEARCH_USE_NOTICE, createResearchUseNotice } from "../../web/src/components/safety/index.js";

test("shared visualizations expose sorted camera, run, CoC/Meta Action, and trajectory views", () => {
  const cameras = createCameraVisualization({
    selectedFrameIndex: 1,
    cameras: [
      { cameraId: 6, frames: [{ contentType: "image/png", filename: "rear-0.png" }, { contentType: "image/png", filename: "rear-1.png" }] },
      { cameraId: 1, frames: [{ contentType: "image/jpeg", filename: "front-0.jpg" }, { contentType: "image/jpeg", filename: "front-1.jpg" }] },
    ],
  });
  const status = createRunStatusVisualization("running");
  const inference = createInferenceVisualization({
    chainOfCausation: "The junction is clear.",
    metaAction: "continue",
  });
  const trajectory = createTrajectoryVisualization([
    { timeSeconds: 0.1, position: [1, 2, 0] },
    { timeSeconds: 0.2, position: [3, 5, 0] },
  ]);

  assert.deepEqual(cameras.cameras.map((camera) => camera.cameraId), [1, 6]);
  assert.deepEqual(cameras.cameras.map((camera) => camera.frame.filename), ["front-1.jpg", "rear-1.png"]);
  assert.deepEqual(status, { status: "running", label: "运行中", tone: "info" });
  assert.deepEqual(inference, { chainOfCausation: "The junction is clear.", metaAction: "continue" });
  assert.deepEqual(trajectory, {
    pointCount: 2,
    horizonSeconds: 0.2,
    points: [
      { timeSeconds: 0.1, x: 1, y: 2 },
      { timeSeconds: 0.2, x: 3, y: 5 },
    ],
  });
});

test("research-use notice says the product is for research and not real vehicle control or safety certification", () => {
  assert.equal(createResearchUseNotice(), RESEARCH_USE_NOTICE);
  assert.match(RESEARCH_USE_NOTICE, /研究、实验、评测和演示/);
  assert.match(RESEARCH_USE_NOTICE, /真实车辆控制/);
  assert.match(RESEARCH_USE_NOTICE, /安全认证/);
  assert.match(RESEARCH_USE_NOTICE, /驾驶安全结论/);
});
