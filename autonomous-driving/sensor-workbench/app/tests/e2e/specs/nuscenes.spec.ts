import { expect, test } from "@playwright/test";

test("nuScenes feature binds race, linkage, search, safety, readonly and AC-14 evidence", async ({ page }) => {
  const nonLoopbackRequests: string[] = [];
  page.on("request", (request) => {
    const host = new URL(request.url()).hostname;
    if (host !== "127.0.0.1" && host !== "localhost" && host !== "::1") nonLoopbackRequests.push(request.url());
  });

  await page.goto("/");
  await page.getByTestId("adapter-nuscenes").click();
  await page.getByTestId("frame-jump-sample-0001").click();
  await page.getByTestId("frame-jump-sample-0002").click();
  await expect(page.getByTestId("frame-context-id")).toHaveText("scene-0061:sample-0002:g2");
  await expect(page.getByTestId("sensor-delta-CAM_FRONT")).toHaveText("10 ms");

  await page.getByTestId("instance-instance-vehicle-01").click();
  for (const view of ["camera", "lidar", "bev", "annotation-chain"]) {
    await expect(page.getByTestId(`${view}-selection`)).toHaveAttribute("data-stable-ref", "instance-vehicle-01");
  }

  await page.getByTestId("scene-search").fill("depot");
  await page.getByTestId("filter-weather-rain").check();
  await expect(page.getByTestId("search-result-scene-0061-sample-0001")).toContainText("Night rain near depot");
  await expect(page.getByTestId("search-result-scene-0061-sample-0001")).toHaveAttribute(
    "data-rule-version",
    "scene-derivation.v1",
  );

  await expect(page.getByTestId("data-boundary-status")).toHaveAttribute("data-absolute-paths-included", "false");
  const afterDigest = await page.getByTestId("data-root-digest-after").textContent();
  expect(afterDigest).not.toBeNull();
  await expect(page.getByTestId("data-root-digest-before")).toHaveText(afterDigest ?? "");
  await expect(page.getByTestId("point-cloud-metrics")).toHaveAttribute("data-worker", "true");
  await expect(page.getByTestId("point-cloud-metrics")).toHaveAttribute("data-lod", "2");
  await expect(page.getByTestId("point-cloud-metrics")).toHaveAttribute("data-max-chunk-bytes", "8388608");
  await expect(page.getByTestId("cache-metrics")).toHaveAttribute("data-hard-limit", "true");
  await expect(page.getByTestId("cache-metrics")).toHaveAttribute("data-eviction-policy", "lru");
  expect(nonLoopbackRequests).toEqual([]);
});
