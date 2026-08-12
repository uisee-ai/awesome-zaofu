import type { RunPersistence } from "../../runs/persistent-run-store.js";
import { metricsFromPersistedRuns, type RunMetrics } from "../../observability/run-metrics.js";

export interface HealthDependencies {
  backendReady: boolean;
  workerReady: boolean;
  persistence: RunPersistence;
}

export interface HealthResponse {
  status: "ready" | "degraded";
  services: {
    backend: { status: "ready" | "unavailable" };
    worker: { status: "ready" | "unavailable" };
  };
  metrics: RunMetrics;
}

/** Public health projection for the backend and its inference worker. */
export function healthResponse(dependencies: HealthDependencies): HealthResponse {
  const ready = dependencies.backendReady && dependencies.workerReady;
  return {
    status: ready ? "ready" : "degraded",
    services: {
      backend: { status: dependencies.backendReady ? "ready" : "unavailable" },
      worker: { status: dependencies.workerReady ? "ready" : "unavailable" },
    },
    metrics: metricsFromPersistedRuns(dependencies.persistence),
  };
}
