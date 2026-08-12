import assert from "node:assert/strict";
import test from "node:test";

import {
  AutoLabelService,
  InMemoryAutoLabelPersistence,
} from "../../backend/studio/labels/auto-label-service.js";
import { AutoLabelStudioController } from "../../web/src/features/labels/auto-label-studio-controller.js";

const candidates = {
  roadStructure: ["城市十字路口"],
  trafficParticipants: ["前方轿车", "右侧行人"],
  potentialRisks: ["行人进入车道"],
  navigationIntent: ["右转"],
  metaAction: ["减速让行"],
  longTailSceneType: ["施工区域旁的混合交通"],
};

test("creates all six candidate label categories while preserving the model raw output", () => {
  const controller = new AutoLabelStudioController(new AutoLabelService(new InMemoryAutoLabelPersistence()));
  const annotation = controller.generate({
    sceneId: "scene-17",
    modelVersion: "alpamayo-v2.1",
    rawModelOutput: { chainOfCausation: "前方行人接近斑马线，车辆应减速。", candidates },
  });

  assert.deepEqual(annotation.candidateLabels, candidates);
  assert.deepEqual(annotation.rawModelOutput, {
    chainOfCausation: "前方行人接近斑马线，车辆应减速。",
    candidates,
  });
  assert.equal(annotation.reviewStatus, "pending");
});

test("records accept, modification, and rejection reviews without overwriting raw output", () => {
  const service = new AutoLabelService(new InMemoryAutoLabelPersistence(), () => new Date("2026-08-10T05:40:00.000Z"));
  const controller = new AutoLabelStudioController(service);
  const annotation = controller.generate({ sceneId: "scene-review", modelVersion: "alpamayo-v2.1", rawModelOutput: { candidates } });

  const accepted = controller.review(annotation.id, { decision: "accepted", actor: "reviewer-a" });
  const modified = controller.review(annotation.id, {
    decision: "modified",
    actor: "reviewer-b",
    labels: { ...candidates, metaAction: ["停车观察"] },
    cocSummary: "修改为更保守的停车观察。",
  });
  const rejected = controller.review(annotation.id, { decision: "rejected", actor: "reviewer-c" });

  assert.equal(accepted.reviewStatus, "accepted");
  assert.equal(modified.reviewStatus, "modified");
  assert.equal(rejected.reviewStatus, "rejected");
  assert.deepEqual(rejected.rawModelOutput, { candidates });
  assert.deepEqual(rejected.candidateLabels, candidates);
  assert.equal(rejected.reviews.length, 3);
  assert.deepEqual(rejected.reviews.map((review) => review.actor), ["reviewer-a", "reviewer-b", "reviewer-c"]);
  assert.deepEqual(rejected.reviews.map((review) => review.at), [
    "2026-08-10T05:40:00.000Z",
    "2026-08-10T05:40:00.000Z",
    "2026-08-10T05:40:00.000Z",
  ]);
  assert.deepEqual(rejected.reviews[1]?.changes, {
    labels: { metaAction: { before: ["减速让行"], after: ["停车观察"] } },
    cocSummary: { before: undefined, after: "修改为更保守的停车观察。" },
  });
});

test("filters annotations and exports JSONL records with scene, model, and review status", () => {
  const service = new AutoLabelService(new InMemoryAutoLabelPersistence(), () => new Date("2026-08-10T06:00:00.000Z"));
  const controller = new AutoLabelStudioController(service);
  const pending = controller.generate({ sceneId: "scene-pending", modelVersion: "alpamayo-v2.1", rawModelOutput: { candidates } });
  const accepted = controller.generate({ sceneId: "scene-accepted", modelVersion: "alpamayo-v2.2", rawModelOutput: { candidates } });
  controller.review(accepted.id, { decision: "accepted", actor: "reviewer" });

  assert.deepEqual(controller.filter({ reviewStatus: "pending", tag: "右转" }).map((item) => item.id), [pending.id]);
  assert.deepEqual(controller.filter({ modelVersion: "alpamayo-v2.2", from: "2026-08-10T05:59:59.000Z" }).map((item) => item.id), [accepted.id]);

  const lines = controller.exportJsonl({ reviewStatus: "accepted" }).trim().split("\n");
  assert.equal(lines.length, 1);
  assert.deepEqual(JSON.parse(lines[0]!), {
    sceneId: "scene-accepted",
    modelVersion: "alpamayo-v2.2",
    reviewStatus: "accepted",
    candidateLabels: candidates,
    reviewedLabels: candidates,
  });
});
