import { describe, expect, it } from "vitest";

import fixture from "../fixtures/synthetic/review/review-fixture.json";
import {
  MemoryReviewPersistence,
  ReviewStore,
  type AppendReviewCommand,
} from "../../src/features/review";

const commands: AppendReviewCommand[] = fixture.events.map((event) => ({
  ...event,
  reviewId: "review-0001",
  frameContextId: fixture.frameContextId,
  actorId: fixture.actorId,
  target: fixture.target,
})) as AppendReviewCommand[];

function createStore(workspaceId: string) {
  return new ReviewStore({
    workspaceId,
    datasetDigest: fixture.datasetDigest,
    persistence: new MemoryReviewPersistence(),
  });
}

async function replay(workspaceId: string) {
  const store = createStore(workspaceId);
  const results = [];
  for (const command of commands) results.push(await store.append(command));
  return { store, results, snapshot: await store.snapshot() };
}

describe("deterministic review replay", () => {
  it("produces the same state digest, revisions, and results from the same inputs", async () => {
    const first = await replay("workspace-deterministic");
    const second = await replay("workspace-deterministic");

    expect(second.results).toEqual(first.results);
    expect(second.snapshot).toEqual(first.snapshot);
    expect(first.snapshot.stateDigest).toMatch(/^sha256:[a-f0-9]{64}$/);
  });

  it("produces stable export identities and deterministic import dedupe", async () => {
    const first = await replay("workspace-deterministic");
    const second = await replay("workspace-deterministic");
    const exportRequest = {
      exportId: "export-deterministic",
      createdAt: "2026-08-04T10:00:00.000Z",
      sinceSequence: 0,
    };

    const firstEnvelope = await first.store.exportDiff(exportRequest);
    const secondEnvelope = await second.store.exportDiff(exportRequest);
    expect(secondEnvelope).toEqual(firstEnvelope);

    const destination = createStore("workspace-import-deterministic");
    const firstImport = await destination.importDiff(firstEnvelope);
    const firstDigest = (await destination.snapshot()).stateDigest;
    const secondImport = await destination.importDiff(firstEnvelope);
    const secondDigest = (await destination.snapshot()).stateDigest;

    expect(firstImport).toEqual({ status: "imported", imported: 2, duplicates: 0 });
    expect(secondImport).toEqual({ status: "duplicate", imported: 0, duplicates: 2 });
    expect(secondDigest).toBe(firstDigest);
  });

  it("replays the same conflict outcome after reset", async () => {
    async function conflictSchedule() {
      const store = createStore("workspace-conflict");
      await store.append(commands[0]);
      const update = { ...commands[1], expectedRevision: 0 };
      return { result: await store.append(update), snapshot: await store.snapshot() };
    }

    expect(await conflictSchedule()).toEqual(await conflictSchedule());
  });
});
