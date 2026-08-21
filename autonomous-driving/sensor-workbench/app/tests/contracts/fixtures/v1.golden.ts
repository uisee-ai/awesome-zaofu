export const adapterDescriptorCamelGolden = {
  schemaVersion: "adapter.v1",
  adapterId: "nuscenes-v1",
  datasetKind: "nuscenes",
  datasetVersion: "v1.0-mini",
  displayName: "nuScenes v1.0 mini",
  capabilities: ["scan", "browse", "search", "coordinate_projection", "review"],
  unsupportedCapabilities: ["model_comparison", "official_evaluation", "raw_data_mutation"],
  fallbackBehavior: "report_unsupported",
  ignoredSourceFields: ["non_keyframe_sweeps", "radar", "lidarseg", "panoptic", "can_bus", "hd_map"],
  readOnly: true,
} as const;

export const adapterDescriptorWireGolden = {
  schema_version: "adapter.v1",
  adapter_id: "nuscenes-v1",
  dataset_kind: "nuscenes",
  dataset_version: "v1.0-mini",
  display_name: "nuScenes v1.0 mini",
  capabilities: ["scan", "browse", "search", "coordinate_projection", "review"],
  unsupported_capabilities: ["model_comparison", "official_evaluation", "raw_data_mutation"],
  fallback_behavior: "report_unsupported",
  ignored_source_fields: ["non_keyframe_sweeps", "radar", "lidarseg", "panoptic", "can_bus", "hd_map"],
  read_only: true,
} as const;

export const frameContextCamelGolden = {
  schemaVersion: "frame-context.v1",
  frameContextId: "scene-0061:sample-0001:g7",
  generation: 7,
  adapterId: "nuscenes-v1",
  datasetKind: "nuscenes",
  datasetVersion: "v1.0-mini",
  sceneRef: "scene-0061",
  frameRef: "sample-0001",
  keyframe: true,
  timestampUs: 1_535_099_000_000_000,
  primarySensorId: "LIDAR_TOP",
  coordinateFrame: "ego",
  sensorFrames: [
    {
      sensorId: "CAM_FRONT",
      modality: "camera",
      timestampUs: 1_535_099_000_012_000,
      deltaMs: 12,
      availability: "available",
      assetRef: "asset:cam-front-0001",
    },
    {
      sensorId: "LIDAR_TOP",
      modality: "lidar",
      timestampUs: 1_535_099_000_000_000,
      deltaMs: 0,
      availability: "available",
      assetRef: "asset:lidar-top-0001",
    },
    {
      sensorId: "CAM_BACK",
      modality: "camera",
      timestampUs: 1_535_098_999_984_000,
      deltaMs: -16,
      availability: "missing",
      assetRef: null,
    },
  ],
} as const;

export const frameContextWireGolden = {
  schema_version: "frame-context.v1",
  frame_context_id: "scene-0061:sample-0001:g7",
  generation: 7,
  adapter_id: "nuscenes-v1",
  dataset_kind: "nuscenes",
  dataset_version: "v1.0-mini",
  scene_ref: "scene-0061",
  frame_ref: "sample-0001",
  keyframe: true,
  timestamp_us: 1_535_099_000_000_000,
  primary_sensor_id: "LIDAR_TOP",
  coordinate_frame: "ego",
  sensor_frames: [
    {
      sensor_id: "CAM_FRONT",
      modality: "camera",
      timestamp_us: 1_535_099_000_012_000,
      delta_ms: 12,
      availability: "available",
      asset_ref: "asset:cam-front-0001",
    },
    {
      sensor_id: "LIDAR_TOP",
      modality: "lidar",
      timestamp_us: 1_535_099_000_000_000,
      delta_ms: 0,
      availability: "available",
      asset_ref: "asset:lidar-top-0001",
    },
    {
      sensor_id: "CAM_BACK",
      modality: "camera",
      timestamp_us: 1_535_098_999_984_000,
      delta_ms: -16,
      availability: "missing",
      asset_ref: null,
    },
  ],
} as const;

export const workspaceCamelGolden = {
  schemaVersion: "workspace.v1",
  workspaceId: "workspace-local-001",
  createdAt: "2026-08-03T10:00:00.000Z",
  dataRootDigest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  dataRootMode: "read-only",
  mutableRootMode: "workspace-only",
  maxCacheBytes: 536_870_912,
  paths: {
    indexDirectory: "index",
    cacheDirectory: "cache",
    reviewLog: "review/events.jsonl",
    exportDirectory: "exports",
    evidenceDirectory: "evidence",
  },
} as const;

export const workspaceWireGolden = {
  schema_version: "workspace.v1",
  workspace_id: "workspace-local-001",
  created_at: "2026-08-03T10:00:00.000Z",
  data_root_digest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  data_root_mode: "read-only",
  mutable_root_mode: "workspace-only",
  max_cache_bytes: 536_870_912,
  paths: {
    index_directory: "index",
    cache_directory: "cache",
    review_log: "review/events.jsonl",
    export_directory: "exports",
    evidence_directory: "evidence",
  },
} as const;

export const reviewEventCamelGolden = {
  schemaVersion: "review-event.v1",
  eventId: "review-event-0001",
  reviewId: "review-0001",
  revision: 1,
  previousEventId: null,
  frameContextId: "scene-0061:sample-0001:g7",
  target: { kind: "annotation", stableId: "instance-0123" },
  eventType: "issue_created",
  occurredAt: "2026-08-03T10:01:00.000Z",
  actorId: "local-user",
  payload: {
    issueCode: "projection_mismatch",
    comment: "Camera 与 BEV 框未对齐",
    status: "open",
    suggestion: "检查 calibrated_sensor 外参",
    severity: "high",
  },
  source: "user",
  immutable: true,
} as const;

export const reviewEventWireGolden = {
  schema_version: "review-event.v1",
  event_id: "review-event-0001",
  review_id: "review-0001",
  revision: 1,
  previous_event_id: null,
  frame_context_id: "scene-0061:sample-0001:g7",
  target: { kind: "annotation", stable_id: "instance-0123" },
  event_type: "issue_created",
  occurred_at: "2026-08-03T10:01:00.000Z",
  actor_id: "local-user",
  payload: {
    issue_code: "projection_mismatch",
    comment: "Camera 与 BEV 框未对齐",
    status: "open",
    suggestion: "检查 calibrated_sensor 外参",
    severity: "high",
  },
  source: "user",
  immutable: true,
} as const;

export const exportEnvelopeCamelGolden = {
  schemaVersion: "export-envelope.v1",
  exportId: "export-0001",
  createdAt: "2026-08-03T10:02:00.000Z",
  sourceWorkspaceId: "workspace-local-001",
  sourceDatasetDigest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  eventCount: 1,
  events: [reviewEventCamelGolden],
  identities: [
    {
      eventId: "review-event-0001",
      digest: "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    },
  ],
  mediaIncluded: false,
  absolutePathsIncluded: false,
  dedupeKey: "review-0001:1",
  contentDigest: "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
} as const;

export const exportEnvelopeWireGolden = {
  schema_version: "export-envelope.v1",
  export_id: "export-0001",
  created_at: "2026-08-03T10:02:00.000Z",
  source_workspace_id: "workspace-local-001",
  source_dataset_digest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  event_count: 1,
  events: [reviewEventWireGolden],
  identities: [
    {
      event_id: "review-event-0001",
      digest: "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    },
  ],
  media_included: false,
  absolute_paths_included: false,
  dedupe_key: "review-0001:1",
  content_digest: "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
} as const;

export const evidenceReceiptCamelGolden = {
  schemaVersion: "evidence-receipt.v1",
  receiptId: "receipt-synthetic-0001",
  commandId: "SWB-ASSEMBLY-005-CMD-02",
  sourceCommit: "0123456789abcdef0123456789abcdef01234567",
  productionBuildDigest: "sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
  runner: { name: "@playwright/test", version: "1.62.1" },
  browser: { name: "chromium", version: "140.0.0.0" },
  fixture: {
    kind: "synthetic",
    digest: "sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
  },
  startedAt: "2026-08-03T10:03:00.000Z",
  finishedAt: "2026-08-03T10:03:08.000Z",
  exitStatus: "passed",
  exitCode: 0,
  dataRootBeforeDigest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  dataRootAfterDigest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  artifacts: [
    {
      kind: "trace",
      digest: "sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
      redacted: true,
    },
    {
      kind: "metrics",
      digest: "sha256:1111111111111111111111111111111111111111111111111111111111111111",
      redacted: true,
    },
  ],
  network: { loopbackOnly: true, nonLoopbackRequests: [] },
  result: "passed",
} as const;

export const evidenceReceiptWireGolden = {
  schema_version: "evidence-receipt.v1",
  receipt_id: "receipt-synthetic-0001",
  command_id: "SWB-ASSEMBLY-005-CMD-02",
  source_commit: "0123456789abcdef0123456789abcdef01234567",
  production_build_digest: "sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
  runner: { name: "@playwright/test", version: "1.62.1" },
  browser: { name: "chromium", version: "140.0.0.0" },
  fixture: {
    kind: "synthetic",
    digest: "sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
  },
  started_at: "2026-08-03T10:03:00.000Z",
  finished_at: "2026-08-03T10:03:08.000Z",
  exit_status: "passed",
  exit_code: 0,
  data_root_before_digest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  data_root_after_digest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  artifacts: [
    {
      kind: "trace",
      digest: "sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
      redacted: true,
    },
    {
      kind: "metrics",
      digest: "sha256:1111111111111111111111111111111111111111111111111111111111111111",
      redacted: true,
    },
  ],
  network: { loopback_only: true, non_loopback_requests: [] },
  result: "passed",
} as const;
