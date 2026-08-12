export const CAMERA_ID_MIN = 0;
export const CAMERA_ID_MAX = 6;
export const CAMERA_COUNT_MIN = 1;
export const CAMERA_COUNT_MAX = 7;
export const FRAME_COUNT_MIN = 1;
export const FRAME_COUNT_MAX = 8;
export const HISTORY_LENGTH = 16;
export const TRAJECTORY_POINT_COUNT = 64;
export const TRAJECTORY_STEP_SECONDS = 0.1;

export type Vector3 = readonly [number, number, number];
export type RotationMatrix3 = readonly [Vector3, Vector3, Vector3];
export type ImageContentType = "image/jpeg" | "image/png";
export type ReviewStatus = "unreviewed" | "approved" | "rejected";

export interface FrameInput {
  contentType: ImageContentType | string;
  filename: string;
}

export interface CameraInput {
  cameraId: number;
  frames: FrameInput[];
}

export interface VehicleHistory {
  positions: Vector3[];
  rotations: RotationMatrix3[];
}

export interface SceneInput {
  name: string;
  description?: string;
  cameras: CameraInput[];
  navigationInstruction?: string;
  history?: VehicleHistory;
  tags?: string[];
  source?: string;
  notes?: string;
}

export interface SceneWarning {
  code: "REDUCED_CAMERA_COVERAGE" | "MISSING_HISTORY";
  severity: "warning";
  message: string;
}

export interface ValidatedScene {
  scene: Omit<SceneInput, "history"> & { history: VehicleHistory };
  warnings: SceneWarning[];
}

export interface TrajectoryPoint {
  timeSeconds: number;
  position: Vector3;
  rotation: RotationMatrix3;
}

export interface InferenceResultInput {
  vqaAnswer: string;
  chainOfCausation: string;
  metaAction: string;
  trajectory: TrajectoryPoint[];
  modelName?: string;
  modelVersion?: string;
  parameters?: Record<string, unknown>;
  seed?: number;
  queueDurationMs?: number;
  inferenceDurationMs?: number;
  totalDurationMs?: number;
  rawResponse?: unknown;
  errorMessage?: string;
  reviewStatus?: ReviewStatus;
}

export interface InferenceResult extends InferenceResultInput {
  reviewStatus: ReviewStatus;
}

export type SceneContractErrorCode =
  | "CAMERA_COUNT"
  | "CAMERA_ID"
  | "DUPLICATE_CAMERA_ID"
  | "FRAME_COUNT"
  | "FRAME_COUNT_MISMATCH"
  | "FRAME_FORMAT"
  | "HISTORY_LENGTH"
  | "HISTORY_SHAPE"
  | "TRAJECTORY_LENGTH"
  | "TRAJECTORY_TIMESTEP"
  | "TRAJECTORY_SHAPE"
  | "REQUIRED_RESULT_FIELD";

export class SceneContractError extends Error {
  constructor(
    public readonly code: SceneContractErrorCode,
    message: string,
  ) {
    super(message);
    this.name = "SceneContractError";
  }
}

const supportedImages: Readonly<Record<ImageContentType, RegExp>> = {
  "image/jpeg": /\.jpe?g$/i,
  "image/png": /\.png$/i,
};

function stationaryHistory(): VehicleHistory {
  return {
    positions: Array.from({ length: HISTORY_LENGTH }, () => [0, 0, 0] as const),
    rotations: Array.from({ length: HISTORY_LENGTH }, () => [
      [1, 0, 0],
      [0, 1, 0],
      [0, 0, 1],
    ] as const),
  };
}

function isFiniteVector3(value: unknown): value is Vector3 {
  return Array.isArray(value)
    && value.length === 3
    && value.every((coordinate) => typeof coordinate === "number" && Number.isFinite(coordinate));
}

function isRotationMatrix3(value: unknown): value is RotationMatrix3 {
  return Array.isArray(value) && value.length === 3 && value.every(isFiniteVector3);
}

function validateHistory(history: VehicleHistory): void {
  if (history.positions.length !== HISTORY_LENGTH || history.rotations.length !== HISTORY_LENGTH) {
    throw new SceneContractError(
      "HISTORY_LENGTH",
      `车辆历史位置和旋转矩阵都必须包含 ${HISTORY_LENGTH} 条记录。`,
    );
  }
  if (!history.positions.every(isFiniteVector3) || !history.rotations.every(isRotationMatrix3)) {
    throw new SceneContractError("HISTORY_SHAPE", "车辆历史必须是 [16, 3] 和 [16, 3, 3] 的有限数字。");
  }
}

function validateCameras(cameras: CameraInput[]): void {
  if (cameras.length < CAMERA_COUNT_MIN || cameras.length > CAMERA_COUNT_MAX) {
    throw new SceneContractError("CAMERA_COUNT", `场景必须包含 ${CAMERA_COUNT_MIN}–${CAMERA_COUNT_MAX} 路 Camera。`);
  }

  const ids = new Set<number>();
  let expectedFrameCount: number | undefined;
  for (const camera of cameras) {
    if (!Number.isInteger(camera.cameraId) || camera.cameraId < CAMERA_ID_MIN || camera.cameraId > CAMERA_ID_MAX) {
      throw new SceneContractError("CAMERA_ID", `Camera ID 必须是 ${CAMERA_ID_MIN}–${CAMERA_ID_MAX} 的整数。`);
    }
    if (ids.has(camera.cameraId)) {
      throw new SceneContractError("DUPLICATE_CAMERA_ID", "同一场景不能重复使用 Camera ID。");
    }
    ids.add(camera.cameraId);
    if (camera.frames.length < FRAME_COUNT_MIN || camera.frames.length > FRAME_COUNT_MAX) {
      throw new SceneContractError("FRAME_COUNT", `每路 Camera 必须包含 ${FRAME_COUNT_MIN}–${FRAME_COUNT_MAX} 帧。`);
    }
    if (expectedFrameCount === undefined) {
      expectedFrameCount = camera.frames.length;
    } else if (camera.frames.length !== expectedFrameCount) {
      throw new SceneContractError("FRAME_COUNT_MISMATCH", "同一场景中所有 Camera 的帧数必须相同。");
    }
    for (const frame of camera.frames) {
      if (!(frame.contentType in supportedImages) || !supportedImages[frame.contentType as ImageContentType].test(frame.filename)) {
        throw new SceneContractError("FRAME_FORMAT", "图片必须是扩展名与 MIME 一致的 JPEG 或 PNG。");
      }
    }
  }
}

export function validateSceneInput(input: SceneInput): ValidatedScene {
  validateCameras(input.cameras);
  const warnings: SceneWarning[] = [];
  if (input.cameras.length < 4) {
    warnings.push({ code: "REDUCED_CAMERA_COVERAGE", severity: "warning", message: "Camera 少于推荐的四路，推理结果质量可能受影响。" });
  }
  const history = input.history ?? stationaryHistory();
  if (input.history === undefined) {
    warnings.push({ code: "MISSING_HISTORY", severity: "warning", message: "车辆历史缺失；将使用静止车辆默认值，结果必须人工审核。" });
  }
  validateHistory(history);
  return { scene: { ...input, history }, warnings };
}

function requireText(value: string, field: string): void {
  if (value.trim().length === 0) {
    throw new SceneContractError("REQUIRED_RESULT_FIELD", `${field} 是必填结果字段。`);
  }
}

function validateTrajectory(trajectory: TrajectoryPoint[]): void {
  if (trajectory.length !== TRAJECTORY_POINT_COUNT) {
    throw new SceneContractError("TRAJECTORY_LENGTH", `未来轨迹必须包含 ${TRAJECTORY_POINT_COUNT} 个时间点。`);
  }
  for (const [index, point] of trajectory.entries()) {
    const expectedTime = Number(((index + 1) * TRAJECTORY_STEP_SECONDS).toFixed(1));
    if (point.timeSeconds !== expectedTime) {
      throw new SceneContractError("TRAJECTORY_TIMESTEP", `第 ${index + 1} 个轨迹点必须位于 ${expectedTime} 秒。`);
    }
    if (!isFiniteVector3(point.position) || !isRotationMatrix3(point.rotation)) {
      throw new SceneContractError("TRAJECTORY_SHAPE", "每个轨迹点必须包含有限的 XYZ 和 3×3 旋转矩阵。");
    }
  }
}

export function createInferenceResult(input: InferenceResultInput): InferenceResult {
  requireText(input.vqaAnswer, "VQA Answer");
  requireText(input.chainOfCausation, "Chain-of-Causation");
  requireText(input.metaAction, "Meta Action");
  validateTrajectory(input.trajectory);
  return { ...input, reviewStatus: input.reviewStatus ?? "unreviewed" };
}
