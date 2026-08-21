import { expect, test } from "@playwright/test";

const fixtureDigest = "sha256:f63d05a3772587bc3cbc80091d62ed538bb5f885025eebc127677c512dc302f6";
const secondLaneRef = "openlane:validation/synthetic-segment/frame-0001.jpg#lane:102";

function isLoopbackRequest(rawUrl: string): boolean {
  const url = new URL(rawUrl);
  if (!["http:", "https:", "ws:", "wss:"].includes(url.protocol)) return true;
  return url.hostname === "127.0.0.1" || url.hostname === "localhost" || url.hostname === "::1";
}

test("OpenLane V1.2 links one lane across 2D/3D and preserves the read-only evidence boundary", async ({ page }) => {
  const nonLoopbackRequests: string[] = [];
  page.on("request", (request) => {
    if (!isLoopbackRequest(request.url())) nonLoopbackRequests.push(request.url());
  });

  await page.goto("/openlane");
  const feature = page.getByTestId("openlane-feature");
  await expect(feature).toBeVisible();
  await expect(feature).toHaveAttribute("data-dataset-version", "v1.2");
  await expect(feature).toHaveAttribute("data-fixture-digest", fixtureDigest);
  await expect(page.getByTestId("openlane-license-notice")).toContainText("Non-commercial use only");

  await page.getByTestId("openlane-lane-102").click();
  await expect(page.getByTestId("openlane-selected-ref")).toHaveText(secondLaneRef);
  await expect(page.getByTestId("openlane-2d-selected-ref")).toHaveText(`${secondLaneRef}:2d`);
  await expect(page.getByTestId("openlane-3d-selected-ref")).toHaveText(`${secondLaneRef}:3d`);
  await expect(page.getByTestId("openlane-category")).toHaveText("8: yellow-solid");
  await expect(page.getByTestId("openlane-attribute")).toHaveText("3: right");
  await expect(page.getByTestId("openlane-visibility")).toHaveText("1, 0.5, 0");
  await expect(page.getByTestId("openlane-points-2d")).toHaveText("[[1120,700],[1090,620],[1050,560]]");
  await expect(page.getByTestId("openlane-points-3d")).toHaveText("[[5,-2.5,0],[10,-2.25,0.1],[15,-2,0.2]]");

  const dataRootBeforeDigest = await page.getByTestId("openlane-data-root-before").textContent();
  const dataRootAfterDigest = await page.getByTestId("openlane-data-root-after").textContent();
  expect(dataRootBeforeDigest).toBe(fixtureDigest);
  expect(dataRootAfterDigest).toBe(dataRootBeforeDigest);
  await expect(page.getByTestId("openlane-readonly-audit")).toHaveAttribute("data-unchanged", "true");
  await expect(page.getByTestId("openlane-media-included")).toHaveText("false");
  await expect(page.getByTestId("openlane-absolute-paths-included")).toHaveText("false");
  expect(nonLoopbackRequests).toEqual([]);

  const receiptText = await page.locator('script[data-testid="openlane-evidence-receipt"]').textContent();
  expect(receiptText).not.toBeNull();
  const receipt = JSON.parse(receiptText ?? "null") as Record<string, any>;
  expect(Object.keys(receipt)).toEqual([
    "schema_version",
    "receipt_id",
    "command_id",
    "source_commit",
    "production_build_digest",
    "runner",
    "browser",
    "fixture",
    "started_at",
    "finished_at",
    "exit_status",
    "exit_code",
    "data_root_before_digest",
    "data_root_after_digest",
    "artifacts",
    "network",
    "result",
  ]);
  expect(receipt.schema_version).toBe("evidence-receipt.v1");
  expect(receipt.command_id).toBe("SWB-ASSEMBLY-005-R3-CMD-04");
  expect(receipt.source_commit).toMatch(/^[0-9a-f]{40}$/);
  expect(receipt.production_build_digest).toMatch(/^sha256:[0-9a-f]{64}$/);
  expect(receipt.runner).toMatchObject({ name: "@playwright/test" });
  expect(receipt.browser.name).toBeTruthy();
  expect(receipt.browser.version).toBeTruthy();
  expect(receipt.fixture).toEqual({ kind: "openlane", digest: fixtureDigest });
  expect(Date.parse(receipt.started_at)).not.toBeNaN();
  expect(Date.parse(receipt.finished_at)).not.toBeNaN();
  expect(receipt.exit_status).toBe("passed");
  expect(receipt.exit_code).toBe(0);
  expect(receipt.data_root_before_digest).toBe(dataRootBeforeDigest);
  expect(receipt.data_root_after_digest).toBe(dataRootAfterDigest);
  expect(receipt.artifacts.length).toBeGreaterThan(0);
  expect(receipt.artifacts.every((artifact: Record<string, unknown>) => artifact.redacted === true)).toBe(true);
  expect(receipt.network).toEqual({ loopback_only: true, non_loopback_requests: [] });
  expect(receipt.result).toBe("passed");
});
