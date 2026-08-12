import assert from "node:assert/strict";
import test from "node:test";

import {
  SequentialEvaluationBatch,
  type EvaluationScenario,
} from "../../backend/studio/evaluation/sequential-batch.js";

const scenarios: EvaluationScenario[] = Array.from({ length: 10 }, (_, index) => ({
  id: `scene-${index + 1}`,
}));

test("runs at least ten evaluation scenarios sequentially and continues after a failure", async () => {
  const started: string[] = [];
  let inFlight = 0;
  let maximumInFlight = 0;
  const batch = new SequentialEvaluationBatch(async (scenario) => {
    started.push(scenario.id);
    inFlight += 1;
    maximumInFlight = Math.max(maximumInFlight, inFlight);
    await Promise.resolve();
    inFlight -= 1;

    if (scenario.id === "scene-4") {
      throw new Error("inference timeout");
    }
  });

  const result = await batch.run(scenarios);

  assert.equal(maximumInFlight, 1);
  assert.deepEqual(started, scenarios.map((scenario) => scenario.id));
  assert.deepEqual(result.items, [
    { scenarioId: "scene-1", status: "succeeded" },
    { scenarioId: "scene-2", status: "succeeded" },
    { scenarioId: "scene-3", status: "succeeded" },
    {
      scenarioId: "scene-4",
      status: "failed",
      failure: { message: "inference timeout" },
    },
    { scenarioId: "scene-5", status: "succeeded" },
    { scenarioId: "scene-6", status: "succeeded" },
    { scenarioId: "scene-7", status: "succeeded" },
    { scenarioId: "scene-8", status: "succeeded" },
    { scenarioId: "scene-9", status: "succeeded" },
    { scenarioId: "scene-10", status: "succeeded" },
  ]);
});

test("rejects a regression batch containing fewer than ten scenarios", async () => {
  const batch = new SequentialEvaluationBatch(async () => undefined);

  await assert.rejects(
    batch.run(scenarios.slice(0, 9)),
    /at least 10 scenarios/,
  );
});
