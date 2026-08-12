import { TRAJECTORY_POINT_COUNT, type TrajectoryPoint } from "../../../../packages/contracts/src/scene";

export type TrajectoryVisualizationErrorCode =
  | "TRAJECTORY_POINT_COUNT"
  | "DUPLICATE_RUN_ID";

export class TrajectoryVisualizationError extends Error {
  constructor(
    readonly code: TrajectoryVisualizationErrorCode,
    message: string,
  ) {
    super(message);
    this.name = "TrajectoryVisualizationError";
  }
}

export interface TrajectoryRun {
  runId: string;
  trajectory: readonly TrajectoryPoint[];
}

export interface BevPoint {
  index: number;
  timeSeconds: number;
  x: number;
  y: number;
}

export interface BevTrajectory {
  runId: string;
  points: BevPoint[];
}

export interface LateralDifferenceSummary {
  endpointLateralDifference: number;
  averageLateralDifference: number;
  maximumLateralDifference: number;
}

export interface BevVisualizationSnapshot {
  baseline: BevTrajectory;
  overlays: BevTrajectory[];
  comparison: LateralDifferenceSummary | null;
}

export interface BevVisualizationInput {
  baseline: TrajectoryRun;
  overlays?: readonly TrajectoryRun[];
}

export interface DownloadableBevExport {
  fileName: string;
  mimeType: "application/json" | "image/png";
  contents?: string;
  dataUrl?: string;
}

const PNG_SIGNATURE = new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10]);
const PNG_SIZE = 96;

function crc32(bytes: Uint8Array): number {
  let crc = 0xffffffff;
  for (const byte of bytes) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit += 1) {
      crc = (crc >>> 1) ^ (-(crc & 1) & 0xedb88320);
    }
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function adler32(bytes: Uint8Array): number {
  let a = 1;
  let b = 0;
  for (const byte of bytes) {
    a = (a + byte) % 65521;
    b = (b + a) % 65521;
  }
  return ((b << 16) | a) >>> 0;
}

function writeUint32(value: number): Uint8Array {
  const bytes = new Uint8Array(4);
  new DataView(bytes.buffer).setUint32(0, value >>> 0);
  return bytes;
}

function concat(parts: readonly Uint8Array[]): Uint8Array {
  const output = new Uint8Array(parts.reduce((size, part) => size + part.length, 0));
  let offset = 0;
  for (const part of parts) {
    output.set(part, offset);
    offset += part.length;
  }
  return output;
}

function pngChunk(type: string, data: Uint8Array): Uint8Array {
  const kind = new TextEncoder().encode(type);
  const crc = crc32(concat([kind, data]));
  return concat([writeUint32(data.length), kind, data, writeUint32(crc)]);
}

function deflateUncompressed(data: Uint8Array): Uint8Array {
  const blocks: Uint8Array[] = [new Uint8Array([0x78, 0x01])];
  for (let offset = 0; offset < data.length; offset += 65535) {
    const size = Math.min(65535, data.length - offset);
    const block = new Uint8Array(size + 5);
    block[0] = offset + size === data.length ? 1 : 0;
    block[1] = size & 0xff;
    block[2] = size >>> 8;
    block[3] = (~size) & 0xff;
    block[4] = (~size) >>> 8;
    block.set(data.subarray(offset, offset + size), 5);
    blocks.push(block);
  }
  blocks.push(writeUint32(adler32(data)));
  return concat(blocks);
}

function encodeBase64(bytes: Uint8Array): string {
  if (typeof Buffer !== "undefined") return Buffer.from(bytes).toString("base64");
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

function drawTrajectory(
  pixels: Uint8Array,
  trajectory: BevTrajectory,
  bounds: { minX: number; maxX: number; minY: number; maxY: number },
  color: readonly [number, number, number],
): void {
  const map = (value: number, min: number, max: number): number => {
    const ratio = max === min ? 0.5 : (value - min) / (max - min);
    return Math.max(0, Math.min(PNG_SIZE - 1, Math.round(ratio * (PNG_SIZE - 1))));
  };
  for (const point of trajectory.points) {
    const x = map(point.x, bounds.minX, bounds.maxX);
    const y = PNG_SIZE - 1 - map(point.y, bounds.minY, bounds.maxY);
    const pixel = (y * PNG_SIZE + x) * 4;
    pixels.set([color[0], color[1], color[2], 255], pixel);
  }
}

function renderPng(snapshot: BevVisualizationSnapshot): string {
  const allPoints = [snapshot.baseline, ...snapshot.overlays].flatMap((trajectory) => trajectory.points);
  const bounds = {
    minX: Math.min(...allPoints.map((point) => point.x)),
    maxX: Math.max(...allPoints.map((point) => point.x)),
    minY: Math.min(...allPoints.map((point) => point.y)),
    maxY: Math.max(...allPoints.map((point) => point.y)),
  };
  const pixels = new Uint8Array(PNG_SIZE * PNG_SIZE * 4);
  for (let pixel = 0; pixel < pixels.length; pixel += 4) pixels.set([15, 23, 42, 255], pixel);
  drawTrajectory(pixels, snapshot.baseline, bounds, [34, 211, 238]);
  for (const [index, overlay] of snapshot.overlays.entries()) {
    drawTrajectory(pixels, overlay, bounds, index % 2 === 0 ? [251, 191, 36] : [244, 114, 182]);
  }

  const rows = new Uint8Array(PNG_SIZE * (1 + PNG_SIZE * 4));
  for (let y = 0; y < PNG_SIZE; y += 1) {
    const target = y * (1 + PNG_SIZE * 4);
    rows[target] = 0;
    rows.set(pixels.subarray(y * PNG_SIZE * 4, (y + 1) * PNG_SIZE * 4), target + 1);
  }
  const header = new Uint8Array(13);
  const view = new DataView(header.buffer);
  view.setUint32(0, PNG_SIZE);
  view.setUint32(4, PNG_SIZE);
  header.set([8, 6, 0, 0, 0], 8);
  const png = concat([PNG_SIGNATURE, pngChunk("IHDR", header), pngChunk("IDAT", deflateUncompressed(rows)), pngChunk("IEND", new Uint8Array())]);
  return `data:image/png;base64,${encodeBase64(png)}`;
}

function toBevTrajectory(run: TrajectoryRun): BevTrajectory {
  if (run.trajectory.length !== TRAJECTORY_POINT_COUNT) {
    throw new TrajectoryVisualizationError(
      "TRAJECTORY_POINT_COUNT",
      `BEV 轨迹必须包含 ${TRAJECTORY_POINT_COUNT} 个未来点。`,
    );
  }

  return {
    runId: run.runId,
    points: run.trajectory.map((point, index) => ({
      index,
      timeSeconds: point.timeSeconds,
      x: point.position[0],
      y: point.position[1],
    })),
  };
}

function summarizeLateralDifference(
  baseline: BevTrajectory,
  overlay: BevTrajectory,
): LateralDifferenceSummary {
  const lateralDifferences = baseline.points.map((point, index) => Math.abs(point.y - overlay.points[index].y));
  const normalize = (value: number): number => Number(value.toFixed(6));
  return {
    endpointLateralDifference: normalize(lateralDifferences.at(-1) ?? 0),
    averageLateralDifference: normalize(lateralDifferences.reduce((sum, difference) => sum + difference, 0) / lateralDifferences.length),
    maximumLateralDifference: normalize(Math.max(...lateralDifferences)),
  };
}

/**
 * Framework-independent BEV view model. A UI can plot `points` directly and
 * bind its export controls to the two download descriptors.
 */
export class BevTrajectoryVisualization {
  private readonly state: BevVisualizationSnapshot;

  constructor(input: BevVisualizationInput) {
    const baseline = toBevTrajectory(input.baseline);
    const overlays = (input.overlays ?? []).map(toBevTrajectory);
    const runIds = new Set([baseline.runId]);
    for (const overlay of overlays) {
      if (runIds.has(overlay.runId)) {
        throw new TrajectoryVisualizationError("DUPLICATE_RUN_ID", "基准轨迹和叠加轨迹必须使用不同的运行 ID。");
      }
      runIds.add(overlay.runId);
    }

    this.state = {
      baseline,
      overlays,
      comparison: overlays.length === 0 ? null : summarizeLateralDifference(baseline, overlays[0]),
    };
  }

  snapshot(): BevVisualizationSnapshot {
    return structuredClone(this.state);
  }

  exportJson(): DownloadableBevExport {
    return {
      fileName: `bev-trajectory-${this.state.baseline.runId}.json`,
      mimeType: "application/json",
      contents: JSON.stringify(this.snapshot(), null, 2),
    };
  }

  exportPng(): DownloadableBevExport {
    return {
      fileName: `bev-trajectory-${this.state.baseline.runId}.png`,
      mimeType: "image/png",
      dataUrl: renderPng(this.state),
    };
  }
}
