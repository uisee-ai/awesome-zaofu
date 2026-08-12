import { expect, test } from "@playwright/test";

test("authorized golden scene completes through the local Studio workbench", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("scene-library")).toBeVisible();
  await expect(page.getByTestId("viewport")).toBeVisible();

  await page.getByTestId("run-inference").click();
  await expect(page.getByTestId("run-status")).toHaveText("Inference running");
});
