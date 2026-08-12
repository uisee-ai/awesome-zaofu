import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  DESKTOP_WORKBENCH_MIN_WIDTH,
  createDesktopWorkbench,
} from "../../web/src/features/browser-compat/desktop-layout.js";

test("desktop workbench exposes semantic core interactions at the supported 1280px width", () => {
  const workbench = createDesktopWorkbench();

  assert.equal(DESKTOP_WORKBENCH_MIN_WIDTH, 1280);
  assert.match(workbench.html, /data-testid="scene-library"/);
  assert.match(workbench.html, /data-testid="viewport"/);
  assert.match(workbench.html, /data-testid="run-inference"/);
  assert.match(workbench.html, /data-testid="run-status"/);
  assert.match(workbench.css, /grid-template-columns: 280px minmax\(0, 1fr\) 320px/);
  assert.match(workbench.css, /min-width: 1280px/);
});

test("browser runner loads the shared Studio URL without injecting page content", () => {
  const runner = readFileSync(
    new URL("../../e2e/browser-compat/desktop-layout.spec.ts", import.meta.url),
    "utf8",
  );
  const config = readFileSync(
    new URL("../../e2e/browser-compat/playwright.config.ts", import.meta.url),
    "utf8",
  );

  assert.doesNotMatch(runner, /page\.setContent/);
  assert.match(runner, /page\.goto\(["']\/["']\)/);
  assert.match(config, /process\.env\.ALPAMAYO_STUDIO_URL/);
  assert.match(config, /baseURL:\s*studioUrl/);
  assert.match(config, /name:\s*["']chromium["']/);
  assert.match(config, /name:\s*["']msedge["']/);
});
