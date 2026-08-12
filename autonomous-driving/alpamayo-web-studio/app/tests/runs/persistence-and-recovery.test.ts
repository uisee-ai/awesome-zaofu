import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import {
  FileRunPersistence,
  InMemoryRunPersistence,
  PersistentRunStore,
} from "../../backend/studio/runs/persistent-run-store.js";
import { runStatus } from "../../backend/studio/api/runs/status.js";

test("persists immutable run inputs, outputs, timings, and failures across a service restart", () => {
  const persistence = new InMemoryRunPersistence();
  const firstService = new PersistentRunStore(persistence);
  const parameters = { temperature: 0.2, cameraIds: [0, 1, 2, 6] };
  const output = { metaAction: "yield", trajectoryId: "trajectory-64" };

  firstService.save({
    id: "run-succeeded",
    state: "succeeded",
    sceneVersionId: "scene-version-7",
    model: { name: "alpamayo", version: "2026.08" },
    codeVersion: "git:abc123",
    parameters,
    seed: 42,
    output,
    timings: { queueDurationMs: 11, inferenceDurationMs: 29, totalDurationMs: 40 },
  });
  firstService.save({
    id: "run-failed",
    state: "failed",
    sceneVersionId: "scene-version-7",
    model: { name: "alpamayo", version: "2026.08" },
    codeVersion: "git:abc123",
    parameters: { temperature: 0 },
    seed: 43,
    output: null,
    timings: { queueDurationMs: 5, inferenceDurationMs: 8, totalDurationMs: 13 },
    error: { code: "UPSTREAM_TIMEOUT", message: "inference timed out" },
  });

  parameters.temperature = 0.9;
  output.metaAction = "accelerate";

  const restartedService = new PersistentRunStore(persistence);
  assert.deepEqual(runStatus(restartedService, "run-succeeded"), {
    id: "run-succeeded",
    state: "succeeded",
    sceneVersionId: "scene-version-7",
    model: { name: "alpamayo", version: "2026.08" },
    codeVersion: "git:abc123",
    parameters: { temperature: 0.2, cameraIds: [0, 1, 2, 6] },
    seed: 42,
    output: { metaAction: "yield", trajectoryId: "trajectory-64" },
    timings: { queueDurationMs: 11, inferenceDurationMs: 29, totalDurationMs: 40 },
  });
  assert.deepEqual(runStatus(restartedService, "run-failed"), {
    id: "run-failed",
    state: "failed",
    sceneVersionId: "scene-version-7",
    model: { name: "alpamayo", version: "2026.08" },
    codeVersion: "git:abc123",
    parameters: { temperature: 0 },
    seed: 43,
    output: null,
    timings: { queueDurationMs: 5, inferenceDurationMs: 8, totalDurationMs: 13 },
    error: { code: "UPSTREAM_TIMEOUT", message: "inference timed out" },
  });
});

test("restores queued work as well as completed results", () => {
  const persistence = new InMemoryRunPersistence();
  const service = new PersistentRunStore(persistence);
  service.save({
    id: "run-queued",
    state: "queued",
    sceneVersionId: "scene-version-8",
    model: { name: "alpamayo", version: "2026.08" },
    codeVersion: "git:def456",
    parameters: { guidanceScale: 4 },
    seed: 7,
    output: null,
    timings: { queueDurationMs: 0, inferenceDurationMs: 0, totalDurationMs: 0 },
  });

  const restartedService = new PersistentRunStore(persistence);
  assert.deepEqual(restartedService.recoverable(), ["run-queued"]);
  assert.equal(runStatus(restartedService, "missing-run"), null);
});

test("restores runs from durable storage when a new persistence adapter starts", () => {
  const directory = mkdtempSync(join(tmpdir(), "alpamayo-runs-"));
  const storagePath = join(directory, "runs.json");
  try {
    const firstService = new PersistentRunStore(new FileRunPersistence(storagePath));
    firstService.save({
      id: "run-durable",
      state: "succeeded",
      sceneVersionId: "scene-version-9",
      model: { name: "alpamayo", version: "2026.08" },
      codeVersion: "git:fedcba",
      parameters: { deterministic: true },
      seed: 99,
      output: { answer: "safe to proceed" },
      timings: { queueDurationMs: 3, inferenceDurationMs: 17, totalDurationMs: 20 },
    });

    const restartedService = new PersistentRunStore(new FileRunPersistence(storagePath));
    assert.equal(runStatus(restartedService, "run-durable")?.output instanceof Object, true);
    assert.deepEqual(runStatus(restartedService, "run-durable")?.output, { answer: "safe to proceed" });
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});
