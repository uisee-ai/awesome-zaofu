import { expect, test } from "@playwright/test";

test("1280px 中文三栏工作台以 synthetic 只读模式呈现，并让多视图和详情共享选择引用", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/");

  await expect(page.getByTestId("workbench-shell")).toBeVisible();
  await expect(page.getByRole("complementary", { name: "数据与导航" })).toBeVisible();
  await expect(page.getByRole("region", { name: "nuScenes 主视图" })).toBeVisible();
  await expect(page.getByRole("complementary", { name: "详情与审核" })).toBeVisible();
  await expect(page.getByTestId("workbench-data-source")).toHaveText("synthetic-only");
  await expect(page.getByTestId("workbench-readonly-status")).toHaveText("只读");

  await page.getByTestId("frame-jump-sample-0002").click();
  await page.getByTestId("instance-instance-vehicle-01").click();
  await expect(page.getByTestId("camera-selection")).toHaveAttribute("data-stable-ref", "instance-vehicle-01");
  await expect(page.getByTestId("lidar-selection")).toHaveAttribute("data-stable-ref", "instance-vehicle-01");
  await expect(page.getByTestId("bev-selection")).toHaveAttribute("data-stable-ref", "instance-vehicle-01");
  await expect(page.getByTestId("annotation-chain-selection")).toHaveAttribute("data-stable-ref", "instance-vehicle-01");
  await expect(page.getByTestId("workbench-detail-frame")).toHaveText("sample-0002");
  await expect(page.getByTestId("workbench-detail-instance")).toHaveText("instance-vehicle-01");

  const review = page.getByRole("complementary", { name: "详情与审核" }).getByTestId("review-panel");
  await expect(review).toBeVisible();
  await expect(review.getByTestId("review-current-frame-context")).toHaveText("scene-0061:sample-0002:g1");
  await expect(review.getByTestId("review-current-target")).toHaveText("annotation: instance-vehicle-01");

  await review.getByLabel("问题代码").fill("INSTANCE_OCCLUDED");
  await review.getByRole("button", { name: "创建问题" }).click();
  await expect(review.getByTestId("review-event-target")).toHaveAttribute("data-target-ref", "instance-vehicle-01");
  await review.getByRole("button", { name: "导出差异" }).click();
  const archive = await review.getByTestId("review-export-json").inputValue();
  expect(JSON.parse(archive)).toMatchObject({
    media_included: false,
    absolute_paths_included: false,
    events: [{
      frame_context_id: "scene-0061:sample-0002:g1",
      target: { kind: "annotation", stable_id: "instance-vehicle-01" },
    }],
  });
  expect(archive).not.toContain("/home/");
});
