import assert from "node:assert/strict";
import test from "node:test";

import {
  InMemorySceneVqaPersistence,
  SceneVqaService,
  VQA_QUESTION_TEMPLATES,
} from "../../backend/studio/vqa/scene-vqa-service.js";
import { createSceneVqaController } from "../../web/src/features/vqa/scene-vqa-controller.js";

test("accepts template and free-form questions for one or multiple cameras as independent results", () => {
  const service = new SceneVqaService(new InMemorySceneVqaPersistence(), (request) => ({
    answer: `回答：${request.question}`,
    generationParameters: { temperature: 0.2, maxTokens: 256 },
  }));

  const templateResult = service.submit({
    sceneVersionId: "scene-version-1",
    cameraIds: [0],
    question: VQA_QUESTION_TEMPLATES[0],
  });
  const freeFormResult = service.submit({
    sceneVersionId: "scene-version-1",
    cameraIds: [0, 1, 2, 6],
    question: "右侧车道是否存在并线风险？",
  });

  assert.notEqual(templateResult.id, freeFormResult.id);
  assert.deepEqual(templateResult.cameraIds, [0]);
  assert.deepEqual(freeFormResult.cameraIds, [0, 1, 2, 6]);
  assert.equal(templateResult.answer, `回答：${VQA_QUESTION_TEMPLATES[0]}`);
  assert.equal(freeFormResult.question, "右侧车道是否存在并线风险？");
  assert.deepEqual(service.list("scene-version-1").map((result) => result.id), [templateResult.id, freeFormResult.id]);
});

test("copies and exports every VQA answer separately, while ratings and remarks persist after refresh", () => {
  const persistence = new InMemorySceneVqaPersistence();
  const firstService = new SceneVqaService(persistence, () => ({
    answer: "前方路口有一辆减速的车辆。",
    generationParameters: { temperature: 0, maxTokens: 64 },
  }));
  const result = firstService.submit({
    sceneVersionId: "scene-version-2",
    cameraIds: [1, 6],
    question: "哪个交通参与者最需要关注？",
  });

  const reviewed = firstService.review(result.id, {
    rating: "partially_correct",
    remark: "需要补充右侧盲区风险。",
  });
  assert.equal(firstService.copyAnswer(result.id), "前方路口有一辆减速的车辆。");
  assert.deepEqual(JSON.parse(firstService.exportResult(result.id)), reviewed);

  const refreshedService = new SceneVqaService(persistence, () => {
    throw new Error("refresh must not submit another question");
  });
  assert.deepEqual(refreshedService.get(result.id), reviewed);
});

test("the web controller submits through its Studio Backend gateway and exposes independent copy/export actions", async () => {
  const requested: string[] = [];
  const result = {
    id: "vqa-1",
    sceneVersionId: "scene-version-3",
    cameraIds: [0],
    question: "前方是否有行人或障碍物？",
    answer: "没有。",
    generationParameters: { temperature: 0.2, maxTokens: 256 },
    rating: null,
    remark: "",
  };
  const controller = createSceneVqaController({
    submit: async (input) => {
      requested.push(`submit:${input.question}`);
      return result;
    },
    copyAnswer: async (resultId) => {
      requested.push(`copy:${resultId}`);
      return result.answer;
    },
    exportResult: async (resultId) => {
      requested.push(`export:${resultId}`);
      return JSON.stringify(result);
    },
    review: async (resultId, review) => {
      requested.push(`review:${resultId}:${review.rating}:${review.remark}`);
      return { ...result, rating: review.rating, remark: review.remark };
    },
  });

  await controller.submit({
    sceneVersionId: "scene-version-3",
    cameraIds: [0],
    question: result.question,
  });
  assert.equal(await controller.copyAnswer("vqa-1"), "没有。");
  assert.equal(await controller.exportResult("vqa-1"), JSON.stringify(result));
  assert.deepEqual(
    await controller.review("vqa-1", { rating: "correct", remark: "回答与画面一致。" }),
    { ...result, rating: "correct", remark: "回答与画面一致。" },
  );
  assert.deepEqual(requested, [
    "submit:前方是否有行人或障碍物？",
    "copy:vqa-1",
    "export:vqa-1",
    "review:vqa-1:correct:回答与画面一致。",
  ]);
  assert.equal(controller.state.phase, "ready");
});
