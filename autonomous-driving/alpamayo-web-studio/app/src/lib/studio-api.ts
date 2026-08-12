import type { TrajectoryPoint } from "../../packages/contracts/src/scene";

export const DEMO_IDS = [
  "workbench",
  "navigation",
  "ablation",
  "vqa",
  "auto-label",
  "regression-judge",
] as const;

export type DemoId = (typeof DEMO_IDS)[number];

export interface InferenceResult extends Record<string, unknown> {
  provider: string;
  modelName: string;
  responseSha256: string;
  rawOutputRef: string;
  demoId: string;
  trajectoryHorizonSeconds: number;
  vqaAnswer: string;
  chainOfCausation: string;
  metaAction: string;
  trajectory: TrajectoryPoint[];
  labels: string[];
  warnings: string[];
  reviewStatus: "unreviewed" | "approved" | "rejected";
}

export type { TrajectoryPoint };

export interface StudioScene {
  sceneId: string;
  sceneVersionId: string;
  name: string;
  source: string;
  status: string;
  previewUrl: string;
  sceneVersion: {
    navigationInstruction: string;
    cameras: Array<{
      cameraId: number;
      frames: Array<{ assetRef: string }>;
    }>;
  };
}

export interface StudioRun {
  runId: string;
  sceneId: string | null;
  sceneVersionId?: string;
  demoId?: string;
  parameters?: Record<string, unknown>;
  status: "queued" | "running" | "completed" | "failed" | "cancelled";
  result?: InferenceResult;
  error?: { message: string; statusCode: number; retryable: boolean };
  reviews?: Array<{
    reviewId: string;
    decision: "accepted" | "modified" | "rejected";
    remarks: string;
    labels: string[];
  }>;
}

interface StudioFetchResponse {
  ok: boolean;
  status: number;
  json(): Promise<unknown>;
}

export type StudioFetch = (
  input: string,
  init?: { method?: string; headers?: Record<string, string>; body?: BodyInit | null },
) => Promise<StudioFetchResponse>;

export class StudioApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

async function request<T>(
  fetcher: StudioFetch,
  input: string,
  init?: { method?: string; headers?: Record<string, string>; body?: BodyInit | null },
): Promise<T> {
  const response = await fetcher(input, init);
  const payload = await response.json().catch(() => null) as { detail?: unknown } | null;
  if (!response.ok) {
    const detail = typeof payload?.detail === "string" ? payload.detail : `Request failed (${response.status})`;
    throw new StudioApiError(detail, response.status);
  }
  return payload as T;
}

export function createStudioApi(fetcher: StudioFetch = fetch) {
  return {
    async health(): Promise<{ status: string; services: Record<string, string> }> {
      return request(fetcher, "/api/health");
    },
    async listScenes(): Promise<StudioScene[]> {
      const payload = await request<{ items: StudioScene[] }>(fetcher, "/api/scenes");
      return payload.items;
    },
    async createDemoScene(name: string): Promise<StudioScene> {
      return request(fetcher, "/api/scenes", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ name, source: "golden" }),
      });
    },
    async listRuns(sceneId: string): Promise<StudioRun[]> {
      const payload = await request<{ items: StudioRun[] }>(
        fetcher,
        `/api/runs?sceneId=${encodeURIComponent(sceneId)}`,
      );
      return payload.items;
    },
    async submitRun(sceneId: string, demoId: DemoId, parameters: Record<string, unknown>): Promise<StudioRun> {
      return request(fetcher, `/api/scenes/${encodeURIComponent(sceneId)}/runs`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ demoId, parameters }),
      });
    },
    async readRun(runId: string): Promise<StudioRun> {
      return request(fetcher, `/api/runs/${encodeURIComponent(runId)}`);
    },
    async reviewRun(
      runId: string,
      decision: "accepted" | "modified" | "rejected",
      remarks = "",
      labels: string[] = [],
    ): Promise<void> {
      await request(fetcher, `/api/runs/${encodeURIComponent(runId)}/reviews`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ decision, remarks, labels }),
      });
    },
  };
}

export async function waitForTerminalRun(
  read: (runId: string) => Promise<StudioRun>,
  runId: string,
  options: { timeoutMs?: number; intervalMs?: number; onUpdate?: (run: StudioRun) => void } = {},
): Promise<StudioRun> {
  const timeoutMs = options.timeoutMs ?? 120_000;
  const intervalMs = options.intervalMs ?? 500;
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const run = await read(runId);
    options.onUpdate?.(run);
    if (["completed", "failed", "cancelled"].includes(run.status)) return run;
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
  throw new Error("Inference timed out before reaching a terminal state.");
}

/** Compatibility adapter for the reusable six-demo workflow controller. */
export function createStudioDemoInferenceClient(fetcher: StudioFetch = fetch) {
  return {
    async submit(sceneId: string, demo: DemoId) {
      const run = await request<StudioRun>(fetcher, `/api/scenes/${encodeURIComponent(sceneId)}/runs`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ demoId: demo, parameters: {} }),
      });
      return { runId: run.runId, status: run.status, result: run.result ?? null };
    },
    async read(runId: string) {
      try {
        const run = await request<StudioRun>(fetcher, `/api/runs/${encodeURIComponent(runId)}`);
        return { runId: run.runId, status: run.status, result: run.result ?? null };
      } catch (error) {
        if (error instanceof StudioApiError && error.status === 404) return null;
        throw error;
      }
    },
  };
}
