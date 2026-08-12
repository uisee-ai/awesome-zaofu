import type { TrajectoryPoint } from "../../../packages/contracts/src/scene.js";

export type CameraAblationPreset = "front-only" | "front-three" | "standard-four" | "all-cameras";

export interface CameraAblationScene {
  id: string;
  /** The IDs already present in the selected immutable scene version. */
  cameraIds: readonly number[];
  navigationInstruction?: string;
}

export interface CameraAblationInferenceRequest {
  sceneId: string;
  cameraIds: readonly number[];
  parameters: Readonly<Record<string, unknown>>;
  seed: number;
}

export interface CameraAblationInferenceResult {
  chainOfCausation: string;
  metaAction: string;
  trajectory: readonly TrajectoryPoint[];
}

export type CameraAblationInference = (
  request: Readonly<CameraAblationInferenceRequest>,
) => Promise<CameraAblationInferenceResult>;

export interface CameraAblationRequest {
  preset?: CameraAblationPreset;
  cameraIds?: readonly number[];
  parameters: Readonly<Record<string, unknown>>;
  seed: number;
}

export interface CameraAblationRun {
  id: string;
  sceneId: string;
  navigationInstruction?: string;
  cameraIds: number[];
  preset: CameraAblationPreset | null;
  parameters: Record<string, unknown>;
  seed: number;
  /** A combination references selected scene assets, so no re-upload is needed. */
  uploadRequired: false;
  result: CameraAblationInferenceResult;
}

export type CameraAblationErrorCode =
  | "COMBINATION_REQUIRED"
  | "COMBINATION_CONFLICT"
  | "EMPTY_COMBINATION"
  | "DUPLICATE_CAMERA_ID"
  | "CAMERA_NOT_IN_SCENE";

export class CameraAblationError extends Error {
  constructor(
    readonly code: CameraAblationErrorCode,
    message: string,
  ) {
    super(message);
    this.name = "CameraAblationError";
  }
}

const PRESET_CAMERA_IDS: Readonly<Record<Exclude<CameraAblationPreset, "all-cameras">, readonly number[]>> = {
  "front-only": [1],
  "front-three": [0, 1, 2],
  "standard-four": [0, 1, 2, 6],
};

function cloneResult(result: CameraAblationInferenceResult): CameraAblationInferenceResult {
  return structuredClone(result);
}

function normalizedCameraIds(cameraIds: readonly number[]): number[] {
  if (cameraIds.length === 0) {
    throw new CameraAblationError("EMPTY_COMBINATION", "Camera 组合至少需要包含一路 Camera。");
  }
  const sorted = [...cameraIds].sort((left, right) => left - right);
  if (new Set(sorted).size !== sorted.length) {
    throw new CameraAblationError("DUPLICATE_CAMERA_ID", "Camera 组合不能包含重复的 Camera ID。");
  }
  return sorted;
}

/**
 * Runs camera experiments only against assets already contained by a scene.
 * The service deliberately stores the selected IDs on every record so results
 * remain interpretable after an experiment has been named or exported.
 */
export class CameraAblationService {
  private sequence = 0;

  constructor(
    private readonly scene: CameraAblationScene,
    private readonly infer: CameraAblationInference,
  ) {}

  async run(request: CameraAblationRequest): Promise<CameraAblationRun> {
    const cameraIds = this.resolveCameraIds(request);
    const result = await this.infer({
      sceneId: this.scene.id,
      cameraIds: [...cameraIds],
      parameters: structuredClone(request.parameters),
      seed: request.seed,
    });

    return {
      id: `camera-ablation-run-${++this.sequence}`,
      sceneId: this.scene.id,
      navigationInstruction: this.scene.navigationInstruction,
      cameraIds,
      preset: request.preset ?? null,
      parameters: structuredClone(request.parameters),
      seed: request.seed,
      uploadRequired: false,
      result: cloneResult(result),
    };
  }

  private resolveCameraIds(request: CameraAblationRequest): number[] {
    if (request.preset === undefined && request.cameraIds === undefined) {
      throw new CameraAblationError("COMBINATION_REQUIRED", "请选择预置或自选 Camera 组合。");
    }
    if (request.preset !== undefined && request.cameraIds !== undefined) {
      throw new CameraAblationError("COMBINATION_CONFLICT", "预置组合与自选 Camera 组合不能同时使用。");
    }

    const requested = request.cameraIds
      ?? (request.preset === "all-cameras" ? this.scene.cameraIds : PRESET_CAMERA_IDS[request.preset as Exclude<CameraAblationPreset, "all-cameras">]);
    const selected = normalizedCameraIds(requested);
    const available = new Set(this.scene.cameraIds);
    const missing = selected.filter((cameraId) => !available.has(cameraId));
    if (missing.length > 0) {
      throw new CameraAblationError(
        "CAMERA_NOT_IN_SCENE",
        `Camera ID ${missing.join("、")} 不存在于当前场景，不能重新上传或虚构输入。`,
      );
    }
    return selected;
  }
}
