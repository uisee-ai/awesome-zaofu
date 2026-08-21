import { expect, test } from "@playwright/test";

function isLoopbackRequest(rawUrl: string): boolean {
  const url = new URL(rawUrl);
  return !["http:", "https:", "ws:", "wss:"].includes(url.protocol) || ["127.0.0.1", "localhost", "::1"].includes(url.hostname);
}

test("production entry completes dual-adapter browse, review history, export, and reimport without external requests", async ({ page }) => {
  const nonLoopbackRequests: string[] = [];
  page.on("request", (request) => {
    if (!isLoopbackRequest(request.url())) nonLoopbackRequests.push(request.url());
  });

  await page.goto("/?fixture=synthetic-review");
  await expect(page.getByTestId("sensor-workbench-production-entry")).toBeVisible();

  await page.getByTestId("adapter-nuscenes").click();
  await page.getByTestId("frame-jump-sample-0002").click();
  await expect(page.getByTestId("frame-context-id")).toHaveText("scene-0061:sample-0002:g1");
  await page.getByTestId("instance-instance-vehicle-01").click();
  await expect(page.getByTestId("bev-selection")).toHaveAttribute("data-stable-ref", "instance-vehicle-01");

  await page.getByTestId("openlane-lane-102").click();
  await expect(page.getByTestId("openlane-2d-selected-ref")).toHaveText(/#lane:102:2d$/);
  await expect(page.getByTestId("openlane-3d-selected-ref")).toHaveText(/#lane:102:3d$/);
  await expect(page.getByTestId("openlane-readonly-audit")).toHaveAttribute("data-unchanged", "true");

  const panel = page.getByTestId("review-panel");
  await panel.getByLabel("问题代码").fill("OCCLUDED");
  await panel.getByRole("button", { name: "创建问题" }).click();
  await panel.getByRole("button", { name: "导出差异" }).click();
  const archive = await panel.getByTestId("review-export-json").inputValue();
  await panel.getByLabel("导入差异").fill(archive);
  await panel.getByRole("button", { name: "导入差异" }).click();
  await expect(panel.getByTestId("review-import-status")).toHaveText("重复 1，新增 0");

  const receipt = JSON.parse(await page.getByTestId("openlane-evidence-receipt").textContent() ?? "{}");
  expect(receipt).toMatchObject({
    command_id: "SWB-ASSEMBLY-005-R3-CMD-04",
    network: { loopback_only: true, non_loopback_requests: [] },
    result: "passed",
  });
  expect(nonLoopbackRequests).toEqual([]);
});
