import type { PersistedRun, RunPersistence } from "../runs/persistent-run-store.js";

export interface RunMetrics {
  succeeded: number;
  failed: number;
  cancelled: number;
  queueDurationMs: number;
  inferenceDurationMs: number;
}

const emptyMetrics = (): RunMetrics => ({
  succeeded: 0,
  failed: 0,
  cancelled: 0,
  queueDurationMs: 0,
  inferenceDurationMs: 0,
});

/** Rebuilds telemetry from the durable run record on every process start. */
export function metricsFromPersistedRuns(persistence: RunPersistence): RunMetrics {
  return persistence.load().reduce<RunMetrics>((metrics, run: PersistedRun) => {
    if (run.state === "succeeded") metrics.succeeded += 1;
    if (run.state === "failed") metrics.failed += 1;
    if (run.state === "cancelled") metrics.cancelled += 1;
    metrics.queueDurationMs += run.timings.queueDurationMs;
    metrics.inferenceDurationMs += run.timings.inferenceDurationMs;
    return metrics;
  }, emptyMetrics());
}
