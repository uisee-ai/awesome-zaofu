import { expect, test } from "@playwright/test";

const sixDemos = [
  "workbench",
  "navigation",
  "ablation",
  "vqa",
  "auto-label",
  "regression-judge",
] as const;

type PersistedRun = {
  runId: string;
  sceneId: string;
  sceneVersionId: string;
  status: string;
  result: {
    provider: string;
    responseSha256: string;
  };
};

type PersistedScene = {
  sceneId: string;
  sceneVersionId: string;
  name: string;
  status: string;
  sceneVersion: {
    visualInput: {
      assetRefs: string[];
    };
  };
};

function isPersistedRun(value: unknown): value is PersistedRun {
  return typeof value === "object"
    && value !== null
    && typeof (value as PersistedRun).runId === "string"
    && typeof (value as PersistedRun).sceneId === "string"
    && typeof (value as PersistedRun).sceneVersionId === "string"
    && typeof (value as PersistedRun).status === "string"
    && typeof (value as PersistedRun).result === "object"
    && (value as PersistedRun).result !== null
    && typeof (value as PersistedRun).result.provider === "string"
    && typeof (value as PersistedRun).result.responseSha256 === "string";
}

test.setTimeout(840_000);

test("one persisted scene can enter all six demos and submit inference", async ({ page }) => {

  const sceneResponse = await page.request.post("/api/scenes", {
    data: { name: "six-demo-browser-scene" },
  });
  expect(sceneResponse.ok()).toBe(true);
  const scene = await sceneResponse.json() as PersistedScene;
  expect(scene.sceneId).toMatch(/^scene-/);
  expect(scene.sceneVersionId).toMatch(/^scene-version-/);
  expect(scene.sceneVersionId).not.toBe(scene.sceneId);
  expect(scene.sceneVersion.visualInput.assetRefs).toHaveLength(16);

  for (const demo of sixDemos) {
      await page.goto(`/?demo=${demo}&sceneId=${encodeURIComponent(scene.sceneId)}`);
      await expect(page.getByTestId("scene-library")).toBeVisible();
      await expect(page.getByTestId("viewport")).toBeVisible();

      const submittedResponsePromise = page.waitForResponse((response) => {
        const request = response.request();
        return request.method() === "POST"
          && new URL(response.url()).pathname === `/api/scenes/${encodeURIComponent(scene.sceneId)}/runs`;
      });

      await page.getByTestId("run-inference").click();
      await expect(page.getByTestId("run-status")).toHaveText("Inference running");

      const submittedResponse = await submittedResponsePromise;
      expect(submittedResponse.ok()).toBe(true);
      const submitted = await submittedResponse.json() as { runId: string; status: string };
      expect(submitted.runId).toMatch(/^run-/);
      expect(submitted.status).toMatch(/^(queued|running|completed)$/);

      let saved: PersistedRun | undefined;
      await expect.poll(async () => {
        const response = await page.request.get(`/api/runs/${encodeURIComponent(submitted.runId)}`);
        const payload: unknown = await response.json();
        saved = isPersistedRun(payload) ? payload : undefined;
        return saved?.status;
      }, { timeout: 120_000, intervals: [250, 1_000] }).toBe("completed");
      expect(saved?.result).not.toBeNull();
      expect(saved).toBeDefined();
      const completedRun = saved!;
      expect(completedRun.runId).toBe(submitted.runId);
      expect(completedRun.sceneId).toBe(scene.sceneId);
      expect(completedRun.sceneVersionId).toBe(scene.sceneVersionId);
      expect(completedRun.result.provider).toBe("litellm");
      expect(completedRun.result.responseSha256).toMatch(/^[0-9a-f]{64}$/);
      expect(JSON.stringify({ submitted, completedRun })).not.toMatch(/authorization|secret|password|token|api[_-]?key/i);
      await expect(page.getByTestId("run-id")).toContainText(submitted.runId);
      await expect(page.getByTestId("run-status")).toContainText(`completed (${submitted.runId})`);
      await expect(page.getByTestId("run-result")).not.toBeEmpty();

      const persistedScene = await page.request.get(`/api/scenes/${encodeURIComponent(scene.sceneId)}`);
      expect(persistedScene.ok()).toBe(true);
      await expect(persistedScene.json()).resolves.toMatchObject({
        sceneId: scene.sceneId,
        sceneVersionId: scene.sceneVersionId,
        name: "six-demo-browser-scene",
        status: "ready",
        sceneVersion: {
          visualInput: { assetRefs: expect.any(Array) },
        },
      });
  }
});
