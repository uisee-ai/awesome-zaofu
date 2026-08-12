import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const appRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");

async function readJson(relativePath) {
  const content = await readFile(path.join(appRoot, relativePath), "utf8");
  return JSON.parse(content);
}

test("workspace exposes runnable web, build, lint, and test entry points", async () => {
  const packageJson = await readJson("package.json");

  assert.match(packageJson.scripts.dev, /next dev/);
  assert.match(packageJson.scripts.build, /next build/);
  assert.match(packageJson.scripts.start, /next start/);
  assert.match(packageJson.scripts.lint, /tsc --noEmit/);
  assert.match(packageJson.scripts.test, /tsx --test/);
});

test("workspace config keeps TypeScript and backend metadata explicit", async () => {
  const tsconfig = await readJson("tsconfig.json");
  const backendPyproject = await readFile(path.join(appRoot, "backend/pyproject.toml"), "utf8");

  assert.equal(tsconfig.compilerOptions.strict, true);
  assert.equal(tsconfig.compilerOptions.noEmit, true);
  assert.equal(tsconfig.compilerOptions.jsx, "react-jsx");
  assert.match(backendPyproject, /^\[project\]$/m);
  assert.match(backendPyproject, /^name = "alpamayo-studio-backend"$/m);
});
