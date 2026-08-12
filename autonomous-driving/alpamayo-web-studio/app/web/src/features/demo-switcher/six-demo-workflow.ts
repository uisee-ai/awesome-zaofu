import {
  createDemoSwitcher,
  type DemoEntry,
  type SharedDemoScene,
} from "./demo-switcher.js";
import type { DemoDestination } from "../../../../backend/studio/demo-linking/shared-scene-entry.js";

export interface SavedDemoResult {
  runId: string;
  status: "queued" | "running" | "completed" | "succeeded" | "failed" | "cancelled";
  result: Record<string, unknown> | null;
}

export interface DemoInferenceClient {
  submit(sceneVersionId: string, demo: DemoDestination): Promise<SavedDemoResult>;
  read(runId: string): Promise<SavedDemoResult | null>;
}

export interface SixDemoEntry extends DemoEntry {
  runId: string | null;
  status: SavedDemoResult["status"] | "ready";
  result: Record<string, unknown> | null;
}

/**
 * Keeps the six demo entrances anchored to one selected SceneVersion.
 * Results are retrieved by run id so a reload can show the server-persisted
 * inference response instead of treating it as transient client state.
 */
export class SixDemoWorkflow {
  private entries: SixDemoEntry[] = [];

  constructor(private readonly client: DemoInferenceClient) {}

  open(scene: SharedDemoScene): SixDemoEntry[] {
    this.entries = createDemoSwitcher().createEntries(scene).map((entry) => ({
      ...entry,
      runId: null,
      status: "ready",
      result: null,
    }));
    return this.snapshot();
  }

  snapshot(): SixDemoEntry[] {
    return structuredClone(this.entries);
  }

  async submit(demo: DemoDestination): Promise<SixDemoEntry> {
    const entry = this.entryFor(demo);
    const saved = await this.client.submit(entry.sceneVersionId, demo);
    return this.applySavedResult(demo, saved);
  }

  async read(demo: DemoDestination): Promise<SixDemoEntry> {
    const entry = this.entryFor(demo);
    if (entry.runId === null) {
      throw new Error(`${demo} has no submitted inference result to read.`);
    }
    const saved = await this.client.read(entry.runId);
    if (saved === null) {
      throw new Error(`Saved inference result ${entry.runId} was not found.`);
    }
    return this.applySavedResult(demo, saved);
  }

  private entryFor(demo: DemoDestination): SixDemoEntry {
    const entry = this.entries.find((candidate) => candidate.demo === demo);
    if (entry === undefined) {
      throw new Error("Open a shared SceneVersion before entering a demo.");
    }
    return entry;
  }

  private applySavedResult(demo: DemoDestination, saved: SavedDemoResult): SixDemoEntry {
    const index = this.entries.findIndex((entry) => entry.demo === demo);
    const updated: SixDemoEntry = {
      ...this.entries[index]!,
      runId: saved.runId,
      status: saved.status,
      result: saved.result === null ? null : structuredClone(saved.result),
    };
    this.entries[index] = updated;
    return structuredClone(updated);
  }
}

export function createSixDemoWorkflow(client: DemoInferenceClient): SixDemoWorkflow {
  return new SixDemoWorkflow(client);
}
