import assert from "node:assert/strict";
import test from "node:test";

import {
  InMemoryWorkbenchRunPersistence,
  WorkbenchRunService,
  type WorkbenchInferenceOutput,
} from "../../../backend/studio/workbench-runs/workbench-run-service.js";
import {
  WorkbenchResultsPanel,
  type WorkbenchResultsClient,
} from "../../../web/src/features/workbench-results/workbench-results-panel.js";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((fulfil) => { resolve = fulfil; });
  return { promise, resolve };
}

const output: WorkbenchInferenceOutput = {
  vqaAnswer: "前方车道畅通。",
  chainOfCausation: "检测到前方车辆保持稳定间距，因此维持当前车道。",
  metaAction: "保持车道并平稳前行。",
};

function clientFor(service: WorkbenchRunService): WorkbenchResultsClient {
  return {
    submit: (configuration) => service.submit(configuration),
    get: (runId) => service.get(runId),
  };
}

test("submits configured workbench runs and exposes queued, running, and completed status", async () => {
  const inference = deferred<WorkbenchInferenceOutput>();
  const service = new WorkbenchRunService(new InMemoryWorkbenchRunPersistence(), () => inference.promise);
  const panel = new WorkbenchResultsPanel(clientFor(service));

  const queued = await panel.submit({ model: "alpamayo-v2", parameters: { temperature: 0.2 }, seed: 7 });
  assert.equal(queued.status.status, "queued");
  assert.equal(queued.status.label, "等待中");

  await Promise.resolve();
  const running = await panel.refresh(queued.runId);
  assert.equal(running?.status.status, "running");
  assert.equal(running?.status.label, "运行中");

  inference.resolve(output);
  await service.whenSettled(queued.runId);
  const completed = await panel.refresh(queued.runId);
  assert.deepEqual(completed?.status, { status: "succeeded", label: "已成功", tone: "success" });
});

test("allows CoC and Meta Action to be expanded and copied from a completed result", async () => {
  const service = new WorkbenchRunService(new InMemoryWorkbenchRunPersistence(), async () => output);
  const panel = new WorkbenchResultsPanel(clientFor(service));

  const submitted = await panel.submit({ model: "alpamayo-v2", parameters: {}, seed: 8 });
  await service.whenSettled(submitted.runId);
  await panel.refresh(submitted.runId);

  assert.equal(panel.snapshot().details.chainOfCausation.expanded, false);
  assert.equal(panel.toggleDetails("chainOfCausation").expanded, true);
  assert.equal(panel.copyDetails("chainOfCausation"), output.chainOfCausation);
  assert.equal(panel.toggleDetails("metaAction").expanded, true);
  assert.equal(panel.copyDetails("metaAction"), output.metaAction);
});

test("restores completed results after refresh and creates a new immutable record when rerun", async () => {
  const persistence = new InMemoryWorkbenchRunPersistence();
  const firstService = new WorkbenchRunService(persistence, async () => output);
  const firstPanel = new WorkbenchResultsPanel(clientFor(firstService));

  const first = await firstPanel.submit({ model: "alpamayo-v2", parameters: { mode: "safe" }, seed: 9 });
  await firstService.whenSettled(first.runId);

  const reloadedService = new WorkbenchRunService(persistence, async () => ({ ...output, metaAction: "减速观察。" }));
  const reloadedPanel = new WorkbenchResultsPanel(clientFor(reloadedService));
  const restored = await reloadedPanel.refresh(first.runId);
  assert.equal(restored?.details.metaAction.value, output.metaAction);

  const rerun = await reloadedPanel.submit({ model: "alpamayo-v2", parameters: { mode: "safe" }, seed: 9 });
  await reloadedService.whenSettled(rerun.runId);
  assert.notEqual(rerun.runId, first.runId);
  assert.equal((await reloadedService.get(first.runId))?.output?.metaAction, output.metaAction);
  assert.equal((await reloadedService.list()).length, 2);
});
