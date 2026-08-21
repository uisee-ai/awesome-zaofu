import { expect, test } from "@playwright/test";

test("creates and updates an append-only review after a recoverable interruption", async ({ page }) => {
  await page.goto("/?fixture=synthetic-review&fault=review-after-prepare");
  const panel = page.getByTestId("review-panel");

  await panel.getByLabel("问题代码").fill("MISALIGNED_BOX");
  await panel.getByRole("button", { name: "创建问题" }).click();
  await expect(panel.getByTestId("review-recovery-status")).toHaveText("已恢复完整写入");
  await expect(panel.getByTestId("review-revision")).toHaveText("revision 1");

  await panel.getByLabel("评论").fill("向车头方向平移 0.3m");
  await panel.getByRole("button", { name: "添加评论" }).click();
  await expect(panel.getByText("向车头方向平移 0.3m")).toBeVisible();
  await expect(panel.getByTestId("review-revision")).toHaveText("revision 2");
});

test("exports, reimports, and binds the browser receipt without duplication", async ({ page }) => {
  await page.goto("/?fixture=synthetic-review");
  const panel = page.getByTestId("review-panel");

  await panel.getByLabel("问题代码").fill("OCCLUDED");
  await panel.getByRole("button", { name: "创建问题" }).click();
  await panel.getByRole("button", { name: "导出差异" }).click();
  const archive = await panel.getByTestId("review-export-json").inputValue();
  expect(JSON.parse(archive)).toMatchObject({
    schema_version: "export-envelope.v1",
    media_included: false,
    absolute_paths_included: false,
  });

  await panel.getByLabel("导入差异").fill(archive);
  await panel.getByRole("button", { name: "导入差异" }).click();
  await expect(panel.getByTestId("review-import-status")).toHaveText("重复 1，新增 0");

  const receiptText = await panel.getByTestId("review-evidence-receipt").textContent();
  expect(receiptText).not.toBeNull();
  const receipt = JSON.parse(receiptText ?? "");
  expect(receipt).toMatchObject({
    command_id: "SWB-REVIEW-004-R3-CMD-04",
    runner: { name: "@playwright/test" },
    fixture: { kind: "synthetic" },
  });
  expect(receipt.source_commit).toMatch(/^[a-f0-9]{40}$/);
  expect(receipt.production_build_digest).toMatch(/^sha256:[a-f0-9]{64}$/);
  expect(receipt.fixture.digest).toMatch(/^sha256:[a-f0-9]{64}$/);
});
