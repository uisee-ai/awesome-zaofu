import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdir, readFile, readdir, rm, stat, writeFile } from "node:fs/promises";
import { basename, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "@playwright/test";

const appRoot = fileURLToPath(new URL("../..", import.meta.url));
const defaultEvidenceRoot = join(appRoot, "artifacts", "e2e", "evidence");
const contractRevision = "contract-r89699449158a";
const shaPattern = /^sha256:[0-9a-f]{64}$/;
const packageManifest = JSON.parse(await readFile(join(appRoot, "package.json"), "utf8"));
const runnerVersion = packageManifest.devDependencies?.["@playwright/test"];
if (!/^\d+(?:\.\d+)+$/.test(runnerVersion)) throw new Error("@playwright/test must be pinned to an exact version");
const commandRuns = [
  {
    commandId: "SWB-ASSEMBLY-005-R3-CMD-02",
    canonicalCommand: "npm --prefix app run e2e:synthetic",
    spec: "tests/e2e/specs/synthetic.spec.ts",
    fixtureKind: "synthetic",
    fixturePath: "tests/fixtures/synthetic",
  },
  {
    commandId: "SWB-ASSEMBLY-005-R3-CMD-03",
    canonicalCommand: "npm --prefix app run e2e:nuscenes",
    spec: "tests/e2e/specs/nuscenes.spec.ts",
    fixtureKind: "nuscenes",
    fixturePath: "tests/fixtures/synthetic/nuscenes",
  },
  {
    commandId: "SWB-ASSEMBLY-005-R3-CMD-04",
    canonicalCommand: "npm --prefix app run e2e:openlane",
    spec: "tests/e2e/specs/openlane.spec.ts",
    fixtureKind: "openlane",
    fixturePath: "tests/fixtures/synthetic/openlane",
  },
];

function sha256(bytes) {
  return `sha256:${createHash("sha256").update(bytes).digest("hex")}`;
}

async function filesBelow(root) {
  const entries = await readdir(root, { withFileTypes: true });
  const nested = await Promise.all(entries.map(async (entry) => {
    const path = join(root, entry.name);
    return entry.isDirectory() ? filesBelow(path) : [path];
  }));
  return nested.flat().sort();
}

async function treeDigest(root) {
  const hash = createHash("sha256");
  for (const path of await filesBelow(root)) {
    hash.update(relative(root, path).split(sep).join("/"));
    hash.update("\0");
    hash.update(await readFile(path));
    hash.update("\0");
  }
  return `sha256:${hash.digest("hex")}`;
}

function gitHead() {
  const result = spawnSync("git", ["rev-parse", "HEAD"], { cwd: appRoot, encoding: "utf8" });
  if (result.status !== 0) throw new Error(`cannot resolve source commit: ${result.stderr}`);
  return result.stdout.trim();
}

async function findNamed(root, name) {
  return (await filesBelow(root)).filter((path) => basename(path) === name);
}

function loopbackOnly(rawUrl) {
  const url = new URL(rawUrl);
  return !["http:", "https:", "ws:", "wss:"].includes(url.protocol)
    || ["127.0.0.1", "localhost", "::1"].includes(url.hostname);
}

function redactUrl(rawUrl) {
  const url = new URL(rawUrl);
  url.username = "";
  url.password = "";
  url.search = "";
  url.hash = "";
  return url.toString();
}

async function summarizeHar(harPath, summaryPath) {
  const har = JSON.parse(await readFile(harPath, "utf8"));
  const entries = har.log?.entries ?? [];
  const requests = entries.map((entry) => ({
    started_at: entry.startedDateTime,
    duration_ms: entry.time,
    method: entry.request?.method,
    url: redactUrl(entry.request?.url),
    resource_type: entry._resourceType ?? "unknown",
    status: entry.response?.status,
    mime_type: entry.response?.content?.mimeType ?? "",
  }));
  await writeFile(summaryPath, `${JSON.stringify({ schema_version: "network-summary.v1", requests }, null, 2)}\n`);
  return requests.filter((request) => !loopbackOnly(request.url)).map((request) => request.url);
}

async function artifact(root, kind, path) {
  const bytes = await readFile(path);
  return {
    kind,
    path: relative(root, path).split(sep).join("/"),
    digest: sha256(bytes),
    byte_count: bytes.length,
    redacted: true,
  };
}

async function browserVersion() {
  const browser = await chromium.launch({ headless: true });
  try {
    return browser.version();
  } finally {
    await browser.close();
  }
}

async function collectRun(run, evidenceRoot, sourceCommit, productionBuildDigest, actualBrowserVersion) {
  const runRoot = join(evidenceRoot, "runs", run.commandId);
  await rm(runRoot, { recursive: true, force: true });
  await mkdir(runRoot, { recursive: true });
  const fixtureRoot = join(appRoot, run.fixturePath);
  const beforeDigest = await treeDigest(fixtureRoot);
  const startedAt = new Date().toISOString();
  const actualArgs = [
    "playwright", "test", run.spec,
    "--config", "tests/e2e/support/evidence.playwright.config.ts",
  ];
  const result = spawnSync("npx", actualArgs, {
    cwd: appRoot,
    encoding: "utf8",
    env: {
      ...process.env,
      SWB_EVIDENCE_RUN_ROOT: runRoot,
      SWB_SOURCE_COMMIT: sourceCommit,
      SWB_PRODUCTION_BUILD_DIGEST: productionBuildDigest,
      SWB_RUNNER_VERSION: runnerVersion,
    },
    maxBuffer: 20 * 1024 * 1024,
    timeout: 15 * 60 * 1000,
  });
  const finishedAt = new Date().toISOString();
  const afterDigest = await treeDigest(fixtureRoot);
  const logPath = join(runRoot, "command.redacted.log");
  const output = `${result.stdout ?? ""}\n${result.stderr ?? ""}`.split(appRoot).join("<APP_ROOT>");
  await writeFile(logPath, output);
  if (result.status !== 0) {
    throw new Error(`${run.commandId} browser evidence process failed with exit ${result.status ?? result.signal}; see ${relative(appRoot, logPath)}`);
  }

  const harPath = join(runRoot, "network.har");
  const networkSummaryPath = join(runRoot, "network.redacted.json");
  const nonLoopbackRequests = await summarizeHar(harPath, networkSummaryPath);
  const tracePaths = await findNamed(join(runRoot, "test-results"), "trace.zip");
  if (tracePaths.length === 0) throw new Error(`${run.commandId} did not produce a browser trace`);
  const traceManifestPath = join(runRoot, "trace-digests.redacted.json");
  const traces = await Promise.all(tracePaths.map(async (path) => ({
    path: relative(runRoot, path).split(sep).join("/"),
    digest: sha256(await readFile(path)),
    byte_count: (await stat(path)).size,
  })));
  await writeFile(traceManifestPath, `${JSON.stringify({ schema_version: "trace-digests.v1", traces }, null, 2)}\n`);
  const playwrightResultPath = join(runRoot, "playwright-result.json");
  const report = JSON.parse(await readFile(playwrightResultPath, "utf8"));
  const expected = report.stats?.expected ?? 0;
  const unexpected = report.stats?.unexpected ?? 0;
  const interrupted = report.stats?.interrupted ?? 0;
  const passed = result.status === 0 && expected > 0 && unexpected === 0 && interrupted === 0
    && nonLoopbackRequests.length === 0 && beforeDigest === afterDigest;
  const receipt = {
    schema_version: "browser-evidence-receipt.v1",
    receipt_id: `receipt-${run.commandId.toLowerCase()}-${startedAt.replace(/[^0-9]/g, "")}`,
    command_id: run.commandId,
    canonical_command: run.canonicalCommand,
    actual_command: `npx ${actualArgs.join(" ")}`,
    contract_revision: contractRevision,
    source_commit: sourceCommit,
    production_build_digest: productionBuildDigest,
    runner: { name: "@playwright/test", version: runnerVersion },
    browser: { name: "chromium", version: actualBrowserVersion },
    fixture: { kind: run.fixtureKind, path: run.fixturePath, digest: beforeDigest },
    started_at: startedAt,
    finished_at: finishedAt,
    exit_status: passed ? "passed" : result.signal ? "interrupted" : "failed",
    exit_code: result.status ?? 1,
    data_root_before_digest: beforeDigest,
    data_root_after_digest: afterDigest,
    artifacts: await Promise.all([
      artifact(evidenceRoot, "browser-trace-digests", traceManifestPath),
      artifact(evidenceRoot, "network-summary", networkSummaryPath),
      artifact(evidenceRoot, "playwright-result", playwrightResultPath),
      artifact(evidenceRoot, "command-output", logPath),
    ]),
    network: { loopback_only: nonLoopbackRequests.length === 0, non_loopback_requests: nonLoopbackRequests },
    metrics: { expected_tests: expected, unexpected_tests: unexpected, interrupted_tests: interrupted },
    result: passed ? "passed" : result.signal ? "interrupted" : "failed",
  };
  const receiptPath = join(evidenceRoot, `${run.commandId}.receipt.json`);
  await writeFile(receiptPath, `${JSON.stringify(receipt, null, 2)}\n`);
  if (!passed) throw new Error(`${run.commandId} browser evidence run failed; see ${relative(appRoot, logPath)}`);
  return receiptPath;
}

function assertObject(value, label) {
  if (typeof value !== "object" || value === null || Array.isArray(value)) throw new Error(`${label} must be an object`);
  return value;
}

async function validateReceipt(receiptPath, evidenceRoot, expectedHead, expectedBuildDigest, expectedBrowserVersion) {
  const receipt = assertObject(JSON.parse(await readFile(receiptPath, "utf8")), "receipt");
  const run = commandRuns.find((candidate) => candidate.commandId === receipt.command_id);
  if (!run) throw new Error(`unexpected command receipt: ${receipt.command_id}`);
  if (receipt.contract_revision !== contractRevision) throw new Error(`${run.commandId} contract revision is stale`);
  if (receipt.source_commit !== expectedHead) throw new Error(`${run.commandId} source commit does not match HEAD`);
  if (receipt.production_build_digest !== expectedBuildDigest) throw new Error(`${run.commandId} production build digest is stale`);
  if (receipt.canonical_command !== run.canonicalCommand) throw new Error(`${run.commandId} canonical command mismatch`);
  const expectedActualCommand = `npx playwright test ${run.spec} --config tests/e2e/support/evidence.playwright.config.ts`;
  if (receipt.actual_command !== expectedActualCommand) throw new Error(`${run.commandId} actual command mismatch`);
  if (receipt.runner?.name !== "@playwright/test" || receipt.runner.version !== runnerVersion) throw new Error(`${run.commandId} runner is not pinned`);
  if (receipt.browser?.name !== "chromium" || receipt.browser.version !== expectedBrowserVersion) throw new Error(`${run.commandId} browser version was not observed`);
  if (receipt.result !== "passed" || receipt.exit_status !== "passed" || receipt.exit_code !== 0) throw new Error(`${run.commandId} did not pass`);
  if (!shaPattern.test(receipt.data_root_before_digest) || receipt.data_root_before_digest !== receipt.data_root_after_digest) throw new Error(`${run.commandId} data root changed`);
  const currentFixtureDigest = await treeDigest(join(appRoot, run.fixturePath));
  if (receipt.fixture?.kind !== run.fixtureKind || receipt.fixture?.path !== run.fixturePath) throw new Error(`${run.commandId} fixture binding mismatch`);
  if (receipt.fixture.digest !== currentFixtureDigest || receipt.data_root_before_digest !== currentFixtureDigest) throw new Error(`${run.commandId} fixture digest is stale`);
  if (receipt.network?.loopback_only !== true || receipt.network.non_loopback_requests?.length !== 0) throw new Error(`${run.commandId} observed non-loopback traffic`);
  if (!(Date.parse(receipt.started_at) < Date.parse(receipt.finished_at))) throw new Error(`${run.commandId} timestamps are not an observed interval`);
  if (!Array.isArray(receipt.artifacts) || receipt.artifacts.length < 3) throw new Error(`${run.commandId} captured artifacts are missing`);
  const artifactsByKind = new Map();
  for (const item of receipt.artifacts) {
    if (item.redacted !== true || !shaPattern.test(item.digest)) throw new Error(`${run.commandId} artifact is not redacted and digested`);
    const path = resolve(evidenceRoot, item.path);
    if (!path.startsWith(`${resolve(evidenceRoot)}${sep}`)) throw new Error(`${run.commandId} artifact path escapes evidence root`);
    const bytes = await readFile(path);
    if (sha256(bytes) !== item.digest || bytes.length !== item.byte_count) throw new Error(`${run.commandId} artifact digest mismatch`);
    artifactsByKind.set(item.kind, path);
  }
  const traceManifest = assertObject(JSON.parse(await readFile(artifactsByKind.get("browser-trace-digests"), "utf8")), "trace manifest");
  if (!Array.isArray(traceManifest.traces) || traceManifest.traces.length === 0) throw new Error(`${run.commandId} trace manifest is empty`);
  const runRoot = join(evidenceRoot, "runs", run.commandId);
  for (const trace of traceManifest.traces) {
    const path = resolve(runRoot, trace.path);
    if (!path.startsWith(`${resolve(runRoot)}${sep}`)) throw new Error(`${run.commandId} trace path escapes run root`);
    const bytes = await readFile(path);
    if (sha256(bytes) !== trace.digest || bytes.length !== trace.byte_count) throw new Error(`${run.commandId} browser trace digest mismatch`);
  }
  const networkSummary = assertObject(JSON.parse(await readFile(artifactsByKind.get("network-summary"), "utf8")), "network summary");
  if (!Array.isArray(networkSummary.requests) || networkSummary.requests.length === 0) throw new Error(`${run.commandId} network trace is empty`);
  if (networkSummary.requests.some((request) => !loopbackOnly(request.url))) throw new Error(`${run.commandId} network trace contains a non-loopback request`);
  const playwrightResult = assertObject(JSON.parse(await readFile(artifactsByKind.get("playwright-result"), "utf8")), "Playwright result");
  if (playwrightResult.stats?.expected !== receipt.metrics?.expected_tests || playwrightResult.stats.expected < 1) throw new Error(`${run.commandId} test count mismatch`);
  if ((playwrightResult.stats.unexpected ?? 0) !== 0 || (playwrightResult.stats.interrupted ?? 0) !== 0) throw new Error(`${run.commandId} Playwright result is not passing`);
}

async function validateEvidence(evidenceRoot) {
  const expectedHead = gitHead();
  const expectedBuildDigest = await treeDigest(join(appRoot, "dist"));
  const expectedBrowserVersion = await browserVersion();
  for (const run of commandRuns) {
    await validateReceipt(
      join(evidenceRoot, `${run.commandId}.receipt.json`),
      evidenceRoot,
      expectedHead,
      expectedBuildDigest,
      expectedBrowserVersion,
    );
  }
  return { expectedHead, expectedBuildDigest };
}

const validateOnlyIndex = process.argv.indexOf("--validate-only");
if (validateOnlyIndex >= 0) {
  const evidenceRoot = resolve(process.argv[validateOnlyIndex + 1] ?? defaultEvidenceRoot);
  await validateEvidence(evidenceRoot);
  console.log(`evidence verified at ${evidenceRoot}`);
} else {
  const evidenceRoot = defaultEvidenceRoot;
  await rm(evidenceRoot, { recursive: true, force: true });
  await mkdir(evidenceRoot, { recursive: true });
  const build = spawnSync("npm", ["run", "build"], { cwd: appRoot, encoding: "utf8", maxBuffer: 20 * 1024 * 1024 });
  if (build.status !== 0) throw new Error(`production build failed:\n${build.stdout}\n${build.stderr}`);
  const sourceCommit = gitHead();
  const productionBuildDigest = await treeDigest(join(appRoot, "dist"));
  const actualBrowserVersion = await browserVersion();
  for (const run of commandRuns) await collectRun(run, evidenceRoot, sourceCommit, productionBuildDigest, actualBrowserVersion);
  const verified = await validateEvidence(evidenceRoot);
  console.log(`evidence verified: 3 production browser runs at ${verified.expectedHead}, build ${verified.expectedBuildDigest}`);
}
