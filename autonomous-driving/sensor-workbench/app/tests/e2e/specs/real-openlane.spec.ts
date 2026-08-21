import { expect, test } from "@playwright/test";

test("真实 OpenLane 演示帧提供图片、联动车道、筛选与清晰导航", async ({ page }) => {
  test.skip(!process.env.OPENLANE_DATA_ROOT, "需要显式配置只读 OpenLane 数据根");
  const nonLoopbackRequests: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (!["127.0.0.1", "localhost", "::1"].includes(url.hostname)) nonLoopbackRequests.push(request.url());
  });

  const manifestResponse = page.waitForResponse((response) => response.url().endsWith("/local-openlane/manifest"));
  const firstImageResponse = page.waitForResponse((response) => response.url().endsWith("/local-openlane/assets/0"));
  await page.goto("/");
  const manifest = await manifestResponse;
  expect(manifest.ok()).toBe(true);
  const manifestText = await manifest.text();
  expect(manifestText).not.toContain("/home/uisee");
  const manifestBody = JSON.parse(manifestText) as { frames: Array<{ frameRef: string }> };
  expect(manifestBody.frames).toHaveLength(10);
  expect(new Set(manifestBody.frames.map((frame) => frame.frameRef.split("/").at(-2))).size).toBe(5);
  const image = await firstImageResponse;
  expect(image.ok()).toBe(true);
  expect(image.headers()["content-type"]).toBe("image/jpeg");

  const panel = page.getByTestId("real-openlane-panel");
  await expect(panel).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("workbench-data-mode")).toHaveCount(0);
  await expect(page.getByText("本机单用户模式 · 所有数据请求仅限回环地址")).toHaveCount(0);
  await expect(page.getByTestId("workbench-data-source")).toHaveText(process.env.NUSCENES_DATA_ROOT ? "nuScenes + OpenLane" : "OpenLane");
  if (process.env.NUSCENES_DATA_ROOT) await expect(page.getByTestId("real-nuscenes-panel")).toBeVisible();
  await expect(panel.getByTestId("openlane-feature")).toHaveAttribute("data-mode", "local");
  await expect(panel.getByTestId("openlane-real-image")).toBeVisible();
  await expect(panel.getByTestId("openlane-2d-view").locator("polyline")).not.toHaveCount(0);
  await expect(panel.getByTestId("openlane-3d-view").locator("polyline")).not.toHaveCount(0);

  const lane = panel.locator('[data-testid^="openlane-lane-"]').first();
  await lane.click();
  const laneRef = await lane.getAttribute("data-lane-ref");
  await expect(panel.getByTestId("openlane-selection-status")).toHaveText(laneRef ?? "");
  await expect(lane).toHaveAttribute("aria-pressed", "true");
  await expect(panel.getByTestId("openlane-2d-view").locator(`polyline[data-lane-ref="${laneRef}"]`)).toHaveAttribute("data-selected", "true");

  const firstFrame = await panel.getByTestId("openlane-real-frame-ref").textContent();
  const nextImageResponse = page.waitForResponse((response) => response.url().endsWith("/local-openlane/assets/1"));
  await panel.getByRole("button", { name: "下一张" }).click();
  expect((await nextImageResponse).ok()).toBe(true);
  await expect.poll(() => panel.getByTestId("openlane-real-frame-ref").textContent()).not.toBe(firstFrame);
  await expect(panel.getByTestId("openlane-timeline-position")).toHaveText("第 2 / 10 张");
  await expect(panel.getByTestId("openlane-readonly-audit")).toHaveAttribute("data-unchanged", "true");
  expect(nonLoopbackRequests).toEqual([]);
});
