import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const appRoot = resolve(import.meta.dirname, "../..");
const packageJson = JSON.parse(readFileSync(resolve(appRoot, "package.json"), "utf8"));
const contractManifest = JSON.parse(readFileSync(resolve(appRoot, "docs/contracts/scaffold-contract.v1.json"), "utf8"));
const contractSource = readFileSync(resolve(appRoot, "src/contracts/v1.ts"), "utf8");

function invariant(condition, message) {
  if (!condition) throw new Error(message);
}

const requiredScripts = {
  build: "vite build",
  "test:coordinates": "vitest run tests/spikes/coordinates.test.ts",
  "spike:coordinates": "node scripts/spikes/run-coordinate-spike.mjs",
  "spike:performance": "node scripts/spikes/run-performance-spike.mjs",
  "test:data-boundary": "vitest run tests/data-boundary",
  "test:nuscenes:race": "vitest run tests/nuscenes/frame-context-race.test.ts",
  "test:nuscenes": "vitest run tests/nuscenes",
  "verify:e2e-specs:nuscenes": "node scripts/scaffold/verify-e2e-spec.mjs nuscenes",
  "test:openlane": "vitest run tests/openlane",
  "verify:e2e-specs:openlane": "node scripts/scaffold/verify-e2e-spec.mjs openlane",
  "test:review": "vitest run tests/review/review.test.ts",
  "test:review:recovery": "vitest run tests/review/recovery.test.ts",
  "test:review:replay": "vitest run tests/review/replay.test.ts",
  "verify:e2e-specs:review": "node scripts/scaffold/verify-e2e-spec.mjs review",
  "e2e:synthetic": "playwright test tests/e2e/specs/synthetic.spec.ts",
  "e2e:nuscenes": "playwright test tests/e2e/specs/nuscenes.spec.ts",
  "e2e:openlane": "playwright test tests/e2e/specs/openlane.spec.ts",
  "verify:license": "node scripts/release/verify-license.mjs",
  "verify:evidence": "node scripts/release/verify-evidence.mjs",
};

for (const [name, command] of Object.entries(requiredScripts)) {
  invariant(packageJson.scripts[name] === command, `downstream command drifted or missing: ${name}`);
}

const featureSpecCommands = Object.keys(packageJson.scripts)
  .filter((name) => name.startsWith("verify:e2e-specs:"))
  .sort();
invariant(
  JSON.stringify(featureSpecCommands) ===
    JSON.stringify(["verify:e2e-specs:nuscenes", "verify:e2e-specs:openlane", "verify:e2e-specs:review"]),
  "exactly the three feature-owned E2E spec verification commands must be registered",
);
invariant(packageJson.scripts["verify:e2e-specs:synthetic"] === undefined, "synthetic spec belongs to assembly build/E2E");
invariant(packageJson.exports?.["./contracts"] === "./src/contracts/index.ts", "public contracts package export is missing");

for (const exportName of contractManifest.contract_exports) {
  const exportPattern = new RegExp(`export\\s+(?:const|function)\\s+${exportName}\\b`);
  invariant(exportPattern.test(contractSource), `declared runtime contract export is missing: ${exportName}`);
}

const packageNames = Object.keys({ ...packageJson.dependencies, ...packageJson.devDependencies });
for (const tool of ["playwright", "tsc", "vite", "vitest"]) {
  const declared = packageNames.some(
    (name) => name === tool || (tool === "playwright" && name === "@playwright/test") || (tool === "tsc" && name === "typescript"),
  );
  invariant(declared, `script tool is not package-resolvable: ${tool}`);
}

console.log(`verify:downstream-contracts passed: ${Object.keys(requiredScripts).length} canonical downstream commands and 3/3 feature specs`);
