import assert from "node:assert/strict";
import test from "node:test";

import {
  SingleConcurrencyQueue,
  type QueueTaskSnapshot,
} from "../../backend/studio/queue/single-concurrency-queue.js";
import { queueTaskStatus } from "../../backend/studio/api/queue/status.js";

interface Deferred<T> {
  promise: Promise<T>;
  resolve(value: T): void;
  reject(reason?: unknown): void;
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function snapshot(queue: SingleConcurrencyQueue<string, unknown>, id: string): QueueTaskSnapshot {
  const task = queueTaskStatus(queue, id);
  assert.ok(task);
  return task;
}

test("runs model requests one at a time and reports waiting, running, and success positions", async () => {
  const first = deferred<string>();
  const second = deferred<string>();
  const started: string[] = [];
  const queue = new SingleConcurrencyQueue<string, string>(async (value) => {
    started.push(value);
    if (value === "first") return first.promise;
    if (value === "second") return second.promise;
    return "third-result";
  });

  const firstId = queue.enqueue("first");
  const secondId = queue.enqueue("second");
  const thirdId = queue.enqueue("third");

  await queue.idleTick();
  assert.deepEqual(started, ["first"]);
  assert.deepEqual(snapshot(queue, firstId), {
    id: firstId,
    state: "running",
    queuePosition: 0,
    attempts: 1,
  });
  assert.deepEqual(snapshot(queue, secondId), {
    id: secondId,
    state: "waiting",
    queuePosition: 1,
    attempts: 0,
  });
  assert.deepEqual(snapshot(queue, thirdId), {
    id: thirdId,
    state: "waiting",
    queuePosition: 2,
    attempts: 0,
  });

  first.resolve("first-result");
  await queue.whenSettled(firstId);

  assert.deepEqual(started, ["first", "second"]);
  assert.equal(snapshot(queue, firstId).state, "succeeded");
  assert.equal(snapshot(queue, secondId).state, "running");
  assert.deepEqual(snapshot(queue, thirdId), {
    id: thirdId,
    state: "waiting",
    queuePosition: 1,
    attempts: 0,
  });

  second.resolve("second-result");
  await queue.whenSettled(secondId);
  await queue.whenSettled(thirdId);
  assert.deepEqual(snapshot(queue, thirdId), {
    id: thirdId,
    state: "succeeded",
    queuePosition: null,
    attempts: 1,
  });
});

test("allows cancellation only before a queued task starts", async () => {
  const first = deferred<void>();
  const queue = new SingleConcurrencyQueue<string, void>(async (value) => {
    if (value === "first") return first.promise;
  });

  const firstId = queue.enqueue("first");
  const waitingId = queue.enqueue("waiting");
  await queue.idleTick();

  assert.equal(queue.cancel(firstId), false);
  assert.equal(queue.cancel(waitingId), true);
  assert.deepEqual(snapshot(queue, waitingId), {
    id: waitingId,
    state: "cancelled",
    queuePosition: null,
    attempts: 0,
  });

  first.resolve();
  await queue.whenSettled(firstId);
  assert.equal(snapshot(queue, firstId).state, "succeeded");
});

test("records an OOM failure without retrying and releases the lock for the next task", async () => {
  const calls: string[] = [];
  const queue = new SingleConcurrencyQueue<string, string>(async (value) => {
    calls.push(value);
    if (value === "oom") {
      const error = Object.assign(new Error("CUDA out of memory"), { statusCode: 503 });
      throw error;
    }
    return "recovered";
  });

  const oomId = queue.enqueue("oom");
  const nextId = queue.enqueue("next");

  await queue.whenSettled(oomId);
  await queue.whenSettled(nextId);

  assert.deepEqual(calls, ["oom", "next"]);
  assert.deepEqual(snapshot(queue, oomId), {
    id: oomId,
    state: "failed",
    queuePosition: null,
    attempts: 1,
    failure: {
      message: "CUDA out of memory",
      statusCode: 503,
      retryable: false,
    },
  });
  assert.equal(snapshot(queue, nextId).state, "succeeded");
  assert.equal(queue.runningTaskId, null);
});
