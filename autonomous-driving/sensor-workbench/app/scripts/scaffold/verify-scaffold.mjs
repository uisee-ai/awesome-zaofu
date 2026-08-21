import { readFileSync, statSync } from "node:fs";
import { resolve } from "node:path";

const appRoot = resolve(import.meta.dirname, "../..");
const repositoryRoot = resolve(appRoot, "..");
const manifestPath = resolve(appRoot, "docs/contracts/scaffold-contract.v1.json");
const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
const productSpec = readFileSync(resolve(repositoryRoot, "docs/product/sensor-workbench-mvp-prd.md"), "utf8");

function invariant(condition, message) {
  if (!condition) throw new Error(message);
}

function occurrences(text, needle) {
  return text.split(needle).length - 1;
}

invariant(manifest.schema_version === "sensor-workbench-scaffold.v1", "unexpected scaffold schema version");
invariant(manifest.canonical_prd.revision === 5, "canonical PRD revision must remain r5");
invariant(
  manifest.canonical_prd.sha256 === "2799455a9649b7ef3a37b463dcd560b27d0d011046c70ea56e47ecf0595771e9",
  "canonical PRD digest drifted",
);
invariant(manifest.canonical_prd.scope_frozen === true, "canonical PRD scope must remain frozen");
invariant(manifest.canonical_prd.acceptance_criteria.length === 14, "canonical PRD must contain exactly 14 ACs");

for (const criterion of manifest.canonical_prd.acceptance_criteria) {
  invariant(occurrences(productSpec, criterion) === 1, `PRD must contain canonical criterion exactly once: ${criterion.slice(0, 5)}`);
}

for (const item of [...manifest.canonical_prd.in_scope, ...manifest.canonical_prd.out_of_scope]) {
  invariant(productSpec.includes(item), `PRD scope item missing: ${item}`);
}

for (const threshold of manifest.canonical_prd.candidate_thresholds) {
  invariant(productSpec.includes(`\`${threshold}\``), `candidate threshold missing: ${threshold}`);
}
invariant(productSpec.includes("均为 UNVERIFIED candidates"), "candidate thresholds were promoted to hard gates");
invariant(productSpec.includes("未经受控 PRD revision"), "controlled threshold revision policy is missing");

for (const relativePath of [
  "package.json",
  "package-lock.json",
  "tsconfig.json",
  "vite.config.ts",
  "playwright.config.ts",
  "index.html",
  ".gitignore",
  "docs/contracts/README.md",
  "docs/contracts/v1-wire-contract.md",
  "src/contracts/index.ts",
  "src/contracts/v1.ts",
  "tests/contracts/fixtures/v1.golden.ts",
  "tests/contracts/v1.contract.test.ts",
]) {
  invariant(statSync(resolve(appRoot, relativePath)).isFile(), `required scaffold file missing: app/${relativePath}`);
}

const expectedDirectories = {
  package_root: "app",
  source_root: "app/src",
  contract_root: "app/src/contracts",
  test_root: "app/tests",
  e2e_spec_root: "app/tests/e2e/specs",
  workspace_policy: "第三方数据根只读；index、cache、review、export 与 evidence 仅写独立 workspace/output",
};
invariant(JSON.stringify(manifest.directory_conventions) === JSON.stringify(expectedDirectories), "directory conventions drifted");

console.log("verify:scaffold passed: locked config, canonical PRD r5 (14/14 ACs), scope, and candidate policy are exact");
