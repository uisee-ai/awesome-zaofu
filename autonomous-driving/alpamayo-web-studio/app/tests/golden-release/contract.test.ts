import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { spawn, spawnSync } from "node:child_process";
import { createServer } from "node:http";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import test from "node:test";
import { fileURLToPath } from "node:url";

const appRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const suitePath = path.join(appRoot, "fixtures/golden-release/authorized-first-inference.json");
const runnerPath = path.join(appRoot, "quality/golden-release/run-first-inference-suite.sh");

test("authorized first-inference suite pins one legal four-camera input and its measurement policy", () => {
  const suite = JSON.parse(readFileSync(suitePath, "utf8")) as Record<string, unknown>;
  const policy = suite.measurementPolicy as Record<string, unknown>;
  const releaseAuthorization = suite.releaseAuthorization as Record<string, unknown>;
  const samples = suite.eligibleSamples as Array<Record<string, unknown>>;
  const sample = samples[0];
  const scene = sample.scene as Record<string, unknown>;
  const cameras = scene.cameras as Array<Record<string, unknown>>;
  const history = scene.history as Record<string, unknown>;
  const authorization = sample.authorization as Record<string, unknown>;

  assert.equal(suite.schemaVersion, "golden-release-suite.v1");
  assert.equal(releaseAuthorization.approvedFor, "internal demo and evaluation");
  assert.equal(samples.length, 1, "the success-rate denominator is a fixed, explicit sample set");
  assert.deepEqual(cameras.map(({ cameraId }) => cameraId), [0, 1, 2, 6]);
  assert.ok(cameras.every(({ frames }) => Array.isArray(frames) && frames.length === 4));
  assert.equal((history.positions as unknown[]).length, 16);
  assert.equal((history.rotations as unknown[]).length, 16);
  assert.match(scene.navigationInstruction as string, /\S/);
  assert.equal(authorization.status, "approved");
  assert.equal(policy.timingStart, "immediately-before-first-user-submission");
  assert.equal(policy.successRateDenominator, "all-eligible-samples");
  assert.equal(policy.illegalInputHandling, "excluded-before-submission");
  assert.equal(policy.maxFirstInferenceSeconds, 300);
  assert.equal(policy.minimumSuccessRate, 0.95);
});

test("live runner validates its bounds and emits a replayable, sanitized evidence record", () => {
  const runner = readFileSync(runnerPath, "utf8");
  assert.match(runner, /--max-first-run-seconds/);
  assert.match(runner, /--minimum-success-rate/);
  assert.match(runner, /immediately-before-first-user-submission/);
  assert.match(runner, /all-eligible-samples/);
  assert.match(runner, /excluded-before-submission/);
  assert.match(runner, /first-run-evidence\.v1/);

  const syntax = spawnSync("bash", ["-n", runnerPath], { encoding: "utf8" });
  assert.equal(syntax.status, 0, syntax.stderr);
});

test("live runner measures from submission and waits for a completed inference before counting success", async () => {
  let polls = 0;
  const server = createServer((request, response) => {
    response.setHeader("content-type", "application/json");
    if (request.method === "POST" && request.url === "/api/runs") {
      response.end(JSON.stringify({ runId: "golden-run-1", status: "queued" }));
      return;
    }
    if (request.method === "GET" && request.url === "/api/runs/golden-run-1") {
      polls += 1;
      response.end(JSON.stringify({ status: polls === 1 ? "running" : "succeeded" }));
      return;
    }
    response.statusCode = 404;
    response.end(JSON.stringify({ status: "missing" }));
  });

  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  assert.ok(address && typeof address === "object");
  const evidenceDir = mkdtempSync(path.join(tmpdir(), "golden-release-"));
  const evidencePath = path.join(evidenceDir, "first-run.json");

  try {
    const exitCode = await new Promise<number>((resolve, reject) => {
      const child = spawn(runnerPath, [
        "--base-url", `http://127.0.0.1:${address.port}`,
        "--max-first-run-seconds", "300",
        "--minimum-success-rate", "0.95",
        "--evidence", evidencePath,
      ]);
      child.once("error", reject);
      child.once("exit", (code) => resolve(code ?? 1));
    });
    const evidence = JSON.parse(readFileSync(evidencePath, "utf8")) as Record<string, unknown>;

    assert.equal(exitCode, 0);
    assert.ok(polls >= 2);
    assert.equal(evidence.denominator, 1);
    assert.equal(evidence.successCount, 1);
    assert.equal(evidence.successRate, 1);
    assert.equal((evidence.measurementPolicy as Record<string, unknown>).timingStart, "immediately-before-first-user-submission");
  } finally {
    await new Promise<void>((resolve) => server.close(() => resolve()));
    rmSync(evidenceDir, { recursive: true, force: true });
  }
});
