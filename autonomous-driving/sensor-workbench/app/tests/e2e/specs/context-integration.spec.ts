import { expect, test } from "@playwright/test";

const secondLaneRef = "openlane:validation/synthetic-segment/frame-0001.jpg#lane:102";

test("键盘选择 OpenLane 后，2D、3D 与 Review 使用同一稳定引用并保留可导入导出的本地历史", async ({ page }) => {
  await page.goto("/");

  const lane = page.getByRole("button", { name: "选择车道 102：yellow-solid" });
  await lane.focus();
  await page.keyboard.press("Enter");

  await expect(lane).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId("openlane-selection-status")).toHaveText(secondLaneRef);
  await expect(page.getByTestId("openlane-2d-selected-ref")).toHaveText(`${secondLaneRef}:2d`);
  await expect(page.getByTestId("openlane-3d-selected-ref")).toHaveText(`${secondLaneRef}:3d`);
  await expect(page.getByTestId("review-current-target")).toHaveText(`lane: ${secondLaneRef}`);

  const panel = page.getByTestId("review-panel");
  await panel.getByLabel("问题代码").fill("LANE_OCCLUDED");
  const create = panel.getByRole("button", { name: "创建问题" });
  await create.focus();
  await page.keyboard.press("Enter");
  await expect(panel.getByTestId("review-history")).toContainText("LANE_OCCLUDED");
  await expect(panel.getByTestId("review-event-target")).toHaveAttribute("data-target-ref", secondLaneRef);

  const exportDiff = panel.getByRole("button", { name: "导出差异" });
  await exportDiff.focus();
  await page.keyboard.press("Enter");
  const archive = await panel.getByTestId("review-export-json").inputValue();
  expect(JSON.parse(archive)).toMatchObject({
    media_included: false,
    absolute_paths_included: false,
    events: [{ target: { kind: "lane", stable_id: secondLaneRef } }],
  });

  await panel.getByLabel("导入差异").fill(archive);
  const importDiff = panel.getByRole("button", { name: "导入差异" });
  await importDiff.focus();
  await page.keyboard.press("Enter");
  await expect(panel.getByTestId("review-import-status")).toHaveText("重复 1，新增 0");
});
