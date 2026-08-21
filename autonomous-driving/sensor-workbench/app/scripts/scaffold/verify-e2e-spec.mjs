import { readFileSync, statSync } from "node:fs";
import { resolve } from "node:path";

const allowedFeatures = new Set(["nuscenes", "openlane", "review"]);
const feature = process.argv[2];

if (!allowedFeatures.has(feature)) {
  throw new Error(`expected one of ${[...allowedFeatures].join(", ")}`);
}

const appRoot = resolve(import.meta.dirname, "../..");
const specPath = resolve(appRoot, `tests/e2e/specs/${feature}.spec.ts`);
if (!statSync(specPath).isFile()) throw new Error(`feature E2E spec is missing: ${specPath}`);

const source = readFileSync(specPath, "utf8");
if (!source.includes("@playwright/test")) throw new Error(`${feature} spec must use the real Playwright runner`);
if (!source.includes("test(")) throw new Error(`${feature} spec must declare at least one browser test`);

console.log(`verify:e2e-specs:${feature} passed: ${specPath}`);
