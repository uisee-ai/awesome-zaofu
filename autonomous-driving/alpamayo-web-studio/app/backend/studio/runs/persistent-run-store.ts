export type RunState = "queued" | "running" | "succeeded" | "failed" | "cancelled";

export interface RunModel {
  name: string;
  version: string;
}

export interface RunTimings {
  queueDurationMs: number;
  inferenceDurationMs: number;
  totalDurationMs: number;
}

export interface RunFailure {
  code: string;
  message: string;
}

export interface PersistedRun {
  id: string;
  state: RunState;
  sceneVersionId: string;
  model: RunModel;
  codeVersion: string;
  parameters: Record<string, unknown>;
  seed: number;
  output: unknown;
  timings: RunTimings;
  error?: RunFailure;
}

export interface RunPersistence {
  load(): PersistedRun[];
  replace(records: PersistedRun[]): void;
}

function copy<T>(value: T): T {
  return structuredClone(value);
}

/**
 * A test-friendly persistence adapter. Production storage can implement the same
 * interface with a database while preserving the restart/recovery behaviour.
 */
export class InMemoryRunPersistence implements RunPersistence {
  private records: PersistedRun[] = [];

  load(): PersistedRun[] {
    return copy(this.records);
  }

  replace(records: PersistedRun[]): void {
    this.records = copy(records);
  }
}

export class FileRunPersistence implements RunPersistence {
  constructor(private readonly storagePath: string) {}

  load(): PersistedRun[] {
    if (!existsSync(this.storagePath)) return [];
    const records: unknown = JSON.parse(readFileSync(this.storagePath, "utf8"));
    if (!Array.isArray(records)) {
      throw new Error(`Persisted runs at ${this.storagePath} must be an array.`);
    }
    return copy(records as PersistedRun[]);
  }

  replace(records: PersistedRun[]): void {
    mkdirSync(dirname(this.storagePath), { recursive: true });
    writeFileSync(this.storagePath, JSON.stringify(records), "utf8");
  }
}

export class PersistentRunStore {
  private readonly records = new Map<string, PersistedRun>();

  constructor(private readonly persistence: RunPersistence) {
    for (const record of persistence.load()) {
      this.records.set(record.id, copy(record));
    }
  }

  save(run: PersistedRun): PersistedRun {
    if (this.records.has(run.id)) {
      throw new Error(`Run ${run.id} is immutable and cannot be overwritten.`);
    }

    const snapshot = copy(run);
    this.records.set(snapshot.id, snapshot);
    this.persist();
    return copy(snapshot);
  }

  find(id: string): PersistedRun | null {
    const run = this.records.get(id);
    return run === undefined ? null : copy(run);
  }

  recoverable(): string[] {
    return [...this.records.values()]
      .filter((run) => run.state === "queued" || run.state === "running")
      .map((run) => run.id);
  }

  private persist(): void {
    this.persistence.replace([...this.records.values()]);
  }
}
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";
