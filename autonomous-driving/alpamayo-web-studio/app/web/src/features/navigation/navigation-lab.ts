import type { NavigationLabExperiment } from "../../../../backend/studio/navigation/navigation-lab.js";
import {
  BevTrajectoryVisualization,
  type BevTrajectory,
  type DownloadableBevExport,
  type TrajectoryRun,
} from "../trajectory/bev-trajectory-visualization.js";

const BRANCH_COLORS = ["#22d3ee", "#fbbf24", "#f472b6", "#a78bfa"] as const;
const PNG_SIGNATURE = new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10]);
const PNG_SIZE = 96;

export interface NavigationLegendItem {
  branchId: string;
  instruction: string;
  color: string;
  visible: boolean;
}

export interface NavigationComparison {
  branchId: string;
  endpointDistance: number;
  averagePointDistance: number;
  maximumLateralDifference: number;
}

export interface NavigationLabSnapshot {
  sceneVersionId: string;
  legend: NavigationLegendItem[];
  trajectories: BevTrajectory[];
  comparisons: NavigationComparison[];
}

export type NavigationLabVisualizationErrorCode = "NO_SUCCEEDED_BRANCHES" | "UNKNOWN_BRANCH";

export class NavigationLabVisualizationError extends Error {
  constructor(
    readonly code: NavigationLabVisualizationErrorCode,
    message: string,
  ) {
    super(message);
    this.name = "NavigationLabVisualizationError";
  }
}

function copy<T>(value: T): T {
  return structuredClone(value);
}

function toTrajectoryRun(experiment: NavigationLabExperiment): TrajectoryRun[] {
  return experiment.branches.flatMap((branch) => branch.status === "succeeded" && branch.output !== undefined
    ? [{ runId: branch.id, trajectory: branch.output.trajectory }]
    : []);
}

function toBevTrajectory(run: TrajectoryRun): BevTrajectory {
  return new BevTrajectoryVisualization({ baseline: run }).snapshot().baseline;
}

function normalize(value: number): number {
  return Number(value.toFixed(6));
}

function compare(baseline: BevTrajectory, candidate: BevTrajectory): NavigationComparison {
  const distances = baseline.points.map((point, index) => {
    const other = candidate.points[index];
    return Math.hypot(point.x - other.x, point.y - other.y);
  });
  const laterals = baseline.points.map((point, index) => Math.abs(point.y - candidate.points[index].y));
  return {
    branchId: candidate.runId,
    endpointDistance: normalize(distances.at(-1) ?? 0),
    averagePointDistance: normalize(distances.reduce((sum, distance) => sum + distance, 0) / distances.length),
    maximumLateralDifference: normalize(Math.max(...laterals)),
  };
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

function writeUint32(value: number): Uint8Array {
  const bytes = new Uint8Array(4);
  new DataView(bytes.buffer).setUint32(0, value >>> 0);
  return bytes;
}

function crc32(bytes: Uint8Array): number {
  let crc = 0xffffffff;
  for (const byte of bytes) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit += 1) crc = (crc >>> 1) ^ (-(crc & 1) & 0xedb88320);
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function pngChunk(type: string, data: Uint8Array): Uint8Array {
  const kind = new TextEncoder().encode(type);
  return concat([writeUint32(data.length), kind, data, writeUint32(crc32(concat([kind, data])))]);
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

function colorBytes(color: string): [number, number, number] {
  return [Number.parseInt(color.slice(1, 3), 16), Number.parseInt(color.slice(3, 5), 16), Number.parseInt(color.slice(5, 7), 16)];
}

function encodeBase64(bytes: Uint8Array): string {
  if (typeof Buffer !== "undefined") return Buffer.from(bytes).toString("base64");
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

function renderNavigationPng(trajectories: readonly { trajectory: BevTrajectory; color: string }[]): string {
  const allPoints = trajectories.flatMap(({ trajectory }) => trajectory.points);
  const bounds = {
    minX: Math.min(...allPoints.map((point) => point.x)),
    maxX: Math.max(...allPoints.map((point) => point.x)),
    minY: Math.min(...allPoints.map((point) => point.y)),
    maxY: Math.max(...allPoints.map((point) => point.y)),
  };
  const map = (value: number, min: number, max: number): number => {
    const ratio = max === min ? 0.5 : (value - min) / (max - min);
    return Math.max(0, Math.min(PNG_SIZE - 1, Math.round(ratio * (PNG_SIZE - 1))));
  };
  const pixels = new Uint8Array(PNG_SIZE * PNG_SIZE * 4);
  for (let pixel = 0; pixel < pixels.length; pixel += 4) pixels.set([15, 23, 42, 255], pixel);
  for (const { trajectory, color } of trajectories) {
    const [red, green, blue] = colorBytes(color);
    for (const point of trajectory.points) {
      const x = map(point.x, bounds.minX, bounds.maxX);
      const y = PNG_SIZE - 1 - map(point.y, bounds.minY, bounds.maxY);
      pixels.set([red, green, blue, 255], (y * PNG_SIZE + x) * 4);
    }
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

/** Framework-neutral state for Navigation Lab controls and the BEV overlay. */
export class NavigationLabVisualization {
  private readonly sceneVersionId: string;
  private readonly trajectoriesByBranch = new Map<string, BevTrajectory>();
  private readonly legend: NavigationLegendItem[];
  private readonly comparisons: NavigationComparison[];

  constructor(experiment: NavigationLabExperiment) {
    const runs = toTrajectoryRun(experiment);
    if (runs.length === 0) {
      throw new NavigationLabVisualizationError("NO_SUCCEEDED_BRANCHES", "导航实验没有可显示的成功分支。");
    }
    this.sceneVersionId = experiment.sceneVersionId;
    for (const run of runs) this.trajectoriesByBranch.set(run.runId, toBevTrajectory(run));
    this.legend = experiment.branches.map((branch, index) => ({
      branchId: branch.id,
      instruction: branch.instruction,
      color: BRANCH_COLORS[index],
      visible: branch.status === "succeeded" && branch.output !== undefined,
    }));
    const baseline = runs[0];
    this.comparisons = runs.slice(1).map((run) => compare(toBevTrajectory(baseline), toBevTrajectory(run)));
  }

  setBranchVisibility(branchId: string, visible: boolean): NavigationLabSnapshot {
    const item = this.legend.find((candidate) => candidate.branchId === branchId);
    if (item === undefined || !this.trajectoriesByBranch.has(branchId)) {
      throw new NavigationLabVisualizationError("UNKNOWN_BRANCH", "找不到可显示的导航实验分支。");
    }
    item.visible = visible;
    return this.snapshot();
  }

  snapshot(): NavigationLabSnapshot {
    return {
      sceneVersionId: this.sceneVersionId,
      legend: copy(this.legend),
      trajectories: this.legend.flatMap((item) => item.visible
        ? [copy(this.trajectoriesByBranch.get(item.branchId)!)]
        : []),
      comparisons: copy(this.comparisons),
    };
  }

  exportJson(): DownloadableBevExport {
    return {
      fileName: `navigation-lab-${this.sceneVersionId}.json`,
      mimeType: "application/json",
      contents: JSON.stringify({ schemaVersion: "navigation-lab-export.v1", ...this.snapshot() }, null, 2),
    };
  }

  exportPng(): DownloadableBevExport {
    const trajectories = this.legend.flatMap((item) => item.visible
      ? [{ trajectory: this.trajectoriesByBranch.get(item.branchId)!, color: item.color }]
      : []);
    if (trajectories.length === 0) {
      throw new NavigationLabVisualizationError("NO_SUCCEEDED_BRANCHES", "至少保留一个导航分支后才能导出 PNG。");
    }
    return {
      fileName: `navigation-lab-${this.sceneVersionId}.png`,
      mimeType: "image/png",
      dataUrl: renderNavigationPng(trajectories),
    };
  }
}
