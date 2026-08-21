import type { EvidenceReceiptV1 } from "../contracts";
import type { DemoFrameVisual, DemoPoint } from "../features/nuscenes/DemoMultimodalViews";
import {
  FrameContextCoordinator,
  type NuScenesFeatureEvidence,
  NuScenesSearchIndex,
  createInstanceSelection,
} from "../features/nuscenes";
import { parseOpenLaneAnnotation } from "../features/openlane/model";
import type { OpenLaneReadonlyAudit } from "../features/openlane/readonly";

import nuScenesFixture from "../../tests/fixtures/synthetic/nuscenes/dataset.v1.json";
import openLaneAnnotation from "../../tests/fixtures/synthetic/openlane/root/lane3d_1000/validation/synthetic-segment/frame-0001.json";

const NUSCENES_DIGEST = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
const OPENLANE_DIGEST = "sha256:f63d05a3772587bc3cbc80091d62ed538bb5f885025eebc127677c512dc302f6";

type ReceiptFixtureKind = EvidenceReceiptV1["fixture"]["kind"];

export interface RuntimeEvidenceContext {
  readonly sourceCommit: string;
  readonly productionBuildDigest: string;
  readonly runnerVersion: string;
  readonly browserVersion: string;
  readonly startedAt: string;
  readonly finishedAt: string;
  readonly observedResourceUrls: readonly string[];
}

export interface SyntheticNuScenesAdapter {
  readonly frameRefs: readonly string[];
  readonly instanceRefs: readonly string[];
  readonly visualsByFrame: Readonly<Record<string, DemoFrameVisual>>;
  readonly selectFrame: FrameContextCoordinator["select"];
  readonly selectInstance: (instanceRef: string) => ReturnType<typeof createInstanceSelection>;
  readonly search: (text: string, weather: "rain" | undefined) => ReturnType<NuScenesSearchIndex["search"]>;
  readonly evidence: { readonly dataRootBefore: string; readonly dataRootAfter: string };
  readonly featureEvidence: NuScenesFeatureEvidence;
}

function createPoints(sequence: number): readonly DemoPoint[] {
  const regular = Array.from({ length: 216 }, (_, index) => {
    const depth = 4 + (index * 13 + sequence * 5) % 32;
    const lateral = ((index * 17 + sequence * 3) % 49 - 24) / 2.25;
    const height = ((index * 7) % 9 - 4) / 3;
    return { x: lateral, y: height, z: depth, intensity: ((index * 19) % 100) / 100 };
  });
  return [
    ...regular,
    { x: 1, y: 0, z: -2, intensity: .4 },
    { x: -3, y: .5, z: 0, intensity: .4 },
    { x: 35, y: 2, z: 10, intensity: .6 },
    { x: 0, y: 0, z: 44, intensity: .7 },
  ];
}

function createVisual(frameRef: string, sequence: number): DemoFrameVisual {
  return {
    frameRef,
    sequence,
    location: "合成园区东侧道路",
    timeLabel: `08:15:${String(sequence * 5).padStart(2, "0")}`,
    object: {
      stableInstanceRef: "instance-vehicle-01",
      category: "vehicle.car",
      velocityMps: 6.4,
      x: -4 + sequence * 1.6,
      y: 13 + sequence * .8,
      headingDeg: sequence * 2,
    },
    points: createPoints(sequence),
  };
}

function createDemoKeyframes() {
  const timestampUs = 1_535_099_000_000_000;
  return Array.from({ length: 6 }, (_, sequence) => {
    const frameRef = `sample-${String(sequence + 1).padStart(4, "0")}`;
    const currentTimestampUs = timestampUs + sequence * 500_000;
    return {
      frame_ref: frameRef,
      timestamp_us: currentTimestampUs,
      sensors: [
        { sensor_id: "CAM_FRONT", modality: "camera", timestamp_us: currentTimestampUs + 10_000, asset_ref: `asset:cam-front-${sequence + 1}` },
        { sensor_id: "CAM_FRONT_RIGHT", modality: "camera", timestamp_us: currentTimestampUs + 8_000, asset_ref: `asset:cam-front-right-${sequence + 1}` },
        { sensor_id: "CAM_BACK_RIGHT", modality: "camera", timestamp_us: currentTimestampUs - 12_000, asset_ref: `asset:cam-back-right-${sequence + 1}` },
        { sensor_id: "CAM_BACK", modality: "camera", timestamp_us: currentTimestampUs - 16_000, asset_ref: `asset:cam-back-${sequence + 1}` },
        { sensor_id: "CAM_BACK_LEFT", modality: "camera", timestamp_us: currentTimestampUs - 9_000, asset_ref: `asset:cam-back-left-${sequence + 1}` },
        { sensor_id: "CAM_FRONT_LEFT", modality: "camera", timestamp_us: currentTimestampUs + 6_000, asset_ref: `asset:cam-front-left-${sequence + 1}` },
        { sensor_id: "LIDAR_TOP", modality: "lidar", timestamp_us: currentTimestampUs, asset_ref: `asset:lidar-top-${sequence + 1}` },
      ],
      annotations: [{
        annotation_ref: `annotation-${String(sequence + 1).padStart(4, "0")}`,
        instance_ref: "instance-vehicle-01",
        category: "vehicle.car",
        camera_ref: `camera-box-${String(sequence + 1).padStart(4, "0")}`,
        lidar_ref: `lidar-box-${String(sequence + 1).padStart(4, "0")}`,
        bev_ref: `bev-box-${String(sequence + 1).padStart(4, "0")}`,
        previous_annotation_ref: sequence === 0 ? null : `annotation-${String(sequence).padStart(4, "0")}`,
        next_annotation_ref: sequence === 5 ? null : `annotation-${String(sequence + 2).padStart(4, "0")}`,
      }],
    };
  });
}

export function createSyntheticNuScenesAdapter(): SyntheticNuScenesAdapter {
  const scene = nuScenesFixture.scenes[0]!;
  const frames = createDemoKeyframes();
  const coordinator = new FrameContextCoordinator(async (frameRef) => {
    const frame = frames.find((candidate) => candidate.frame_ref === frameRef);
    if (!frame) throw new RangeError(`unknown synthetic frame: ${frameRef}`);
    return {
      sceneRef: scene.scene_ref,
      frameRef: frame.frame_ref,
      timestampUs: frame.timestamp_us,
      sensors: frame.sensors.map((sensor) => ({
        sensorId: sensor.sensor_id,
        modality: sensor.modality as "camera" | "lidar",
        timestampUs: sensor.timestamp_us,
        assetRef: sensor.asset_ref,
      })),
    };
  });
  const annotations = frames.flatMap((frame) =>
    frame.annotations.map((annotation) => ({
      annotationRef: annotation.annotation_ref,
      sceneRef: scene.scene_ref,
      frameRef: frame.frame_ref,
      instanceRef: annotation.instance_ref,
      cameraRef: annotation.camera_ref,
      lidarRef: annotation.lidar_ref,
      bevRef: annotation.bev_ref,
      previousAnnotationRef: annotation.previous_annotation_ref,
      nextAnnotationRef: annotation.next_annotation_ref,
    })),
  );
  const index = new NuScenesSearchIndex("scene-derivation.v1", [{
    stableId: `${scene.scene_ref}:${frames[0]!.frame_ref}`,
    sceneRef: scene.scene_ref,
    frameRef: frames[0]!.frame_ref,
    sourceText: scene.description,
  }]);
  const featureEvidence: NuScenesFeatureEvidence = {
    dataRootDigestBefore: NUSCENES_DIGEST,
    dataRootDigestAfter: NUSCENES_DIGEST,
    absolutePathsIncluded: false,
    pointCloud: { worker: true, lod: 2, maxChunkBytes: 8_388_608 },
    cache: { hardLimit: true, evictionPolicy: "lru" },
  };

  return {
    frameRefs: frames.map((frame) => frame.frame_ref),
    instanceRefs: [...new Set(annotations.map((annotation) => annotation.instanceRef))],
    visualsByFrame: Object.fromEntries(frames.map((frame, sequence) => [frame.frame_ref, createVisual(frame.frame_ref, sequence)])),
    selectFrame: coordinator.select.bind(coordinator),
    selectInstance: (instanceRef) => createInstanceSelection(scene.scene_ref, instanceRef, annotations),
    search: (text, weather) => index.search({ text, derivedFilters: { weather } }),
    evidence: { dataRootBefore: NUSCENES_DIGEST, dataRootAfter: NUSCENES_DIGEST },
    featureEvidence,
  };
}

export function createOpenLaneAssembly() {
  const frame = parseOpenLaneAnnotation(openLaneAnnotation, {
    datasetVersion: "v1.2",
    frameRef: "lane3d_1000/validation/synthetic-segment/frame-0001.json",
  });
  const audit: OpenLaneReadonlyAudit = {
    schemaVersion: "openlane-readonly-audit.v1",
    datasetVersion: "v1.2",
    rootId: "openlane:f63d05a3772587bc",
    dataRootBeforeDigest: OPENLANE_DIGEST,
    dataRootAfterDigest: OPENLANE_DIGEST,
    unchanged: true,
    fileCount: 1,
    mediaIncluded: false,
    absolutePathsIncluded: false,
    acquisitionRequired: true,
    nonCommercialUseOnly: true,
  };
  return { frame, audit, fixtureDigest: OPENLANE_DIGEST };
}

function isLoopbackResource(rawUrl: string): boolean {
  const url = new URL(rawUrl, globalThis.location?.href ?? "http://127.0.0.1");
  return !["http:", "https:", "ws:", "wss:"].includes(url.protocol)
    || ["127.0.0.1", "localhost", "::1"].includes(url.hostname);
}

export function createRuntimeEvidenceReceipt(
  commandId: string,
  kind: ReceiptFixtureKind,
  digest: string,
  context: RuntimeEvidenceContext,
): EvidenceReceiptV1 {
  const nonLoopbackRequests = context.observedResourceUrls.filter((url) => !isLoopbackResource(url));
  return {
    schemaVersion: "evidence-receipt.v1",
    receiptId: `runtime-${commandId.toLowerCase()}-${context.startedAt.replace(/[^0-9]/g, "")}`,
    commandId,
    sourceCommit: context.sourceCommit,
    productionBuildDigest: context.productionBuildDigest,
    runner: { name: "@playwright/test", version: context.runnerVersion },
    browser: { name: "chromium", version: context.browserVersion },
    fixture: { kind, digest },
    startedAt: context.startedAt,
    finishedAt: context.finishedAt,
    exitStatus: nonLoopbackRequests.length === 0 ? "passed" : "failed",
    exitCode: nonLoopbackRequests.length === 0 ? 0 : 1,
    dataRootBeforeDigest: digest,
    dataRootAfterDigest: digest,
    artifacts: [{ kind: "loaded-production-build", digest: context.productionBuildDigest, redacted: true }],
    network: { loopbackOnly: nonLoopbackRequests.length === 0, nonLoopbackRequests },
    result: nonLoopbackRequests.length === 0 ? "passed" : "failed",
  };
}
