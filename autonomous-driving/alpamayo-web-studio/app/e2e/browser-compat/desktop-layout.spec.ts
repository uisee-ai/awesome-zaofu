import { expect, test } from "@playwright/test";

test("@desktop-1280 keeps the desktop workbench visible and interactive", async ({ page }) => {
  await page.goto("/");

  const sceneLibrary = page.getByTestId("scene-library");
  const viewport = page.getByTestId("viewport");
  const runButton = page.getByTestId("run-inference");

  await expect(sceneLibrary).toBeVisible();
  await expect(viewport).toBeVisible();
  await expect(runButton).toBeVisible();
  await expect(sceneLibrary).toHaveCSS("min-width", "0px");

  const viewportBox = await viewport.boundingBox();
  expect(viewportBox?.width).toBeGreaterThanOrEqual(600);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);

  await runButton.click();
  await expect(page.getByTestId("run-status")).toHaveText("Inference running");
});
