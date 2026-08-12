import assert from "node:assert/strict";
import test from "node:test";

import { createStudioDemoInferenceClient } from "../../src/lib/studio-api.js";
import { createSixDemoWorkflow } from "../../web/src/features/demo-switcher/six-demo-workflow.js";

function jsonResponse(payload: unknown): Response {
  return {
    ok: true,
    json: async () => payload,
  } as Response;
}

test("each Studio demo posts its shared persisted scene then reads the saved run", async () => {
  const requests: Array<{ url: string; method: string; body: string | undefined }> = [];
  const client = createStudioDemoInferenceClient(async (input, init) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    requests.push({ url, method, body: init?.body?.toString() });

    if (method === "POST") {
      const demoId = JSON.parse(init?.body?.toString() ?? "{}") as { demoId: string };
      return jsonResponse({ runId: `run-${demoId.demoId}`, status: "queued", result: null });
    }

    return jsonResponse({ runId: url.split("/").at(-1), status: "completed", result: { saved: true } });
  });
  const workflow = createSixDemoWorkflow(client);
  const entries = workflow.open({
    sceneVersionId: "scene persisted/37",
    cameraFrames: [],
    inference: { status: "succeeded", chainOfCausation: "clear", metaAction: "continue", trajectory: [] },
  });

  for (const entry of entries) {
    const submitted = await workflow.submit(entry.demo);
    assert.equal(submitted.runId, `run-${entry.demo}`);
    assert.equal(submitted.status, "queued");

    const restored = await workflow.read(entry.demo);
    assert.deepEqual(restored.result, { saved: true });
    assert.equal(restored.status, "completed");
  }

  assert.equal(requests.length, 12);
  for (const [index, entry] of entries.entries()) {
    const post = requests[index * 2]!;
    const get = requests[index * 2 + 1]!;
    assert.deepEqual(post, {
      url: "/api/scenes/scene%20persisted%2F37/runs",
      method: "POST",
      body: JSON.stringify({ demoId: entry.demo, parameters: {} }),
    });
    assert.deepEqual(get, {
      url: `/api/runs/run-${entry.demo}`,
      method: "GET",
      body: undefined,
    });
  }
});
