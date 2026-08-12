import { defineConfig } from "@playwright/test";

const studioUrl = process.env.ALPAMAYO_STUDIO_URL;

if (!studioUrl) {
  throw new Error("ALPAMAYO_STUDIO_URL must point to the running Studio");
}

export default defineConfig({
  testDir: ".",
  fullyParallel: false,
  use: {
    baseURL: studioUrl,
    viewport: { width: 1280, height: 800 },
  },
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
});
