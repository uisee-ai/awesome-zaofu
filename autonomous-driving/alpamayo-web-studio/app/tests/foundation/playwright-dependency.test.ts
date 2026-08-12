import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";

const playwrightVersion = "1.62.1";
const require = createRequire(import.meta.url);

test("pins the Playwright test runner and resolves it for Chrome and Edge coverage", () => {
  const packageJson = JSON.parse(readFileSync(new URL("../../package.json", import.meta.url), "utf8")) as {
    devDependencies?: Record<string, string>;
  };
  const packageLock = JSON.parse(readFileSync(new URL("../../package-lock.json", import.meta.url), "utf8")) as {
    packages?: Record<string, { version?: string; devDependencies?: Record<string, string> }>;
  };

  assert.equal(packageJson.devDependencies?.["@playwright/test"], playwrightVersion);
  assert.equal(packageLock.packages?.[""]?.devDependencies?.["@playwright/test"], playwrightVersion);
  assert.equal(packageLock.packages?.["node_modules/@playwright/test"]?.version, playwrightVersion);
  assert.equal(require.resolve("@playwright/test/package.json").includes("node_modules/@playwright/test/package.json"), true);
});
