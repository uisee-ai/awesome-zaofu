export type QueueTaskState = "waiting" | "running" | "succeeded" | "failed" | "cancelled";

export interface QueueTaskFailure {
  message: string;
  statusCode?: number;
  retryable: false;
}

export interface QueueTaskSnapshot {
  id: string;
  state: QueueTaskState;
  queuePosition: number | null;
  attempts: number;
  failure?: QueueTaskFailure;
}

export type QueueExecutor<Input, Result> = (input: Input) => Promise<Result>;

interface QueueTask<Input> {
  id: string;
  input: Input;
  state: QueueTaskState;
  attempts: number;
  failure?: QueueTaskFailure;
  settle: () => void;
  settled: Promise<void>;
}

function taskFailure(error: unknown): QueueTaskFailure {
  const message = error instanceof Error ? error.message : String(error);
  const statusCode = typeof error === "object" && error !== null && "statusCode" in error
    && typeof error.statusCode === "number"
    ? error.statusCode
    : undefined;

  return { message, ...(statusCode === undefined ? {} : { statusCode }), retryable: false };
}

export class SingleConcurrencyQueue<Input, Result> {
  private readonly tasks = new Map<string, QueueTask<Input>>();
  private readonly waiting: string[] = [];
  private sequence = 0;
  private draining = false;
  public runningTaskId: string | null = null;

  constructor(private readonly execute: QueueExecutor<Input, Result>) {}

  enqueue(input: Input): string {
    const id = `queue-${++this.sequence}`;
    let settle!: () => void;
    const settled = new Promise<void>((resolve) => { settle = resolve; });
    this.tasks.set(id, { id, input, state: "waiting", attempts: 0, settle, settled });
    this.waiting.push(id);
    void this.drain();
    return id;
  }

  cancel(id: string): boolean {
    const task = this.tasks.get(id);
    if (task?.state !== "waiting") return false;

    const position = this.waiting.indexOf(id);
    if (position >= 0) this.waiting.splice(position, 1);
    task.state = "cancelled";
    task.settle();
    return true;
  }

  getTask(id: string): QueueTaskSnapshot | null {
    const task = this.tasks.get(id);
    if (!task) return null;
    const queuePosition = task.state === "waiting"
      ? this.waiting.indexOf(id) + 1
      : task.state === "running"
        ? 0
        : null;
    return {
      id: task.id,
      state: task.state,
      queuePosition,
      attempts: task.attempts,
      ...(task.failure === undefined ? {} : { failure: task.failure }),
    };
  }

  async whenSettled(id: string): Promise<void> {
    const task = this.tasks.get(id);
    if (!task) throw new Error(`Unknown queue task: ${id}`);
    await task.settled;
  }

  async idleTick(): Promise<void> {
    await Promise.resolve();
  }

  private async drain(): Promise<void> {
    if (this.draining) return;
    this.draining = true;
    try {
      while (this.runningTaskId === null) {
        const id = this.waiting.shift();
        if (id === undefined) return;
        const task = this.tasks.get(id);
        if (task?.state !== "waiting") continue;

        this.runningTaskId = id;
        task.state = "running";
        task.attempts += 1;
        try {
          await this.execute(task.input);
          task.state = "succeeded";
        } catch (error) {
          task.state = "failed";
          task.failure = taskFailure(error);
        } finally {
          this.runningTaskId = null;
          task.settle();
        }
      }
    } finally {
      this.draining = false;
      if (this.runningTaskId === null && this.waiting.length > 0) void this.drain();
    }
  }
}
