import assert from "node:assert/strict";
import test from "node:test";

import {
  InMemoryRegressionReportStore,
  RegressionReportService,
  type RegressionRun,
} from "../../backend/studio/judge/regression-report.js";
import { RegressionReportPanel } from "../../web/src/features/regression-report/regression-report-panel.js";

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

function successfulRun(overrides: Partial<RegressionRun>): RegressionRun {
  return {
    id: "run-default",
    sceneVersionId: "scene-default",
    status: "succeeded",
    durationMs: 100,
    model: { name: "alpamayo", version: "1.0.0", parameters: { temperature: 0.2, seed: 7 } },
    rawOutput: { requestId: "raw-default", result: "default" },
    output: {
      chainOfCausation: "道路通畅，保持车道。",
      metaAction: "保持车道",
      trajectory: trajectory(),
    },
    ...overrides,
  };
}

test("creates a traceable regression report with success, latency, CoC, action, trajectory and raw-output links", () => {
  const service = new RegressionReportService(new InMemoryRegressionReportStore());

  const report = service.compare({
    baseline: [
      successfulRun({ id: "baseline-1", sceneVersionId: "scene-1", durationMs: 100 }),
      successfulRun({ id: "baseline-2", sceneVersionId: "scene-2", durationMs: 300 }),
    ],
    candidate: [
      successfulRun({
        id: "candidate-1",
        sceneVersionId: "scene-1",
        durationMs: 150,
        model: { name: "alpamayo", version: "1.1.0", parameters: { temperature: 0.1, seed: 8 } },
        rawOutput: { requestId: "raw-candidate-1", result: "candidate" },
        output: {
          chainOfCausation: "道路通畅，因此保持车道。",
          metaAction: "保持车道",
          trajectory: trajectory(2),
        },
      }),
      successfulRun({
        id: "candidate-2",
        sceneVersionId: "scene-2",
        status: "failed",
        durationMs: 250,
        output: undefined,
        rawOutput: { requestId: "raw-candidate-2", error: "timeout" },
      }),
    ],
  });

  assert.deepEqual(report.summary.successRate, { baseline: 1, candidate: 0.5, delta: -0.5 });
  assert.deepEqual(report.summary.averageLatencyMs, { baseline: 200, candidate: 200, delta: 0 });
  assert.equal(report.scenes.length, 2);

  const scene = report.scenes.find((entry) => entry.sceneVersionId === "scene-1");
  assert.ok(scene);
  assert.ok(scene.coc);
  assert.ok(scene.metaAction);
  assert.ok(scene.provenance.candidate);
  assert.equal(scene.coc.changed, true);
  assert.equal(scene.metaAction.consistent, true);
  assert.deepEqual(scene.trajectory, { averagePointDifference: 2, endpointDifference: 2 });
  assert.deepEqual(scene.links, {
    scene: "/scenes/scene-1",
    baselineRawOutput: "/runs/baseline-1/raw-output",
    candidateRawOutput: "/runs/candidate-1/raw-output",
  });
  assert.equal(scene.provenance.baseline.model.version, "1.0.0");
  assert.deepEqual(scene.provenance.candidate.model.parameters, { temperature: 0.1, seed: 8 });

  const failed = report.scenes.find((entry) => entry.sceneVersionId === "scene-2");
  assert.ok(failed);
  assert.ok(failed.candidate);
  assert.equal(failed.candidate.status, "failed");
  assert.equal(failed.trajectory, null);
  assert.equal(failed.links.candidateRawOutput, "/runs/candidate-2/raw-output");
});

test("keeps human Judge decisions separate from immutable model outputs and exposes report navigation", () => {
  const service = new RegressionReportService(new InMemoryRegressionReportStore());
  const report = service.compare({
    baseline: [successfulRun({ id: "baseline", sceneVersionId: "scene-1" })],
    candidate: [successfulRun({ id: "candidate", sceneVersionId: "scene-1" })],
  });
  const panel = new RegressionReportPanel(service, report.id);

  const panelScene = panel.snapshot().scenes[0];
  assert.ok(panelScene);
  assert.equal(panelScene.links.scene, "/scenes/scene-1");
  assert.equal(panel.navigateToRawOutput("scene-1", "candidate"), "/runs/candidate/raw-output");

  const judged = panel.submitJudge({
    sceneVersionId: "scene-1",
    verdict: "approved",
    reviewerId: "reviewer-7",
    note: "可作为发布基线。",
    judgedAt: "2026-08-10T00:00:00.000Z",
  });

  assert.deepEqual(judged, {
    sceneVersionId: "scene-1",
    verdict: "approved",
    reviewerId: "reviewer-7",
    note: "可作为发布基线。",
    judgedAt: "2026-08-10T00:00:00.000Z",
  });
  assert.equal(service.get(report.id)?.scenes[0]?.candidate?.rawOutput.requestId, "raw-default");
  assert.deepEqual(panel.snapshot().scenes[0]?.judgeDecisions, [judged]);
});
