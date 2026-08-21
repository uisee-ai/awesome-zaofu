import { defineConfig } from "@playwright/test";

const evidenceRoot = process.env.SWB_EVIDENCE_RUN_ROOT;
if (!evidenceRoot) throw new Error("SWB_EVIDENCE_RUN_ROOT is required");

export default defineConfig({
  testDir: "../specs",
  outputDir: `${evidenceRoot}/test-results`,
  fullyParallel: false,
  forbidOnly: true,
  retries: 0,
  workers: 1,
  reporter: [["list"], ["json", { outputFile: `${evidenceRoot}/playwright-result.json` }]],
  use: {
    baseURL: "http://127.0.0.1:4273",
    browserName: "chromium",
    trace: "on",
    screenshot: "only-on-failure",
    contextOptions: {
      recordHar: {
        path: `${evidenceRoot}/network.har`,
        content: "omit",
        mode: "full",
      },
    },
  },
  webServer: {
    command: "node production-server.mjs",
    url: "http://127.0.0.1:4273",
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
