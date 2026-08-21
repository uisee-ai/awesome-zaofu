import { describe, expect, it } from "vitest";

import fixture from "../fixtures/synthetic/review/review-fixture.json";
import {
  MemoryReviewPersistence,
  ReviewStore,
  type AppendReviewCommand,
} from "../../src/features/review";

function command(index: number): AppendReviewCommand {
  const event = fixture.events[index];
  if (!event) throw new Error(`missing fixture event ${index}`);
  return {
    ...event,
    reviewId: "review-0001",
    frameContextId: fixture.frameContextId,
    actorId: fixture.actorId,
    target: fixture.target,
  } as AppendReviewCommand;
}

function createStore(persistence = new MemoryReviewPersistence()) {
  return new ReviewStore({
    workspaceId: fixture.workspaceId,
    datasetDigest: fixture.datasetDigest,
    persistence,
  });
}

describe("append-only review history", () => {
  it("persists issue and comment as immutable linked revisions", async () => {
    const store = createStore();

    const issue = await store.append(command(0));
    const comment = await store.append(command(1));
    const snapshot = await store.snapshot();

    expect(issue).toMatchObject({ status: "appended", revision: 1 });
    expect(comment).toMatchObject({ status: "appended", revision: 2 });
    expect(snapshot.events).toEqual([
      expect.objectContaining({
        eventId: "review-event-0001",
        revision: 1,
        previousEventId: null,
        immutable: true,
      }),
      expect.objectContaining({
        eventId: "review-event-0002",
        revision: 2,
        previousEventId: "review-event-0001",
        immutable: true,
      }),
    ]);
    expect(snapshot.reviews).toEqual([
      {
        reviewId: "review-0001",
        revision: 2,
        issueCode: "MISALIGNED_BOX",
        comments: ["向车头方向平移 0.3m"],
        status: "open",
        severity: null,
        suggestion: null,
      },
    ]);
  });

  it("rejects empty semantic values without changing the committed state", async () => {
    const store = createStore();
    await store.append(command(0));
    const before = await store.snapshot();

    await expect(
      store.append({
        ...command(1),
        eventId: "review-event-empty",
        payload: { issueCode: null, comment: "   ", status: null, suggestion: null },
      }),
    ).rejects.toThrow(/comment/i);

    expect(await store.snapshot()).toEqual(before);
  });
});

describe("review diff export and import", () => {
  it("round-trips the semantic history and deduplicates a repeated package", async () => {
    const source = createStore();
    await source.append(command(0));
    await source.append(command(1));

    const envelope = await source.exportDiff({
      exportId: "export-review-0001",
      createdAt: "2026-08-04T08:02:00.000Z",
      sinceSequence: 0,
    });
    const destination = new ReviewStore({
      workspaceId: "workspace-review-import",
      datasetDigest: fixture.datasetDigest,
      persistence: new MemoryReviewPersistence(),
    });
    const first = await destination.importDiff(envelope);
    const repeated = await destination.importDiff(envelope);

    expect(envelope).toMatchObject({
      schemaVersion: "export-envelope.v1",
      eventCount: 2,
      mediaIncluded: false,
      absolutePathsIncluded: false,
    });
    expect(envelope.contentDigest).toMatch(/^sha256:[a-f0-9]{64}$/);
    expect(envelope.dedupeKey).toBe(envelope.contentDigest);
    expect(first).toEqual({ status: "imported", imported: 2, duplicates: 0 });
    expect(repeated).toEqual({ status: "duplicate", imported: 0, duplicates: 2 });
    expect((await destination.snapshot()).reviews).toEqual((await source.snapshot()).reviews);
  });

  it("rejects null and digest-corrupted imports atomically", async () => {
    const source = createStore();
    await source.append(command(0));
    const envelope = await source.exportDiff({
      exportId: "export-review-corrupt",
      createdAt: "2026-08-04T08:02:00.000Z",
      sinceSequence: 0,
    });
    const destination = createStore();
    const before = await destination.snapshot();

    await expect(destination.importDiff(null)).rejects.toThrow(/export/i);
    await expect(
      destination.importDiff({ ...envelope, contentDigest: `sha256:${"0".repeat(64)}` }),
    ).rejects.toThrow(/digest/i);

    expect(await destination.snapshot()).toEqual(before);
  });
});
