import type { AdapterDescriptorV1 } from "../../contracts/index.ts";

export type OpenLanePoint2d = readonly [number, number];
export type OpenLanePoint3d = readonly [number, number, number];

export interface OpenLaneLane {
  readonly laneRef: string;
  readonly lane2dRef: string;
  readonly lane3dRef: string;
  readonly trackId: number;
  readonly category: { readonly id: number; readonly name: string };
  readonly attribute: { readonly id: number; readonly name: string };
  readonly visibility: readonly number[];
  readonly points2d: readonly OpenLanePoint2d[];
  readonly points3d: readonly OpenLanePoint3d[];
}

export interface OpenLaneFrame {
  readonly datasetVersion: "v1.2";
  readonly frameRef: string;
  readonly imageRef: string;
  readonly intrinsic: readonly (readonly number[])[];
  readonly extrinsic: readonly (readonly number[])[];
  readonly pose: readonly (readonly number[])[];
  readonly lanes: readonly OpenLaneLane[];
}

export interface OpenLaneViewModel {
  readonly frameRef: string;
  readonly lanes: readonly OpenLaneLane[];
  readonly selectedLane: OpenLaneLane | null;
}

export const OPENLANE_ADAPTER_DESCRIPTOR: AdapterDescriptorV1 = {
  schemaVersion: "adapter.v1",
  adapterId: "openlane-v1.2",
  datasetKind: "openlane",
  datasetVersion: "v1.2",
  displayName: "OpenLane V1.2",
  capabilities: ["scan", "browse", "coordinate_projection", "review"],
  unsupportedCapabilities: ["model_comparison", "official_evaluation", "raw_data_mutation"],
  fallbackBehavior: "report_unsupported",
  ignoredSourceFields: ["future_v2_field", "cipo", "scene_tags"],
  readOnly: true,
};

const categoryNames = new Map<number, string>([
  [0, "unknown"],
  [1, "white-dash"],
  [2, "white-solid"],
  [3, "double-white-dash"],
  [4, "double-white-solid"],
  [5, "white-ldash-rsolid"],
  [6, "white-lsolid-rdash"],
  [7, "yellow-dash"],
  [8, "yellow-solid"],
  [9, "double-yellow-dash"],
  [10, "double-yellow-solid"],
  [11, "yellow-ldash-rsolid"],
  [12, "yellow-lsolid-rdash"],
  [20, "left-curbside"],
  [21, "right-curbside"],
]);

const attributeNames = new Map<number, string>([
  [0, "unknown"],
  [1, "left-left"],
  [2, "left"],
  [3, "right"],
  [4, "right-right"],
]);

type UnknownRecord = Record<string, unknown>;

function record(value: unknown, path: string): UnknownRecord {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new TypeError(`${path} must be an object`);
  }
  return value as UnknownRecord;
}

function finiteNumber(value: unknown, path: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new TypeError(`${path} must be a finite number`);
  }
  return value;
}

function integer(value: unknown, path: string): number {
  const parsed = finiteNumber(value, path);
  if (!Number.isSafeInteger(parsed) || parsed < 0) throw new TypeError(`${path} must be a non-negative integer`);
  return parsed;
}

function numericArray(value: unknown, path: string): readonly number[] {
  if (!Array.isArray(value)) throw new TypeError(`${path} must be an array`);
  return value.map((item, index) => finiteNumber(item, `${path}[${index}]`));
}

function matrixRows(value: unknown, rows: number, path: string): readonly (readonly number[])[] {
  if (!Array.isArray(value) || value.length !== rows) throw new TypeError(`${path} must have ${rows} rows`);
  return value.map((row, index) => numericArray(row, `${path}[${index}]`));
}

function matrix(value: unknown, rows: number, columns: number, path: string): readonly (readonly number[])[] {
  return matrixRows(value, rows, path).map((parsed, index) => {
    if (parsed.length !== columns) throw new TypeError(`${path}[${index}] must have ${columns} columns`);
    return parsed;
  });
}

function relativeRef(value: unknown, path: string): string {
  if (typeof value !== "string" || value.length === 0) throw new TypeError(`${path} must be a non-empty string`);
  if (value.startsWith("/") || value.startsWith("\\") || /^[A-Za-z]:[\\/]/.test(value)) {
    throw new TypeError(`${path} must be relative`);
  }
  if (value.split(/[\\/]/).includes("..")) throw new TypeError(`${path} must not traverse its root`);
  return value.replaceAll("\\", "/");
}

function laneLine(value: unknown, imageRef: string, index: number): OpenLaneLane {
  const path = `openlane.lane_lines[${index}]`;
  const line = record(value, path);
  const categoryId = integer(line.category, `${path}.category`);
  const attributeId = integer(line.attribute, `${path}.attribute`);
  const categoryName = categoryNames.get(categoryId);
  const attributeName = attributeNames.get(attributeId);
  if (!categoryName) throw new TypeError(`${path}.category is not an OpenLane category`);
  if (!attributeName) throw new TypeError(`${path}.attribute is not an OpenLane lane attribute`);

  const visibility = numericArray(line.visibility, `${path}.visibility`);
  if (visibility.some((point) => point < 0 || point > 1)) {
    throw new TypeError(`${path}.visibility values must be between 0 and 1`);
  }
  const uv = matrixRows(line.uv, 2, `${path}.uv`);
  const xyz = matrixRows(line.xyz, 3, `${path}.xyz`);
  if (
    visibility.length === 0
    || uv[0]!.length === 0
    || uv[0]!.length !== uv[1]!.length
    || xyz.some((row) => row.length !== visibility.length)
  ) {
    throw new TypeError(`${path} visibility and xyz must have the same point count, and uv rows must match`);
  }

  const trackId = integer(line.track_id, `${path}.track_id`);
  const laneRef = `openlane:${imageRef}#lane:${trackId}`;
  return {
    laneRef,
    lane2dRef: `${laneRef}:2d`,
    lane3dRef: `${laneRef}:3d`,
    trackId,
    category: { id: categoryId, name: categoryName },
    attribute: { id: attributeId, name: attributeName },
    visibility,
    points2d: uv[0]!.map((u, point) => [u, uv[1]![point]!] as const),
    points3d: visibility.map((_, point) => [xyz[0]![point]!, xyz[1]![point]!, xyz[2]![point]!] as const),
  };
}

export function parseOpenLaneAnnotation(
  input: unknown,
  options: { readonly datasetVersion: string; readonly frameRef: string },
): OpenLaneFrame {
  if (options.datasetVersion !== "v1.2") throw new TypeError("OpenLane dataset version must be v1.2");
  const value = record(input, "openlane");
  const frameRef = relativeRef(options.frameRef, "openlane.frame_ref");
  const imageRef = relativeRef(value.file_path, "openlane.file_path");
  if (!Array.isArray(value.lane_lines) || value.lane_lines.length === 0) {
    throw new TypeError("openlane.lane_lines must be a non-empty array");
  }
  const lanes = value.lane_lines.map((line, index) => laneLine(line, imageRef, index));
  if (new Set(lanes.map((lane) => lane.laneRef)).size !== lanes.length) {
    throw new TypeError("openlane.lane_lines track_id values must be unique within a frame");
  }
  return {
    datasetVersion: "v1.2",
    frameRef,
    imageRef,
    intrinsic: matrix(value.intrinsic, 3, 3, "openlane.intrinsic"),
    extrinsic: matrix(value.extrinsic, 4, 4, "openlane.extrinsic"),
    pose: matrix(value.pose, 4, 4, "openlane.pose"),
    lanes,
  };
}

export function createOpenLaneViewModel(frame: OpenLaneFrame, selectedLaneRef?: string): OpenLaneViewModel {
  return {
    frameRef: frame.frameRef,
    lanes: frame.lanes,
    selectedLane: frame.lanes.find((lane) => lane.laneRef === selectedLaneRef) ?? frame.lanes[0] ?? null,
  };
}
