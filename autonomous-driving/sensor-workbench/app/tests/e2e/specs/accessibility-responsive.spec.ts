import { expect, test } from "@playwright/test";

test("窄屏提供桌面使用提示，nuScenes 操作可由键盘以语义名称完成", async ({ page }) => {
  await page.setViewportSize({ width: 1024, height: 768 });
  await page.goto("/");

  await expect(page.getByTestId("desktop-use-hint")).toBeVisible();
  const frame = page.getByRole("button", { name: "选择帧 sample-0002" });
  await frame.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("workbench-detail-frame")).toHaveText("sample-0002");

  const instance = page.getByRole("button", { name: "选择实例 instance-vehicle-01" });
  await instance.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("workbench-detail-instance")).toHaveText("instance-vehicle-01");
  await expect(page.getByTestId("workbench-selection-status")).toHaveText("已选择帧 sample-0002，实例 instance-vehicle-01");
});
