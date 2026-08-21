import { expect, test } from "@playwright/test";

test("真实 nuScenes mini 显示六路相机、LiDAR、BEV、时间轴和标注，且请求保持 loopback", async ({ page }) => {
  test.skip(!process.env.NUSCENES_DATA_ROOT, "需要显式配置只读 nuScenes 数据根");
  const nonLoopbackRequests: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (!["127.0.0.1", "localhost", "::1"].includes(url.hostname)) nonLoopbackRequests.push(request.url());
  });

  const manifestResponse = page.waitForResponse((response) => response.url().endsWith("/local-nuscenes/manifest"));
  await page.goto("/");
  const manifest = await manifestResponse;
  expect(manifest.ok()).toBe(true);
  expect(await manifest.text()).not.toContain("/home/uisee");

  await expect(page.getByTestId("real-nuscenes-panel")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("workbench-data-mode")).toHaveText("本地真实数据");
  await expect(page.getByTestId("workbench-data-source")).toHaveText("local-nuscenes");
  await expect(page.locator('[data-testid^="camera-view-"]')).toHaveCount(6);
  await expect(page.getByTestId("real-camera-count")).toHaveText("6");

  const images = page.locator('[data-testid^="camera-view-"] img');
  await expect(images).toHaveCount(6);
  await expect.poll(async () => images.evaluateAll((items) => items.every((item) => {
    const image = item as HTMLImageElement;
    return image.complete && image.naturalWidth > 0 && image.naturalHeight > 0;
  })), { timeout: 30_000 }).toBe(true);

  await expect(page.getByTestId("lidar-view")).toBeVisible();
  await expect(page.getByTestId("bev-view")).toBeVisible();
  await expect.poll(async () => Number(await page.getByTestId("real-point-count").textContent()), { timeout: 30_000 }).toBeGreaterThan(0);
  await expect.poll(async () => Number(await page.getByTestId("real-annotation-count").textContent())).toBeGreaterThan(0);

  const view = page.getByTestId("multimodal-views");
  const firstFrame = await view.getAttribute("data-frame-context-id");
  await page.getByRole("button", { name: "下一帧" }).click();
  await expect.poll(() => view.getAttribute("data-frame-context-id")).not.toBe(firstFrame);
  await expect(page.getByTestId("timeline-position")).toContainText("2 /");
  expect(nonLoopbackRequests).toEqual([]);
});
