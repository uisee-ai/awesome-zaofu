export type WorkbenchRunState = "queued" | "running" | "succeeded" | "failed" | "cancelled";

export interface WorkbenchRunConfiguration {
  model: string;
  parameters: Record<string, unknown>;
  seed: number;
  sceneVersionId?: string;
}

export interface WorkbenchInferenceOutput {
  vqaAnswer: string;
  chainOfCausation: string;
  metaAction: string;
}

export interface WorkbenchRun {
  id: string;
  state: WorkbenchRunState;
  configuration: WorkbenchRunConfiguration;
  output?: WorkbenchInferenceOutput;
  error?: string;
}

export interface WorkbenchRunPersistence {
  load(): WorkbenchRun[];
  replace(runs: WorkbenchRun[]): void;
}

export type WorkbenchInference = (configuration: Readonly<WorkbenchRunConfiguration>) => Promise<WorkbenchInferenceOutput>;

function copy<T>(value: T): T {
  return structuredClone(value);
}

/** A persistence adapter suitable for wiring the panel in tests or a process-local demo. */
export class InMemoryWorkbenchRunPersistence implements WorkbenchRunPersistence {
  private records: WorkbenchRun[] = [];

  load(): WorkbenchRun[] {
    return copy(this.records);
  }

  replace(runs: WorkbenchRun[]): void {
    this.records = copy(runs);
  }
}

/**
 * Owns workbench-specific run records. A new submission always receives a new
 * identifier, so subsequent runs preserve the complete history of prior output.
 */
export class WorkbenchRunService {
  private readonly records = new Map<string, WorkbenchRun>();
  private readonly settlements = new Map<string, Promise<void>>();
  private sequence = 0;

  constructor(
    private readonly persistence: WorkbenchRunPersistence,
    private readonly infer: WorkbenchInference,
  ) {
    for (const run of persistence.load()) {
      this.records.set(run.id, copy(run));
      this.sequence = Math.max(this.sequence, sequenceFromId(run.id));
    }
  }

  submit(configuration: WorkbenchRunConfiguration): WorkbenchRun {
    const run: WorkbenchRun = {
      id: `workbench-run-${++this.sequence}`,
      state: "queued",
      configuration: copy(configuration),
    };
    this.records.set(run.id, run);
    this.persist();

    const settlement = this.execute(run.id);
    this.settlements.set(run.id, settlement);
    return copy(run);
  }

  get(runId: string): WorkbenchRun | null {
    const run = this.records.get(runId);
    return run === undefined ? null : copy(run);
  }

  list(): WorkbenchRun[] {
    return [...this.records.values()].map(copy);
  }

  async whenSettled(runId: string): Promise<void> {
    const settlement = this.settlements.get(runId);
    if (settlement === undefined) return;
    await settlement;
  }

  private async execute(runId: string): Promise<void> {
    const queued = this.records.get(runId);
    if (queued === undefined) return;

    this.replace({ ...queued, state: "running" });
    try {
      const output = await this.infer(copy(queued.configuration));
      this.replace({ ...this.requireRun(runId), state: "succeeded", output: copy(output) });
    } catch (error) {
      const message = error instanceof Error ? error.message : "Workbench 推理失败。";
      this.replace({ ...this.requireRun(runId), state: "failed", error: message });
    }
  }

  private requireRun(runId: string): WorkbenchRun {
    const run = this.records.get(runId);
    if (run === undefined) throw new Error(`Unknown Workbench run: ${runId}`);
    return run;
  }

  private replace(run: WorkbenchRun): void {
    this.records.set(run.id, copy(run));
    this.persist();
  }

  private persist(): void {
    this.persistence.replace([...this.records.values()]);
  }
}

function sequenceFromId(id: string): number {
  const match = /^workbench-run-(\d+)$/.exec(id);
  return match === null ? 0 : Number(match[1]);
}
