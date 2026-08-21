import { expect, test } from "@playwright/test";

test("合成六帧演示可见呈现多模态视图、时间轴、筛选和带严重度的审核", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1100 });
  await page.goto("/");

  await page.getByTestId("frame-jump-sample-0001").click();
  const views = page.getByTestId("multimodal-views");
  await expect(views).toBeVisible();
  await expect(page.locator('[data-testid^="camera-view-"]')).toHaveCount(6);
  await expect(page.getByTestId("lidar-view")).toBeVisible();
  await expect(page.getByTestId("bev-view")).toBeVisible();
  await expect(page.getByTestId("projection-valid-count")).not.toHaveText("0");
  await expect(page.getByTestId("timeline-position")).toHaveText("1 / 6");

  await page.getByRole("button", { name: "下一帧" }).click();
  await expect(page.getByTestId("frame-context-id")).toHaveText("scene-0061:sample-0002:g2");
  await expect(page.getByTestId("timeline-position")).toHaveText("2 / 6");

  await page.getByTestId("instance-instance-vehicle-01").click();
  await expect(page.getByTestId("camera-box-CAM_FRONT")).toHaveAttribute("stroke", "#fbbf24");

  await page.getByTestId("openlane-category-filter").selectOption("2");
  await expect(page.getByTestId("openlane-filter-count")).toHaveText("1 条匹配车道");
  await expect(page.getByTestId("openlane-selected-ref")).toHaveText(/#lane:101$/);

  const review = page.getByTestId("review-panel");
  await review.getByLabel("问题代码").fill("MISALIGNED_BOX");
  await review.getByLabel("严重度").selectOption("high");
  await review.getByRole("button", { name: "创建问题" }).click();
  await expect(review.getByTestId("review-summary")).toHaveText("pending · high");
});
