import assert from "node:assert/strict";
import test from "node:test";

import { createSixDemoWorkflow } from "../../web/src/features/demo-switcher/six-demo-workflow.js";

const sharedScene = {
  sceneVersionId: "scene-version-persisted-32",
  cameraFrames: [],
  inference: {
    status: "succeeded" as const,
    chainOfCausation: "道路畅通。",
    metaAction: "continue",
    trajectory: [],
  },
};

test("all six demos reuse one persisted scene and expose their saved inference result", async () => {
  const savedRuns = new Map<string, { runId: string; status: "succeeded"; result: { summary: string } }>();
  const workflow = createSixDemoWorkflow({
    async submit(sceneVersionId, demo) {
      const run = {
        runId: `run-${demo}`,
        status: "succeeded" as const,
        result: { summary: `${demo} inference saved for ${sceneVersionId}` },
      };
      savedRuns.set(run.runId, run);
      return run;
    },
    async read(runId) {
      return savedRuns.get(runId) ?? null;
    },
  });

  const entries = workflow.open(sharedScene);
  assert.equal(entries.length, 6);
  assert.deepEqual(new Set(entries.map((entry) => entry.sceneVersionId)), new Set([sharedScene.sceneVersionId]));
  assert.deepEqual(entries.map((entry) => entry.uploadRequired), Array(6).fill(false));

  for (const entry of entries) {
    const submitted = await workflow.submit(entry.demo);
    assert.equal(submitted.sceneVersionId, sharedScene.sceneVersionId);
    assert.equal(submitted.status, "succeeded");

    const restored = await workflow.read(entry.demo);
    assert.deepEqual(restored.result, { summary: `${entry.demo} inference saved for ${sharedScene.sceneVersionId}` });
  }
});
