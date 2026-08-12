import assert from "node:assert/strict";
import test from "node:test";

import { healthResponse } from "../../backend/studio/api/health/health.js";
import {
  InMemoryRunPersistence,
  type PersistedRun,
} from "../../backend/studio/runs/persistent-run-store.js";
import { InMemoryStructuredLogger } from "../../backend/studio/observability/structured-logger.js";

function persistedRun(state: PersistedRun["state"], id: string): PersistedRun {
  return {
    id,
    state,
    sceneVersionId: "scene-version-24",
    model: { name: "alpamayo", version: "2026.08" },
    codeVersion: "git:observability",
    parameters: {},
    seed: 24,
    output: null,
    timings: { queueDurationMs: 12, inferenceDurationMs: 34, totalDurationMs: 46 },
  };
}

test("structured backend and worker logs correlate IDs, duration, and redact sensitive payloads", () => {
  const logger = new InMemoryStructuredLogger(() => "2026-08-10T00:00:00.000Z");

  logger.info({
    actor: "backend",
    event: "model.response",
    requestId: "request-24",
    sceneId: "scene-24",
    runId: "run-24",
    modelResponseDurationMs: 34,
    data: {
      authorization: "Bearer must-not-appear",
      secret: "must-not-appear",
      image: "data:image/jpeg;base64,aGVsbG8td29ybGQ=",
      rawImage: "aGVsbG8td29ybGQ=",
      cameraFrames: ["aGVsbG8td29ybGQ="],
      safe: "kept",
    },
  });
  logger.info({
    actor: "worker",
    event: "run.completed",
    requestId: "request-24",
    sceneId: "scene-24",
    runId: "run-24",
    modelResponseDurationMs: 21,
  });

  const entries = logger.entries();
  assert.equal(entries.length, 2);
  assert.deepEqual(entries[0], {
    timestamp: "2026-08-10T00:00:00.000Z",
    actor: "backend",
    event: "model.response",
    requestId: "request-24",
    sceneId: "scene-24",
    runId: "run-24",
    modelResponseDurationMs: 34,
    data: {
      authorization: "[REDACTED]",
      secret: "[REDACTED]",
      image: "[REDACTED_BASE64]",
      rawImage: "[REDACTED_BASE64]",
      cameraFrames: ["[REDACTED_BASE64]"],
      safe: "kept",
    },
  });
  assert.equal(entries[1]?.actor, "worker");
  assert.equal(entries[1]?.runId, "run-24");
  assert.doesNotMatch(JSON.stringify(entries), /must-not-appear|data:image\/jpeg;base64|aGVsbG8td29ybGQ=/i);
});

test("health response reports backend and worker readiness with metrics rebuilt from persisted runs", () => {
  const persistence = new InMemoryRunPersistence();
  persistence.replace([
    persistedRun("succeeded", "run-success"),
    persistedRun("failed", "run-failure"),
    persistedRun("cancelled", "run-cancelled"),
  ]);

  const health = healthResponse({ backendReady: true, workerReady: false, persistence });

  assert.deepEqual(health, {
    status: "degraded",
    services: {
      backend: { status: "ready" },
      worker: { status: "unavailable" },
    },
    metrics: {
      succeeded: 1,
      failed: 1,
      cancelled: 1,
      queueDurationMs: 36,
      inferenceDurationMs: 102,
    },
  });
});
