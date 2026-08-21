export const ADAPTER_CONTRACT_VERSION = "adapter.v1" as const;
export const FRAME_CONTEXT_VERSION = "frame-context.v1" as const;
export const WORKSPACE_CONTRACT_VERSION = "workspace.v1" as const;
export const REVIEW_EVENT_VERSION = "review-event.v1" as const;
export const EXPORT_ENVELOPE_VERSION = "export-envelope.v1" as const;
export const EVIDENCE_RECEIPT_VERSION = "evidence-receipt.v1" as const;

export type DatasetKindV1 = "nuscenes" | "openlane" | "synthetic";
export type AdapterCapabilityV1 = "scan" | "browse" | "search" | "coordinate_projection" | "review";
export type UnsupportedCapabilityV1 = "model_comparison" | "official_evaluation" | "raw_data_mutation";

export interface AdapterDescriptorV1 {
  readonly schemaVersion: typeof ADAPTER_CONTRACT_VERSION;
  readonly adapterId: string;
  readonly datasetKind: DatasetKindV1;
  readonly datasetVersion: string;
  readonly displayName: string;
  readonly capabilities: readonly AdapterCapabilityV1[];
  readonly unsupportedCapabilities: readonly UnsupportedCapabilityV1[];
  readonly fallbackBehavior: "report_unsupported";
  readonly ignoredSourceFields: readonly string[];
  readonly readOnly: true;
}

export interface AdapterDescriptorWireV1 {
  readonly schema_version: typeof ADAPTER_CONTRACT_VERSION;
  readonly adapter_id: string;
  readonly dataset_kind: DatasetKindV1;
  readonly dataset_version: string;
  readonly display_name: string;
  readonly capabilities: readonly AdapterCapabilityV1[];
  readonly unsupported_capabilities: readonly UnsupportedCapabilityV1[];
  readonly fallback_behavior: "report_unsupported";
  readonly ignored_source_fields: readonly string[];
  readonly read_only: true;
}

export interface DataRootRefV1 {
  readonly rootId: string;
  readonly digest: string;
  readonly mode: "read-only";
}

export interface DatasetScanResultV1 {
  readonly datasetKind: DatasetKindV1;
  readonly datasetVersion: string;
  readonly rootDigest: string;
  readonly missingAssets: readonly string[];
  readonly affectedScopes: readonly string[];
}

export interface FrameRequestV1 {
  readonly sceneRef: string;
  readonly frameRef: string;
  readonly generation: number;
}

export interface SearchQueryV1 {
  readonly text: string;
  readonly derivedFilters: Readonly<Record<string, string>>;
  readonly ruleVersion: string;
}

export interface SearchResultV1 {
  readonly stableId: string;
  readonly sceneRef: string;
  readonly frameRef: string;
  readonly sourceText: string;
  readonly derived: boolean;
  readonly derivationSource: string | null;
  readonly ruleVersion: string;
}

export interface SensorWorkbenchAdapterV1<TFrame = unknown> {
  readonly descriptor: AdapterDescriptorV1;
  scan(root: DataRootRefV1, signal?: AbortSignal): Promise<DatasetScanResultV1>;
  loadFrame(request: FrameRequestV1, signal?: AbortSignal): Promise<TFrame>;
  search(query: SearchQueryV1, signal?: AbortSignal): Promise<readonly SearchResultV1[]>;
}

export type SensorModalityV1 = "camera" | "lidar";
export type SensorAvailabilityV1 = "available" | "missing";
export type CoordinateFrameV1 = "sensor" | "ego" | "global";

export interface SensorFrameV1 {
  readonly sensorId: string;
  readonly modality: SensorModalityV1;
  readonly timestampUs: number;
  readonly deltaMs: number;
  readonly availability: SensorAvailabilityV1;
  readonly assetRef: string | null;
}

export interface SensorFrameWireV1 {
  readonly sensor_id: string;
  readonly modality: SensorModalityV1;
  readonly timestamp_us: number;
  readonly delta_ms: number;
  readonly availability: SensorAvailabilityV1;
  readonly asset_ref: string | null;
}

export interface FrameContextV1 {
  readonly schemaVersion: typeof FRAME_CONTEXT_VERSION;
  readonly frameContextId: string;
  readonly generation: number;
  readonly adapterId: string;
  readonly datasetKind: DatasetKindV1;
  readonly datasetVersion: string;
  readonly sceneRef: string;
  readonly frameRef: string;
  readonly keyframe: boolean;
  readonly timestampUs: number;
  readonly primarySensorId: string;
  readonly coordinateFrame: CoordinateFrameV1;
  readonly sensorFrames: readonly SensorFrameV1[];
}

export interface FrameContextWireV1 {
  readonly schema_version: typeof FRAME_CONTEXT_VERSION;
  readonly frame_context_id: string;
  readonly generation: number;
  readonly adapter_id: string;
  readonly dataset_kind: DatasetKindV1;
  readonly dataset_version: string;
  readonly scene_ref: string;
  readonly frame_ref: string;
  readonly keyframe: boolean;
  readonly timestamp_us: number;
  readonly primary_sensor_id: string;
  readonly coordinate_frame: CoordinateFrameV1;
  readonly sensor_frames: readonly SensorFrameWireV1[];
}

export interface WorkspacePathsV1 {
  readonly indexDirectory: string;
  readonly cacheDirectory: string;
  readonly reviewLog: string;
  readonly exportDirectory: string;
  readonly evidenceDirectory: string;
}

export interface WorkspacePathsWireV1 {
  readonly index_directory: string;
  readonly cache_directory: string;
  readonly review_log: string;
  readonly export_directory: string;
  readonly evidence_directory: string;
}

export interface WorkspaceV1 {
  readonly schemaVersion: typeof WORKSPACE_CONTRACT_VERSION;
  readonly workspaceId: string;
  readonly createdAt: string;
  readonly dataRootDigest: string;
  readonly dataRootMode: "read-only";
  readonly mutableRootMode: "workspace-only";
  readonly maxCacheBytes: number;
  readonly paths: WorkspacePathsV1;
}

export interface WorkspaceWireV1 {
  readonly schema_version: typeof WORKSPACE_CONTRACT_VERSION;
  readonly workspace_id: string;
  readonly created_at: string;
  readonly data_root_digest: string;
  readonly data_root_mode: "read-only";
  readonly mutable_root_mode: "workspace-only";
  readonly max_cache_bytes: number;
  readonly paths: WorkspacePathsWireV1;
}

export type ReviewTargetKindV1 = "annotation" | "lane" | "frame";
export type ReviewEventTypeV1 = "issue_created" | "comment_added" | "status_changed" | "suggestion_changed";
export type ReviewStatusV1 = "pending" | "needs_fix" | "accepted" | "resolved" | "open" | "dismissed";
export type ReviewSeverityV1 = "low" | "medium" | "high" | "critical";

export interface ReviewTargetV1 {
  readonly kind: ReviewTargetKindV1;
  readonly stableId: string;
}

export interface ReviewPayloadV1 {
  readonly issueCode: string | null;
  readonly comment: string | null;
  readonly status: ReviewStatusV1 | null;
  readonly suggestion: string | null;
  readonly severity?: ReviewSeverityV1 | null;
}

export interface ReviewEventV1 {
  readonly schemaVersion: typeof REVIEW_EVENT_VERSION;
  readonly eventId: string;
  readonly reviewId: string;
  readonly revision: number;
  readonly previousEventId: string | null;
  readonly frameContextId: string;
  readonly target: ReviewTargetV1;
  readonly eventType: ReviewEventTypeV1;
  readonly occurredAt: string;
  readonly actorId: string;
  readonly payload: ReviewPayloadV1;
  readonly source: "user" | "import";
  readonly immutable: true;
}

export interface ReviewEventWireV1 {
  readonly schema_version: typeof REVIEW_EVENT_VERSION;
  readonly event_id: string;
  readonly review_id: string;
  readonly revision: number;
  readonly previous_event_id: string | null;
  readonly frame_context_id: string;
  readonly target: { readonly kind: ReviewTargetKindV1; readonly stable_id: string };
  readonly event_type: ReviewEventTypeV1;
  readonly occurred_at: string;
  readonly actor_id: string;
  readonly payload: {
    readonly issue_code: string | null;
    readonly comment: string | null;
    readonly status: ReviewStatusV1 | null;
    readonly suggestion: string | null;
    readonly severity: ReviewSeverityV1 | null;
  };
  readonly source: "user" | "import";
  readonly immutable: true;
}

export interface ExportIdentityV1 {
  readonly eventId: string;
  readonly digest: string;
}

export interface ExportEnvelopeV1 {
  readonly schemaVersion: typeof EXPORT_ENVELOPE_VERSION;
  readonly exportId: string;
  readonly createdAt: string;
  readonly sourceWorkspaceId: string;
  readonly sourceDatasetDigest: string;
  readonly eventCount: number;
  readonly events: readonly ReviewEventV1[];
  readonly identities: readonly ExportIdentityV1[];
  readonly mediaIncluded: false;
  readonly absolutePathsIncluded: false;
  readonly dedupeKey: string;
  readonly contentDigest: string;
}

export interface ExportEnvelopeWireV1 {
  readonly schema_version: typeof EXPORT_ENVELOPE_VERSION;
  readonly export_id: string;
  readonly created_at: string;
  readonly source_workspace_id: string;
  readonly source_dataset_digest: string;
  readonly event_count: number;
  readonly events: readonly ReviewEventWireV1[];
  readonly identities: readonly { readonly event_id: string; readonly digest: string }[];
  readonly media_included: false;
  readonly absolute_paths_included: false;
  readonly dedupe_key: string;
  readonly content_digest: string;
}

export type EvidenceExitStatusV1 = "passed" | "failed" | "interrupted";
export type EvidenceResultV1 = EvidenceExitStatusV1;

export interface EvidenceReceiptV1 {
  readonly schemaVersion: typeof EVIDENCE_RECEIPT_VERSION;
  readonly receiptId: string;
  readonly commandId: string;
  readonly sourceCommit: string;
  readonly productionBuildDigest: string;
  readonly runner: { readonly name: string; readonly version: string };
  readonly browser: { readonly name: string; readonly version: string };
  readonly fixture: { readonly kind: "synthetic" | "nuscenes" | "openlane"; readonly digest: string };
  readonly startedAt: string;
  readonly finishedAt: string;
  readonly exitStatus: EvidenceExitStatusV1;
  readonly exitCode: number;
  readonly dataRootBeforeDigest: string;
  readonly dataRootAfterDigest: string;
  readonly artifacts: readonly { readonly kind: string; readonly digest: string; readonly redacted: boolean }[];
  readonly network: { readonly loopbackOnly: boolean; readonly nonLoopbackRequests: readonly string[] };
  readonly result: EvidenceResultV1;
}

export interface EvidenceReceiptWireV1 {
  readonly schema_version: typeof EVIDENCE_RECEIPT_VERSION;
  readonly receipt_id: string;
  readonly command_id: string;
  readonly source_commit: string;
  readonly production_build_digest: string;
  readonly runner: { readonly name: string; readonly version: string };
  readonly browser: { readonly name: string; readonly version: string };
  readonly fixture: { readonly kind: "synthetic" | "nuscenes" | "openlane"; readonly digest: string };
  readonly started_at: string;
  readonly finished_at: string;
  readonly exit_status: EvidenceExitStatusV1;
  readonly exit_code: number;
  readonly data_root_before_digest: string;
  readonly data_root_after_digest: string;
  readonly artifacts: readonly { readonly kind: string; readonly digest: string; readonly redacted: boolean }[];
  readonly network: { readonly loopback_only: boolean; readonly non_loopback_requests: readonly string[] };
  readonly result: EvidenceResultV1;
}

type UnknownRecord = Record<string, unknown>;

function record(value: unknown, path: string): UnknownRecord {
  if (typeof value !== "object" || value === null || Array.isArray(value)) throw new TypeError(`${path} must be an object`);
  return value as UnknownRecord;
}

function stringValue(value: unknown, path: string): string {
  if (typeof value !== "string" || value.length === 0) throw new TypeError(`${path} must be a non-empty string`);
  return value;
}

function nullableString(value: unknown, path: string): string | null {
  if (value === null) return null;
  return stringValue(value, path);
}

function booleanValue(value: unknown, path: string): boolean {
  if (typeof value !== "boolean") throw new TypeError(`${path} must be a boolean`);
  return value;
}

function integerValue(value: unknown, path: string, minimum = Number.MIN_SAFE_INTEGER): number {
  if (!Number.isSafeInteger(value) || (value as number) < minimum) throw new TypeError(`${path} must be a safe integer >= ${minimum}`);
  return value as number;
}

function numberValue(value: unknown, path: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) throw new TypeError(`${path} must be a finite number`);
  return value;
}

function literal<T extends string | boolean>(value: unknown, expected: T, path: string): T {
  if (value !== expected) throw new TypeError(`${path} must be ${JSON.stringify(expected)}`);
  return expected;
}

function oneOf<T extends string>(value: unknown, allowed: readonly T[], path: string): T {
  if (typeof value !== "string" || !allowed.includes(value as T)) {
    throw new TypeError(`${path} must be one of ${allowed.join(", ")}`);
  }
  return value as T;
}

function arrayValue(value: unknown, path: string): readonly unknown[] {
  if (!Array.isArray(value)) throw new TypeError(`${path} must be an array`);
  return value;
}

function stringArray<T extends string>(value: unknown, allowed: readonly T[] | null, path: string): readonly T[] {
  return arrayValue(value, path).map((item, index) =>
    allowed ? oneOf(item, allowed, `${path}[${index}]`) : (stringValue(item, `${path}[${index}]`) as T),
  );
}

function digest(value: unknown, path: string): string {
  const parsed = stringValue(value, path);
  if (!/^sha256:[0-9a-f]{64}$/.test(parsed)) throw new TypeError(`${path} must be a sha256 digest`);
  return parsed;
}

function isoDate(value: unknown, path: string): string {
  const parsed = stringValue(value, path);
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{3})?Z$/.test(parsed) || Number.isNaN(Date.parse(parsed))) {
    throw new TypeError(`${path} must be a UTC RFC 3339 timestamp`);
  }
  return parsed;
}

function relativePath(value: unknown, path: string): string {
  const parsed = stringValue(value, path);
  if (parsed.startsWith("/") || parsed.startsWith("\\") || /^[A-Za-z]:[\\/]/.test(parsed) || parsed.split(/[\\/]/).includes("..")) {
    throw new TypeError(`${path} must be workspace-relative`);
  }
  return parsed;
}

const datasetKinds = ["nuscenes", "openlane", "synthetic"] as const;
const adapterCapabilities = ["scan", "browse", "search", "coordinate_projection", "review"] as const;
const unsupportedCapabilities = ["model_comparison", "official_evaluation", "raw_data_mutation"] as const;
const sensorModalities = ["camera", "lidar"] as const;
const sensorAvailabilities = ["available", "missing"] as const;
const coordinateFrames = ["sensor", "ego", "global"] as const;
const reviewTargetKinds = ["annotation", "lane", "frame"] as const;
const reviewEventTypes = ["issue_created", "comment_added", "status_changed", "suggestion_changed"] as const;
const reviewStatuses = ["pending", "needs_fix", "accepted", "resolved", "open", "dismissed"] as const;
const reviewSeverities = ["low", "medium", "high", "critical"] as const;
const evidenceStatuses = ["passed", "failed", "interrupted"] as const;

export function toAdapterDescriptorWire(value: AdapterDescriptorV1): AdapterDescriptorWireV1 {
  return {
    schema_version: value.schemaVersion,
    adapter_id: value.adapterId,
    dataset_kind: value.datasetKind,
    dataset_version: value.datasetVersion,
    display_name: value.displayName,
    capabilities: [...value.capabilities],
    unsupported_capabilities: [...value.unsupportedCapabilities],
    fallback_behavior: value.fallbackBehavior,
    ignored_source_fields: [...value.ignoredSourceFields],
    read_only: value.readOnly,
  };
}

export function parseAdapterDescriptorWire(input: unknown): AdapterDescriptorV1 {
  const value = record(input, "adapter");
  return {
    schemaVersion: literal(value.schema_version, ADAPTER_CONTRACT_VERSION, "adapter.schema_version"),
    adapterId: stringValue(value.adapter_id, "adapter.adapter_id"),
    datasetKind: oneOf(value.dataset_kind, datasetKinds, "adapter.dataset_kind"),
    datasetVersion: stringValue(value.dataset_version, "adapter.dataset_version"),
    displayName: stringValue(value.display_name, "adapter.display_name"),
    capabilities: stringArray(value.capabilities, adapterCapabilities, "adapter.capabilities"),
    unsupportedCapabilities: stringArray(
      value.unsupported_capabilities,
      unsupportedCapabilities,
      "adapter.unsupported_capabilities",
    ),
    fallbackBehavior: literal(value.fallback_behavior, "report_unsupported", "adapter.fallback_behavior"),
    ignoredSourceFields: stringArray(value.ignored_source_fields, null, "adapter.ignored_source_fields"),
    readOnly: literal(value.read_only, true, "adapter.read_only"),
  };
}

function toSensorFrameWire(value: SensorFrameV1): SensorFrameWireV1 {
  return {
    sensor_id: value.sensorId,
    modality: value.modality,
    timestamp_us: value.timestampUs,
    delta_ms: value.deltaMs,
    availability: value.availability,
    asset_ref: value.assetRef,
  };
}

function parseSensorFrameWire(input: unknown, path: string): SensorFrameV1 {
  const value = record(input, path);
  const availability = oneOf(value.availability, sensorAvailabilities, `${path}.availability`);
  const assetRef = nullableString(value.asset_ref, `${path}.asset_ref`);
  if ((availability === "missing") !== (assetRef === null)) {
    throw new TypeError(`${path}.asset_ref must be null exactly when availability is missing`);
  }
  return {
    sensorId: stringValue(value.sensor_id, `${path}.sensor_id`),
    modality: oneOf(value.modality, sensorModalities, `${path}.modality`),
    timestampUs: integerValue(value.timestamp_us, `${path}.timestamp_us`, 0),
    deltaMs: numberValue(value.delta_ms, `${path}.delta_ms`),
    availability,
    assetRef,
  };
}

export function toFrameContextWire(value: FrameContextV1): FrameContextWireV1 {
  return {
    schema_version: value.schemaVersion,
    frame_context_id: value.frameContextId,
    generation: value.generation,
    adapter_id: value.adapterId,
    dataset_kind: value.datasetKind,
    dataset_version: value.datasetVersion,
    scene_ref: value.sceneRef,
    frame_ref: value.frameRef,
    keyframe: value.keyframe,
    timestamp_us: value.timestampUs,
    primary_sensor_id: value.primarySensorId,
    coordinate_frame: value.coordinateFrame,
    sensor_frames: value.sensorFrames.map(toSensorFrameWire),
  };
}

export function parseFrameContextWire(input: unknown): FrameContextV1 {
  const value = record(input, "frame_context");
  const sensorFrames = arrayValue(value.sensor_frames, "frame_context.sensor_frames").map((item, index) =>
    parseSensorFrameWire(item, `frame_context.sensor_frames[${index}]`),
  );
  if (sensorFrames.length === 0) throw new TypeError("frame_context.sensor_frames must not be empty");
  const primarySensorId = stringValue(value.primary_sensor_id, "frame_context.primary_sensor_id");
  if (!sensorFrames.some((sensor) => sensor.sensorId === primarySensorId)) {
    throw new TypeError("frame_context.primary_sensor_id must identify a sensor_frames entry");
  }
  return {
    schemaVersion: literal(value.schema_version, FRAME_CONTEXT_VERSION, "frame_context.schema_version"),
    frameContextId: stringValue(value.frame_context_id, "frame_context.frame_context_id"),
    generation: integerValue(value.generation, "frame_context.generation", 0),
    adapterId: stringValue(value.adapter_id, "frame_context.adapter_id"),
    datasetKind: oneOf(value.dataset_kind, datasetKinds, "frame_context.dataset_kind"),
    datasetVersion: stringValue(value.dataset_version, "frame_context.dataset_version"),
    sceneRef: stringValue(value.scene_ref, "frame_context.scene_ref"),
    frameRef: stringValue(value.frame_ref, "frame_context.frame_ref"),
    keyframe: booleanValue(value.keyframe, "frame_context.keyframe"),
    timestampUs: integerValue(value.timestamp_us, "frame_context.timestamp_us", 0),
    primarySensorId,
    coordinateFrame: oneOf(value.coordinate_frame, coordinateFrames, "frame_context.coordinate_frame"),
    sensorFrames,
  };
}

export function toWorkspaceWire(value: WorkspaceV1): WorkspaceWireV1 {
  return {
    schema_version: value.schemaVersion,
    workspace_id: value.workspaceId,
    created_at: value.createdAt,
    data_root_digest: value.dataRootDigest,
    data_root_mode: value.dataRootMode,
    mutable_root_mode: value.mutableRootMode,
    max_cache_bytes: value.maxCacheBytes,
    paths: {
      index_directory: value.paths.indexDirectory,
      cache_directory: value.paths.cacheDirectory,
      review_log: value.paths.reviewLog,
      export_directory: value.paths.exportDirectory,
      evidence_directory: value.paths.evidenceDirectory,
    },
  };
}

export function parseWorkspaceWire(input: unknown): WorkspaceV1 {
  const value = record(input, "workspace");
  const paths = record(value.paths, "workspace.paths");
  return {
    schemaVersion: literal(value.schema_version, WORKSPACE_CONTRACT_VERSION, "workspace.schema_version"),
    workspaceId: stringValue(value.workspace_id, "workspace.workspace_id"),
    createdAt: isoDate(value.created_at, "workspace.created_at"),
    dataRootDigest: digest(value.data_root_digest, "workspace.data_root_digest"),
    dataRootMode: literal(value.data_root_mode, "read-only", "workspace.data_root_mode"),
    mutableRootMode: literal(value.mutable_root_mode, "workspace-only", "workspace.mutable_root_mode"),
    maxCacheBytes: integerValue(value.max_cache_bytes, "workspace.max_cache_bytes", 1),
    paths: {
      indexDirectory: relativePath(paths.index_directory, "workspace.paths.index_directory"),
      cacheDirectory: relativePath(paths.cache_directory, "workspace.paths.cache_directory"),
      reviewLog: relativePath(paths.review_log, "workspace.paths.review_log"),
      exportDirectory: relativePath(paths.export_directory, "workspace.paths.export_directory"),
      evidenceDirectory: relativePath(paths.evidence_directory, "workspace.paths.evidence_directory"),
    },
  };
}

export function toReviewEventWire(value: ReviewEventV1): ReviewEventWireV1 {
  return {
    schema_version: value.schemaVersion,
    event_id: value.eventId,
    review_id: value.reviewId,
    revision: value.revision,
    previous_event_id: value.previousEventId,
    frame_context_id: value.frameContextId,
    target: { kind: value.target.kind, stable_id: value.target.stableId },
    event_type: value.eventType,
    occurred_at: value.occurredAt,
    actor_id: value.actorId,
    payload: {
      issue_code: value.payload.issueCode,
      comment: value.payload.comment,
      status: value.payload.status,
      suggestion: value.payload.suggestion,
      severity: value.payload.severity ?? null,
    },
    source: value.source,
    immutable: value.immutable,
  };
}

export function parseReviewEventWire(input: unknown): ReviewEventV1 {
  const value = record(input, "review_event");
  const target = record(value.target, "review_event.target");
  const payload = record(value.payload, "review_event.payload");
  const rawStatus = payload.status;
  return {
    schemaVersion: literal(value.schema_version, REVIEW_EVENT_VERSION, "review_event.schema_version"),
    eventId: stringValue(value.event_id, "review_event.event_id"),
    reviewId: stringValue(value.review_id, "review_event.review_id"),
    revision: integerValue(value.revision, "review_event.revision", 1),
    previousEventId: nullableString(value.previous_event_id, "review_event.previous_event_id"),
    frameContextId: stringValue(value.frame_context_id, "review_event.frame_context_id"),
    target: {
      kind: oneOf(target.kind, reviewTargetKinds, "review_event.target.kind"),
      stableId: stringValue(target.stable_id, "review_event.target.stable_id"),
    },
    eventType: oneOf(value.event_type, reviewEventTypes, "review_event.event_type"),
    occurredAt: isoDate(value.occurred_at, "review_event.occurred_at"),
    actorId: stringValue(value.actor_id, "review_event.actor_id"),
    payload: {
      issueCode: nullableString(payload.issue_code, "review_event.payload.issue_code"),
      comment: nullableString(payload.comment, "review_event.payload.comment"),
      status: rawStatus === null ? null : oneOf(rawStatus, reviewStatuses, "review_event.payload.status"),
      suggestion: nullableString(payload.suggestion, "review_event.payload.suggestion"),
      severity: payload.severity === undefined || payload.severity === null
        ? null
        : oneOf(payload.severity, reviewSeverities, "review_event.payload.severity"),
    },
    source: oneOf(value.source, ["user", "import"] as const, "review_event.source"),
    immutable: literal(value.immutable, true, "review_event.immutable"),
  };
}

export function toExportEnvelopeWire(value: ExportEnvelopeV1): ExportEnvelopeWireV1 {
  return {
    schema_version: value.schemaVersion,
    export_id: value.exportId,
    created_at: value.createdAt,
    source_workspace_id: value.sourceWorkspaceId,
    source_dataset_digest: value.sourceDatasetDigest,
    event_count: value.eventCount,
    events: value.events.map(toReviewEventWire),
    identities: value.identities.map((identity) => ({ event_id: identity.eventId, digest: identity.digest })),
    media_included: value.mediaIncluded,
    absolute_paths_included: value.absolutePathsIncluded,
    dedupe_key: value.dedupeKey,
    content_digest: value.contentDigest,
  };
}

export function parseExportEnvelopeWire(input: unknown): ExportEnvelopeV1 {
  const value = record(input, "export_envelope");
  const mediaIncluded = literal(value.media_included, false, "export_envelope.media_included");
  const absolutePathsIncluded = literal(value.absolute_paths_included, false, "export_envelope.absolute_paths_included");
  const events = arrayValue(value.events, "export_envelope.events").map(parseReviewEventWire);
  const identities = arrayValue(value.identities, "export_envelope.identities").map((item, index) => {
    const identity = record(item, `export_envelope.identities[${index}]`);
    return {
      eventId: stringValue(identity.event_id, `export_envelope.identities[${index}].event_id`),
      digest: digest(identity.digest, `export_envelope.identities[${index}].digest`),
    };
  });
  const eventCount = integerValue(value.event_count, "export_envelope.event_count", 0);
  if (events.length !== eventCount || identities.length !== eventCount) {
    throw new TypeError("export_envelope.event_count must match complete events and identities lists");
  }
  return {
    schemaVersion: literal(value.schema_version, EXPORT_ENVELOPE_VERSION, "export_envelope.schema_version"),
    exportId: stringValue(value.export_id, "export_envelope.export_id"),
    createdAt: isoDate(value.created_at, "export_envelope.created_at"),
    sourceWorkspaceId: stringValue(value.source_workspace_id, "export_envelope.source_workspace_id"),
    sourceDatasetDigest: digest(value.source_dataset_digest, "export_envelope.source_dataset_digest"),
    eventCount,
    events,
    identities,
    mediaIncluded,
    absolutePathsIncluded,
    dedupeKey: stringValue(value.dedupe_key, "export_envelope.dedupe_key"),
    contentDigest: digest(value.content_digest, "export_envelope.content_digest"),
  };
}

export function toEvidenceReceiptWire(value: EvidenceReceiptV1): EvidenceReceiptWireV1 {
  return {
    schema_version: value.schemaVersion,
    receipt_id: value.receiptId,
    command_id: value.commandId,
    source_commit: value.sourceCommit,
    production_build_digest: value.productionBuildDigest,
    runner: { ...value.runner },
    browser: { ...value.browser },
    fixture: { ...value.fixture },
    started_at: value.startedAt,
    finished_at: value.finishedAt,
    exit_status: value.exitStatus,
    exit_code: value.exitCode,
    data_root_before_digest: value.dataRootBeforeDigest,
    data_root_after_digest: value.dataRootAfterDigest,
    artifacts: value.artifacts.map((artifact) => ({ ...artifact })),
    network: {
      loopback_only: value.network.loopbackOnly,
      non_loopback_requests: [...value.network.nonLoopbackRequests],
    },
    result: value.result,
  };
}

export function parseEvidenceReceiptWire(input: unknown): EvidenceReceiptV1 {
  const value = record(input, "evidence_receipt");
  const runner = record(value.runner, "evidence_receipt.runner");
  const browser = record(value.browser, "evidence_receipt.browser");
  const fixture = record(value.fixture, "evidence_receipt.fixture");
  const network = record(value.network, "evidence_receipt.network");
  const exitStatus = oneOf(value.exit_status, evidenceStatuses, "evidence_receipt.exit_status");
  const result = oneOf(value.result, evidenceStatuses, "evidence_receipt.result");
  const exitCode = integerValue(value.exit_code, "evidence_receipt.exit_code", 0);
  const beforeDigest = digest(value.data_root_before_digest, "evidence_receipt.data_root_before_digest");
  const afterDigest = digest(value.data_root_after_digest, "evidence_receipt.data_root_after_digest");
  const loopbackOnly = booleanValue(network.loopback_only, "evidence_receipt.network.loopback_only");
  const nonLoopbackRequests = stringArray(
    network.non_loopback_requests,
    null,
    "evidence_receipt.network.non_loopback_requests",
  );

  if (result !== exitStatus) throw new TypeError("evidence_receipt.result must match exit_status");
  if (result === "passed" && exitCode !== 0) throw new TypeError("evidence_receipt.exit_code must be 0 when passed");
  if (result === "passed" && beforeDigest !== afterDigest) {
    throw new TypeError("evidence_receipt passed result requires unchanged data root digest");
  }
  if (result === "passed" && (!loopbackOnly || nonLoopbackRequests.length !== 0)) {
    throw new TypeError("evidence_receipt passed result requires loopback-only network activity");
  }

  return {
    schemaVersion: literal(value.schema_version, EVIDENCE_RECEIPT_VERSION, "evidence_receipt.schema_version"),
    receiptId: stringValue(value.receipt_id, "evidence_receipt.receipt_id"),
    commandId: stringValue(value.command_id, "evidence_receipt.command_id"),
    sourceCommit: (() => {
      const commit = stringValue(value.source_commit, "evidence_receipt.source_commit");
      if (!/^[0-9a-f]{40}$/.test(commit)) throw new TypeError("evidence_receipt.source_commit must be a 40-char git hash");
      return commit;
    })(),
    productionBuildDigest: digest(value.production_build_digest, "evidence_receipt.production_build_digest"),
    runner: {
      name: stringValue(runner.name, "evidence_receipt.runner.name"),
      version: stringValue(runner.version, "evidence_receipt.runner.version"),
    },
    browser: {
      name: stringValue(browser.name, "evidence_receipt.browser.name"),
      version: stringValue(browser.version, "evidence_receipt.browser.version"),
    },
    fixture: {
      kind: oneOf(fixture.kind, ["synthetic", "nuscenes", "openlane"] as const, "evidence_receipt.fixture.kind"),
      digest: digest(fixture.digest, "evidence_receipt.fixture.digest"),
    },
    startedAt: isoDate(value.started_at, "evidence_receipt.started_at"),
    finishedAt: isoDate(value.finished_at, "evidence_receipt.finished_at"),
    exitStatus,
    exitCode,
    dataRootBeforeDigest: beforeDigest,
    dataRootAfterDigest: afterDigest,
    artifacts: arrayValue(value.artifacts, "evidence_receipt.artifacts").map((item, index) => {
      const artifact = record(item, `evidence_receipt.artifacts[${index}]`);
      return {
        kind: stringValue(artifact.kind, `evidence_receipt.artifacts[${index}].kind`),
        digest: digest(artifact.digest, `evidence_receipt.artifacts[${index}].digest`),
        redacted: booleanValue(artifact.redacted, `evidence_receipt.artifacts[${index}].redacted`),
      };
    }),
    network: { loopbackOnly, nonLoopbackRequests },
    result,
  };
}
