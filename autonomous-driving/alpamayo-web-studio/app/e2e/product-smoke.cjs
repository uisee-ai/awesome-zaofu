const assert = require("node:assert/strict");
const { mkdirSync } = require("node:fs");
const { chromium } = require("/app/node_modules/playwright");

const baseUrl = process.env.ALPAMAYO_STUDIO_URL ?? "http://127.0.0.1:3000";
const evidenceDir = process.env.ALPAMAYO_EVIDENCE_DIR ?? "/work/artifacts";
const demos = ["workbench", "navigation", "ablation", "vqa", "auto-label", "regression-judge"];

async function runDemo(page, demo) {
  await page.locator(`[data-demo="${demo}"]`).click();
  await page.getByTestId("run-inference").click();
  await page.getByTestId("run-status").waitFor({ state: "visible" });
  await assertEventually(async () => (await page.getByTestId("run-status").textContent())?.trim() === "completed");
  await assertEventually(async () => (await page.getByTestId("run-result").textContent())?.includes("Chain of Causation"));
  if (demo === "ablation") {
    await assertEventually(async () => (await page.getByTestId("run-result").textContent())?.includes("Cameras 0, 1, 2, 6"));
  }
  if (demo === "auto-label") {
    await page.getByRole("button", { name: "Accept" }).click();
    await assertEventually(async () => page.evaluate(async () => {
      const runs = await fetch("/api/runs").then((response) => response.json());
      const autoLabel = runs.items.find((item) => item.demoId === "auto-label-studio");
      return autoLabel?.reviews?.some((review) => review.decision === "accepted");
    }));
  }
}

async function assertEventually(check, timeoutMs = 12_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await check()) return;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error("Condition did not become true before timeout");
}

(async () => {
  mkdirSync(evidenceDir, { recursive: true });
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || undefined,
  });
  try {
    const desktop = await browser.newContext({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1 });
    const page = await desktop.newPage();
    await page.goto(baseUrl, { waitUntil: "networkidle" });
    await assertEventually(async () => (await page.locator("h1").textContent()) === "Alpamayo Studio");

    if ((await page.locator(".scene-row").count()) === 0) {
      await page.locator(".create-scene-empty").click();
      await page.locator(".scene-row").first().waitFor();
    }

    const cameraPixels = await page.locator(".camera-grid img").evaluateAll((images) => images.map((image) => ({
      width: image.naturalWidth,
      height: image.naturalHeight,
    })));
    assert.equal(cameraPixels.length, 4);
    assert.ok(cameraPixels.every(({ width, height }) => width > 400 && height > 200));
    const cameraIds = await page.locator("[data-camera-id]").evaluateAll((items) =>
      items.map((item) => Number(item.getAttribute("data-camera-id"))),
    );
    assert.deepEqual(cameraIds, [0, 1, 2, 6]);
    assert.match((await page.locator(".timeline").textContent()) ?? "", /Frame 4\/4/);

    for (const demo of demos) await runDemo(page, demo);
    const recentRunLabels = await page.locator(".history-row").allTextContents();
    assert.ok(recentRunLabels.slice(0, 6).every((label) => !label.includes("inference")));

    const trajectoryPath = await page.getByTestId("trajectory-path").getAttribute("d");
    assert.ok(trajectoryPath && trajectoryPath.split("L").length === 64);
    await assertEventually(async () => (await page.getByTestId("run-result").textContent())?.includes("MAINTAIN LANE"));

    const runDemos = await page.evaluate(async () => {
      const scenes = await fetch("/api/scenes").then((response) => response.json());
      const sceneId = scenes.items[0].sceneId;
      const runs = await fetch(`/api/runs?sceneId=${encodeURIComponent(sceneId)}`).then((response) => response.json());
      return runs.items.map((run) => run.result?.demoId).filter(Boolean);
    });
    assert.deepEqual(new Set(runDemos), new Set([
      "scene-workbench",
      "navigation-lab",
      "camera-ablation",
      "scene-vqa",
      "auto-label-studio",
      "regression-judge",
    ]));

    await page.reload({ waitUntil: "networkidle" });
    await assertEventually(async () => (await page.getByTestId("run-status").textContent())?.trim() === "completed");
    await page.screenshot({ path: `${evidenceDir}/alpamayo-studio-desktop.png`, fullPage: true });
    await desktop.close();

    const mobile = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 1 });
    const mobilePage = await mobile.newPage();
    await mobilePage.goto(baseUrl, { waitUntil: "networkidle" });
    const overflow = await mobilePage.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    assert.ok(overflow <= 1, `mobile layout overflows horizontally by ${overflow}px`);
    assert.equal(await mobilePage.locator(".camera-grid img").count(), 4);
    await mobilePage.screenshot({ path: `${evidenceDir}/alpamayo-studio-mobile.png`, fullPage: true });
    await mobile.close();
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
