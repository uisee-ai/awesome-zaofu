import assert from "node:assert/strict";
import test from "node:test";

import {
  DEMO_DESTINATIONS,
  SharedSceneEntryService,
} from "../../backend/studio/demo-linking/shared-scene-entry.js";
import { createDemoSwitcher } from "../../web/src/features/demo-switcher/demo-switcher.js";
import { RESEARCH_USE_NOTICE } from "../../web/src/components/safety/index.js";

const sharedScene = {
  sceneVersionId: "scene-version-cross-demo-1",
  cameraFrames: [
    { cameraId: 3, frames: [{ contentType: "image/png", filename: "left.png" }] },
    { cameraId: 1, frames: [{ contentType: "image/jpeg", filename: "front.jpg" }] },
  ],
  inference: {
    status: "succeeded" as const,
    chainOfCausation: "路口清晰可见。",
    metaAction: "continue",
    trajectory: [{ timeSeconds: 0.1, position: [1, 2, 0] as const }],
  },
};

test("one shared SceneVersion enters every demo without another upload", () => {
  const service = new SharedSceneEntryService();
  const entries = service.createEntries(sharedScene.sceneVersionId);

  assert.deepEqual(entries.map((entry) => entry.demo), DEMO_DESTINATIONS);
  assert.deepEqual(entries.map((entry) => entry.sceneVersionId), Array(DEMO_DESTINATIONS.length).fill(sharedScene.sceneVersionId));
  assert.deepEqual(entries.map((entry) => entry.uploadRequired), Array(DEMO_DESTINATIONS.length).fill(false));
  assert.deepEqual(entries.map((entry) => entry.href), [
    "/workbench?sceneVersionId=scene-version-cross-demo-1",
    "/navigation?sceneVersionId=scene-version-cross-demo-1",
    "/ablation?sceneVersionId=scene-version-cross-demo-1",
    "/vqa?sceneVersionId=scene-version-cross-demo-1",
    "/auto-label?sceneVersionId=scene-version-cross-demo-1",
    "/regression-judge?sceneVersionId=scene-version-cross-demo-1",
  ]);
});

test("each demo entry reuses shared visualizations and exposes the research-use notice", () => {
  const switcher = createDemoSwitcher();
  const entries = switcher.createEntries(sharedScene);

  assert.deepEqual(entries.map((entry) => entry.demo), DEMO_DESTINATIONS);
  for (const entry of entries) {
    assert.equal(entry.sceneVersionId, sharedScene.sceneVersionId);
    assert.equal(entry.uploadRequired, false);
    assert.equal(entry.researchUseNotice, RESEARCH_USE_NOTICE);
    assert.deepEqual(entry.visualizations.camera.cameras.map((camera) => camera.cameraId), [1, 3]);
    assert.equal(entry.visualizations.runStatus.status, "succeeded");
    assert.deepEqual(entry.visualizations.inference, {
      chainOfCausation: "路口清晰可见。",
      metaAction: "continue",
    });
    assert.deepEqual(entry.visualizations.trajectory.points, [{ timeSeconds: 0.1, x: 1, y: 2 }]);
  }
});
