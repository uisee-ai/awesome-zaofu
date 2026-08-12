import {
  type QueueTaskSnapshot,
  type SingleConcurrencyQueue,
} from "../../queue/single-concurrency-queue.js";

export function queueTaskStatus<Input, Result>(
  queue: SingleConcurrencyQueue<Input, Result>,
  taskId: string,
): QueueTaskSnapshot | null {
  return queue.getTask(taskId);
}
