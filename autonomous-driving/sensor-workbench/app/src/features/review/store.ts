import {
  EXPORT_ENVELOPE_VERSION,
  REVIEW_EVENT_VERSION,
  parseExportEnvelopeWire,
  parseReviewEventWire,
  toExportEnvelopeWire,
  toReviewEventWire,
  type ExportEnvelopeV1,
  type ExportEnvelopeWireV1,
  type ReviewEventTypeV1,
  type ReviewEventV1,
  type ReviewPayloadV1,
  type ReviewSeverityV1,
  type ReviewTargetV1,
} from "../../contracts";
import { sha256, stableJson } from "./digest";
import {
  AtomicWriteConflictError,
  type RecoveryResult,
  type ResetResult,
  type ReviewFaultPoint,
  type ReviewPersistence,
} from "./persistence";

const DIGEST_PATTERN = /^sha256:[a-f0-9]{64}$/;

export interface AppendReviewCommand {
  readonly eventId: string;
  readonly reviewId: string;
  readonly expectedRevision: number;
  readonly frameContextId: string;
  readonly target: ReviewTargetV1;
  readonly eventType: ReviewEventTypeV1;
  readonly occurredAt: string;
  readonly actorId: string;
  readonly payload: ReviewPayloadV1;
}

export interface ReviewStoreOptions {
  readonly workspaceId: string;
  readonly datasetDigest: string;
  readonly persistence: ReviewPersistence;
}

export interface FaultOptions {
  readonly faultAt?: ReviewFaultPoint;
}

export interface ExportDiffRequest {
  readonly exportId: string;
  readonly createdAt: string;
  readonly sinceSequence: number;
}

export type AppendResult =
  | { readonly status: "appended" | "duplicate"; readonly eventId: string; readonly revision: number }
  | {
      readonly status: "conflict";
      readonly reviewId: string;
      readonly expectedRevision: number;
      readonly actualRevision: number;
      readonly currentEventId: string | null;
    };

export type ImportResult =
  | { readonly status: "imported"; readonly imported: number; readonly duplicates: number }
  | { readonly status: "duplicate"; readonly imported: 0; readonly duplicates: number };

export interface ReviewProjection {
  readonly reviewId: string;
  readonly revision: number;
  readonly issueCode: string | null;
  readonly comments: readonly string[];
  readonly status: ReviewEventV1["payload"]["status"];
  readonly severity: ReviewSeverityV1 | null;
  readonly suggestion: string | null;
}

export interface ReviewSnapshot {
  readonly events: readonly ReviewEventV1[];
  readonly reviews: readonly ReviewProjection[];
  readonly sequence: number;
  readonly archivedExportIds: readonly string[];
  readonly importedContentDigests: readonly string[];
  readonly stateDigest: string;
}

interface StoredReviewWorkspace {
  readonly schema_version: "review-workspace.v1";
  readonly workspace_id: string;
  readonly dataset_digest: string;
  readonly events: readonly ReturnType<typeof toReviewEventWire>[];
  readonly exports: readonly ExportEnvelopeWireV1[];
  readonly imported_content_digests: readonly string[];
}

interface LoadedState {
  readonly serialized: string | null;
  readonly state: StoredReviewWorkspace;
  readonly events: readonly ReviewEventV1[];
  readonly exports: readonly ExportEnvelopeV1[];
}

function nonEmpty(value: string, field: string): string {
  if (!value.trim()) throw new TypeError(`${field} must not be empty`);
  return value;
}

function validateDigest(value: string, field: string): string {
  if (!DIGEST_PATTERN.test(value)) throw new TypeError(`${field} must be a lowercase SHA-256 digest`);
  return value;
}

function validateDate(value: string, field: string): string {
  if (!value || !Number.isFinite(Date.parse(value))) throw new TypeError(`${field} must be an ISO date-time`);
  return value;
}

function validateCommand(command: AppendReviewCommand): void {
  nonEmpty(command.eventId, "eventId");
  nonEmpty(command.reviewId, "reviewId");
  nonEmpty(command.frameContextId, "frameContextId");
  nonEmpty(command.target.stableId, "target.stableId");
  nonEmpty(command.actorId, "actorId");
  validateDate(command.occurredAt, "occurredAt");
  if (!Number.isInteger(command.expectedRevision) || command.expectedRevision < 0) {
    throw new TypeError("expectedRevision must be a non-negative integer");
  }
  const semanticField: Record<ReviewEventTypeV1, keyof ReviewPayloadV1> = {
    issue_created: "issueCode",
    comment_added: "comment",
    status_changed: "status",
    suggestion_changed: "suggestion",
  };
  const value = command.payload[semanticField[command.eventType]];
  if (value === null || (typeof value === "string" && !value.trim())) {
    throw new TypeError(`${semanticField[command.eventType]} must not be empty for ${command.eventType}`);
  }
}

function projectReviews(events: readonly ReviewEventV1[]): readonly ReviewProjection[] {
  const reviews = new Map<string, ReviewProjection>();
  for (const event of events) {
    const current = reviews.get(event.reviewId) ?? {
      reviewId: event.reviewId,
      revision: 0,
      issueCode: null,
      comments: [],
      status: null,
      suggestion: null,
      severity: null,
    };
    reviews.set(event.reviewId, {
      reviewId: event.reviewId,
      revision: event.revision,
      issueCode: event.payload.issueCode ?? current.issueCode,
      comments: event.payload.comment === null ? current.comments : [...current.comments, event.payload.comment],
      status: event.payload.status ?? current.status,
      suggestion: event.payload.suggestion ?? current.suggestion,
      severity: event.payload.severity ?? current.severity,
    });
  }
  return [...reviews.values()].sort((left, right) => left.reviewId.localeCompare(right.reviewId));
}

function buildEnvelopeDigestInput(envelope: Omit<ExportEnvelopeV1, "dedupeKey" | "contentDigest">): unknown {
  return {
    schema_version: envelope.schemaVersion,
    export_id: envelope.exportId,
    created_at: envelope.createdAt,
    source_workspace_id: envelope.sourceWorkspaceId,
    source_dataset_digest: envelope.sourceDatasetDigest,
    event_count: envelope.eventCount,
    events: envelope.events.map(toReviewEventWire),
    identities: envelope.identities.map((identity) => ({ event_id: identity.eventId, digest: identity.digest })),
    media_included: envelope.mediaIncluded,
    absolute_paths_included: envelope.absolutePathsIncluded,
  };
}

function normalizeEnvelope(input: unknown): ExportEnvelopeV1 {
  try {
    if (typeof input === "object" && input !== null && "schemaVersion" in input) {
      return parseExportEnvelopeWire(toExportEnvelopeWire(input as ExportEnvelopeV1));
    }
    return parseExportEnvelopeWire(input);
  } catch (error) {
    throw new TypeError(`invalid export envelope: ${error instanceof Error ? error.message : String(error)}`);
  }
}

export class ReviewStore {
  private queue: Promise<void> = Promise.resolve();
  private readonly workspaceId: string;
  private readonly datasetDigest: string;
  private readonly persistence: ReviewPersistence;

  constructor(options: ReviewStoreOptions) {
    this.workspaceId = nonEmpty(options.workspaceId, "workspaceId");
    this.datasetDigest = validateDigest(options.datasetDigest, "datasetDigest");
    this.persistence = options.persistence;
  }

  append(command: AppendReviewCommand, options: FaultOptions = {}): Promise<AppendResult> {
    return this.exclusive(async () => {
      validateCommand(command);
      return this.appendUnlocked(command, options);
    });
  }

  snapshot(): Promise<ReviewSnapshot> {
    return this.exclusive(async () => {
      const loaded = this.load();
      return this.snapshotOf(loaded);
    });
  }

  recover(): Promise<RecoveryResult> {
    return this.exclusive(async () => {
      const result = this.persistence.recover();
      this.load();
      return result;
    });
  }

  resetPending(): Promise<ResetResult> {
    return this.exclusive(async () => this.persistence.resetPending());
  }

  exportDiff(request: ExportDiffRequest, options: FaultOptions = {}): Promise<ExportEnvelopeV1> {
    nonEmpty(request.exportId, "exportId");
    validateDate(request.createdAt, "createdAt");
    if (!Number.isInteger(request.sinceSequence) || request.sinceSequence < 0) {
      throw new TypeError("sinceSequence must be a non-negative integer");
    }
    return this.exclusive(async () => {
      const loaded = this.load();
      if (request.sinceSequence > loaded.events.length) throw new RangeError("sinceSequence exceeds review history");
      const events = loaded.events.slice(request.sinceSequence);
      const identities = await Promise.all(
        events.map(async (event) => ({ eventId: event.eventId, digest: await sha256(toReviewEventWire(event)) })),
      );
      const withoutDigest = {
        schemaVersion: EXPORT_ENVELOPE_VERSION,
        exportId: request.exportId,
        createdAt: request.createdAt,
        sourceWorkspaceId: this.workspaceId,
        sourceDatasetDigest: this.datasetDigest,
        eventCount: events.length,
        events,
        identities,
        mediaIncluded: false as const,
        absolutePathsIncluded: false as const,
      };
      const contentDigest = await sha256(buildEnvelopeDigestInput(withoutDigest));
      const envelope: ExportEnvelopeV1 = {
        ...withoutDigest,
        dedupeKey: contentDigest,
        contentDigest,
      };
      const existing = loaded.exports.find((candidate) => candidate.exportId === request.exportId);
      if (existing) {
        if (stableJson(existing) !== stableJson(envelope)) throw new Error(`exportId ${request.exportId} is immutable`);
        return existing;
      }
      const next = { ...loaded.state, exports: [...loaded.state.exports, toExportEnvelopeWire(envelope)] };
      this.persistence.compareAndSwap(loaded.serialized, stableJson(next), options.faultAt);
      return envelope;
    });
  }

  importDiff(input: unknown, options: FaultOptions = {}): Promise<ImportResult> {
    return this.exclusive(async () => this.importUnlocked(input, options));
  }

  private async appendUnlocked(command: AppendReviewCommand, options: FaultOptions): Promise<AppendResult> {
    const normalizedPayload = { ...command.payload, severity: command.payload.severity ?? null };
    for (let attempt = 0; attempt < 2; attempt += 1) {
      const loaded = this.load();
      const existing = loaded.events.find((event) => event.eventId === command.eventId);
      if (existing) {
        const retryMatches =
          existing.reviewId === command.reviewId &&
          existing.revision === command.expectedRevision + 1 &&
          existing.frameContextId === command.frameContextId &&
          stableJson(existing.target) === stableJson(command.target) &&
          existing.eventType === command.eventType &&
          existing.occurredAt === command.occurredAt &&
          existing.actorId === command.actorId &&
          stableJson(existing.payload) === stableJson(normalizedPayload);
        if (!retryMatches) throw new Error(`eventId ${command.eventId} already identifies a different immutable event`);
        return { status: "duplicate", eventId: existing.eventId, revision: existing.revision };
      }
      const history = loaded.events.filter((event) => event.reviewId === command.reviewId);
      const current = history.at(-1) ?? null;
      const actualRevision = current?.revision ?? 0;
      if (command.expectedRevision !== actualRevision) {
        return {
          status: "conflict",
          reviewId: command.reviewId,
          expectedRevision: command.expectedRevision,
          actualRevision,
          currentEventId: current?.eventId ?? null,
        };
      }
      const event: ReviewEventV1 = {
        schemaVersion: REVIEW_EVENT_VERSION,
        eventId: command.eventId,
        reviewId: command.reviewId,
        revision: actualRevision + 1,
        previousEventId: current?.eventId ?? null,
        frameContextId: command.frameContextId,
        target: { ...command.target },
        eventType: command.eventType,
        occurredAt: command.occurredAt,
        actorId: command.actorId,
        payload: normalizedPayload,
        source: "user",
        immutable: true,
      };
      parseReviewEventWire(toReviewEventWire(event));
      const next = { ...loaded.state, events: [...loaded.state.events, toReviewEventWire(event)] };
      try {
        this.persistence.compareAndSwap(loaded.serialized, stableJson(next), options.faultAt);
        return { status: "appended", eventId: event.eventId, revision: event.revision };
      } catch (error) {
        if (!(error instanceof AtomicWriteConflictError) || attempt === 1) throw error;
      }
    }
    throw new Error("unreachable append retry state");
  }

  private async importUnlocked(input: unknown, options: FaultOptions): Promise<ImportResult> {
    const envelope = normalizeEnvelope(input);
    if (envelope.sourceDatasetDigest !== this.datasetDigest) throw new Error("export dataset digest does not match workspace");
    const expectedIdentities = await Promise.all(
      envelope.events.map(async (event) => ({ eventId: event.eventId, digest: await sha256(toReviewEventWire(event)) })),
    );
    if (stableJson(expectedIdentities) !== stableJson(envelope.identities)) {
      throw new Error("export event identity digest mismatch");
    }
    const { dedupeKey: _dedupeKey, contentDigest: _contentDigest, ...withoutDigest } = envelope;
    const expectedContentDigest = await sha256(buildEnvelopeDigestInput(withoutDigest));
    if (envelope.contentDigest !== expectedContentDigest || envelope.dedupeKey !== expectedContentDigest) {
      throw new Error("export content digest mismatch");
    }

    for (let attempt = 0; attempt < 2; attempt += 1) {
      const loaded = this.load();
      if (loaded.state.imported_content_digests.includes(envelope.contentDigest)) {
        return { status: "duplicate", imported: 0, duplicates: envelope.eventCount };
      }
      const nextEvents = [...loaded.events];
      let duplicates = 0;
      for (let index = 0; index < envelope.events.length; index += 1) {
        const event = envelope.events[index];
        const identity = envelope.identities[index];
        const existingIndex = nextEvents.findIndex((candidate) => candidate.eventId === event.eventId);
        if (existingIndex >= 0) {
          const existingDigest = await sha256(toReviewEventWire(nextEvents[existingIndex]));
          if (existingDigest !== identity.digest) throw new Error(`eventId ${event.eventId} has conflicting immutable content`);
          duplicates += 1;
          continue;
        }
        const current = nextEvents.filter((candidate) => candidate.reviewId === event.reviewId).at(-1) ?? null;
        if (event.revision !== (current?.revision ?? 0) + 1 || event.previousEventId !== (current?.eventId ?? null)) {
          throw new Error(`import event ${event.eventId} does not continue its revision chain`);
        }
        nextEvents.push(event);
      }
      const next: StoredReviewWorkspace = {
        ...loaded.state,
        events: nextEvents.map(toReviewEventWire),
        imported_content_digests: [...loaded.state.imported_content_digests, envelope.contentDigest].sort(),
      };
      try {
        this.persistence.compareAndSwap(loaded.serialized, stableJson(next), options.faultAt);
        return { status: "imported", imported: envelope.eventCount - duplicates, duplicates };
      } catch (error) {
        if (!(error instanceof AtomicWriteConflictError) || attempt === 1) throw error;
      }
    }
    throw new Error("unreachable import retry state");
  }

  private load(): LoadedState {
    const serialized = this.persistence.readCommitted();
    if (serialized === null) {
      return {
        serialized,
        state: {
          schema_version: "review-workspace.v1",
          workspace_id: this.workspaceId,
          dataset_digest: this.datasetDigest,
          events: [],
          exports: [],
          imported_content_digests: [],
        },
        events: [],
        exports: [],
      };
    }
    let raw: unknown;
    try {
      raw = JSON.parse(serialized);
    } catch {
      throw new TypeError("committed review state is corrupted JSON");
    }
    if (typeof raw !== "object" || raw === null) throw new TypeError("committed review state must be an object");
    const value = raw as Record<string, unknown>;
    if (
      value.schema_version !== "review-workspace.v1" ||
      value.workspace_id !== this.workspaceId ||
      value.dataset_digest !== this.datasetDigest ||
      !Array.isArray(value.events) ||
      !Array.isArray(value.exports) ||
      !Array.isArray(value.imported_content_digests)
    ) {
      throw new TypeError("committed review state does not match this workspace contract");
    }
    const events = value.events.map(parseReviewEventWire);
    const exports = value.exports.map(parseExportEnvelopeWire);
    const eventIds = new Set<string>();
    const revisions = new Map<string, ReviewEventV1>();
    for (const event of events) {
      if (eventIds.has(event.eventId)) throw new TypeError(`duplicate committed eventId ${event.eventId}`);
      eventIds.add(event.eventId);
      const previous = revisions.get(event.reviewId) ?? null;
      if (event.revision !== (previous?.revision ?? 0) + 1 || event.previousEventId !== (previous?.eventId ?? null)) {
        throw new TypeError(`committed review chain is invalid at ${event.eventId}`);
      }
      revisions.set(event.reviewId, event);
    }
    const importedContentDigests = value.imported_content_digests.map((digest, index) => {
      if (typeof digest !== "string") throw new TypeError(`imported digest ${index} must be a string`);
      return validateDigest(digest, `imported digest ${index}`);
    });
    const state = raw as StoredReviewWorkspace;
    return { serialized, state, events, exports };
  }

  private async snapshotOf(loaded: LoadedState): Promise<ReviewSnapshot> {
    const reviews = projectReviews(loaded.events);
    const stateDigest = await sha256({ events: loaded.events.map(toReviewEventWire), reviews });
    return {
      events: loaded.events,
      reviews,
      sequence: loaded.events.length,
      archivedExportIds: loaded.exports.map((envelope) => envelope.exportId),
      importedContentDigests: [...loaded.state.imported_content_digests],
      stateDigest,
    };
  }

  private exclusive<T>(operation: () => Promise<T>): Promise<T> {
    const result = this.queue.then(operation, operation);
    this.queue = result.then(
      () => undefined,
      () => undefined,
    );
    return result;
  }
}
