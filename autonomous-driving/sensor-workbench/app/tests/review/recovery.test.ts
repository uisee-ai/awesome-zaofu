import { describe, expect, it } from "vitest";

import fixture from "../fixtures/synthetic/review/review-fixture.json";
import {
  MemoryReviewPersistence,
  ReviewStore,
  type AppendReviewCommand,
} from "../../src/features/review";

function issue(eventId = "review-event-recovery"): AppendReviewCommand {
  return {
    eventId,
    reviewId: "review-recovery",
    expectedRevision: 0,
    frameContextId: fixture.frameContextId,
    target: { kind: "annotation", stableId: fixture.target.stableId },
    eventType: "issue_created",
    occurredAt: "2026-08-04T09:00:00.000Z",
    actorId: fixture.actorId,
    payload: { issueCode: "OCCLUDED", comment: null, status: "open", suggestion: null },
  };
}

function createStore(persistence: MemoryReviewPersistence) {
  return new ReviewStore({
    workspaceId: fixture.workspaceId,
    datasetDigest: fixture.datasetDigest,
    persistence,
  });
}

describe("write-ahead recovery", () => {
  it("keeps a prepared partial write invisible, rolls it forward, and makes retry idempotent", async () => {
    const persistence = new MemoryReviewPersistence();
    const interrupted = createStore(persistence);

    await expect(interrupted.append(issue(), { faultAt: "after_prepare" })).rejects.toThrow(/interrupted/i);
    expect((await interrupted.snapshot()).events).toEqual([]);

    const restarted = createStore(persistence);
    expect(await restarted.recover()).toEqual({ action: "rolled_forward" });
    expect((await restarted.snapshot()).events.map((event) => event.eventId)).toEqual(["review-event-recovery"]);
    expect(await restarted.append(issue())).toMatchObject({ status: "duplicate", revision: 1 });
  });

  it("resets an uncommitted journal and permits an exact retry", async () => {
    const persistence = new MemoryReviewPersistence();
    const store = createStore(persistence);

    await expect(store.append(issue("review-event-reset"), { faultAt: "after_prepare" })).rejects.toThrow();
    expect(await store.resetPending()).toEqual({ action: "discarded" });
    expect(await store.append(issue("review-event-reset"))).toMatchObject({ status: "appended", revision: 1 });
  });

  it("recognizes an interruption after commit as a complete append", async () => {
    const persistence = new MemoryReviewPersistence();
    const store = createStore(persistence);

    await expect(store.append(issue("review-event-committed"), { faultAt: "after_commit" })).rejects.toThrow();
    expect((await store.snapshot()).events.map((event) => event.eventId)).toEqual(["review-event-committed"]);
    expect(await store.recover()).toEqual({ action: "cleared_committed_journal" });
  });

  it("publishes an export archive only after recovery completes its prepared transaction", async () => {
    const persistence = new MemoryReviewPersistence();
    const store = createStore(persistence);
    await store.append(issue("review-event-export"));

    await expect(
      store.exportDiff(
        { exportId: "export-recovery", createdAt: "2026-08-04T09:01:00.000Z", sinceSequence: 0 },
        { faultAt: "after_prepare" },
      ),
    ).rejects.toThrow(/interrupted/i);
    expect((await store.snapshot()).archivedExportIds).toEqual([]);

    expect(await store.recover()).toEqual({ action: "rolled_forward" });
    expect((await store.snapshot()).archivedExportIds).toEqual(["export-recovery"]);
  });

  it("imports no half-history and deduplicates the package after recovery", async () => {
    const source = createStore(new MemoryReviewPersistence());
    await source.append(issue("review-event-import"));
    const envelope = await source.exportDiff({
      exportId: "export-import-recovery",
      createdAt: "2026-08-04T09:02:00.000Z",
      sinceSequence: 0,
    });
    const destinationPersistence = new MemoryReviewPersistence();
    const destination = createStore(destinationPersistence);

    await expect(destination.importDiff(envelope, { faultAt: "after_prepare" })).rejects.toThrow(/interrupted/i);
    expect((await destination.snapshot()).events).toEqual([]);

    expect(await destination.recover()).toEqual({ action: "rolled_forward" });
    expect((await destination.snapshot()).events.map((event) => event.eventId)).toEqual(["review-event-import"]);
    expect(await destination.importDiff(envelope)).toEqual({ status: "duplicate", imported: 0, duplicates: 1 });
  });

  it("serializes concurrent revisions into one append and one deterministic conflict", async () => {
    const persistence = new MemoryReviewPersistence();
    const store = createStore(persistence);
    await store.append(issue("review-event-root"));

    const statusChange: AppendReviewCommand = {
      ...issue("review-event-status"),
      expectedRevision: 1,
      eventType: "status_changed",
      payload: { issueCode: null, comment: null, status: "resolved", suggestion: null },
    };
    const suggestionChange: AppendReviewCommand = {
      ...issue("review-event-suggestion"),
      expectedRevision: 1,
      eventType: "suggestion_changed",
      payload: { issueCode: null, comment: null, status: null, suggestion: "保留原标注" },
    };

    const [winner, loser] = await Promise.all([store.append(statusChange), store.append(suggestionChange)]);

    expect(winner).toMatchObject({ status: "appended", revision: 2 });
    expect(loser).toEqual({
      status: "conflict",
      reviewId: "review-recovery",
      expectedRevision: 1,
      actualRevision: 2,
      currentEventId: "review-event-status",
    });
    expect((await store.snapshot()).events.map((event) => event.eventId)).toEqual([
      "review-event-root",
      "review-event-status",
    ]);
  });
});
