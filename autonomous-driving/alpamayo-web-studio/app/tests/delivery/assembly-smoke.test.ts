import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";

const appRoot = new URL("../..", import.meta.url);

function read(relativePath: string): string {
  return readFileSync(new URL(relativePath, appRoot), "utf8");
}

test("the local Studio exposes one FastAPI root application with the PRD API surface", () => {
  const mainPath = new URL("backend/studio/app/main.py", appRoot);
  assert.equal(existsSync(mainPath), true);

  const main = read("backend/studio/app/main.py");
  assert.match(main, /app\s*=\s*FastAPI\(/);
  for (const [method, path] of [
    ["get", "/api/health"],
    ["get", "/api/model/status"],
    ["post", "/api/assets"],
    ["post", "/api/scenes"],
    ["get", "/api/scenes"],
    ["get", "/api/scenes/{scene_id}"],
    ["post", "/api/scenes/{scene_id}/runs"],
    ["get", "/api/runs/{run_id}"],
    ["post", "/api/runs/{run_id}/cancel"],
    ["post", "/api/runs/{run_id}/reviews"],
    ["post", "/api/experiments"],
    ["post", "/api/evaluation-sets"],
    ["post", "/api/evaluation-runs"],
  ]) {
    assert.match(main, new RegExp(`@app\\.${method}\\([\\s\\S]{0,120}${path.replace(/[{}]/g, "\\$&").replaceAll("/", "\\/")}`));
  }
});

test("local health verification and public responses keep credentials and payload data out of evidence", () => {
  const verifierPath = new URL("deploy/scripts/verify-local-studio.sh", appRoot);
  assert.equal(existsSync(verifierPath), true);

  const verifier = read("deploy/scripts/verify-local-studio.sh");
  const main = read("backend/studio/app/main.py");
  assert.match(verifier, /\/api\/health/);
  assert.match(verifier, /\[REDACTED\]/);
  assert.match(main, /REDACTED/);
  assert.doesNotMatch(main, /svc\.cluster\.local/);
  assert.doesNotMatch(main, /Authorization: Bearer/);
});

test("the Playwright Edge image installs Edge as root and runs tests without nested su", () => {
  const dockerfilePath = new URL("deploy/local/Dockerfile.playwright-edge", appRoot);
  assert.equal(existsSync(dockerfilePath), true);

  const dockerfile = read("deploy/local/Dockerfile.playwright-edge");
  assert.match(dockerfile, /npx playwright install msedge/);
  assert.match(dockerfile, /USER\s+pwuser/);
  assert.ok(dockerfile.indexOf("npx playwright install msedge") < dockerfile.indexOf("USER pwuser"));
  assert.doesNotMatch(dockerfile, /\bsu\b/);
});

test("the real Studio browser scenario uses the configured local URL and workbench selectors", () => {
  const configPath = new URL("e2e/studio/playwright.config.ts", appRoot);
  const scenarioPath = new URL("e2e/studio/golden-scene.spec.ts", appRoot);
  assert.equal(existsSync(configPath), true);
  assert.equal(existsSync(scenarioPath), true);

  const config = read("e2e/studio/playwright.config.ts");
  const scenario = read("e2e/studio/golden-scene.spec.ts");
  assert.match(config, /ALPAMAYO_STUDIO_URL/);
  assert.match(config, /baseURL:\s*studioUrl/);
  assert.match(scenario, /page\.goto\(["']\/["']\)/);
  assert.match(scenario, /run-inference/);
  assert.doesNotMatch(scenario, /page\.setContent/);
});
