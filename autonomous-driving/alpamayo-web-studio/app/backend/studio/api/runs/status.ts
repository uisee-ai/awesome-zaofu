import {
  type PersistedRun,
  type PersistentRunStore,
} from "../../runs/persistent-run-store.js";

export function runStatus(store: PersistentRunStore, runId: string): PersistedRun | null {
  return store.find(runId);
}
