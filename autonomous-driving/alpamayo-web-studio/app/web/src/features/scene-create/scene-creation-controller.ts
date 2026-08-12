import type { AcceptedAssetUpload } from "../asset-upload/upload-controller.js";

export interface UploadedSceneAsset extends AcceptedAssetUpload {
  assetId: string;
}

export interface SceneCameraSelection {
  cameraId: number;
  assets: UploadedSceneAsset[];
}

export interface SceneCreationRequest {
  name: string;
  description?: string;
  navigationInstruction: string;
  cameras: SceneCameraSelection[];
}

export interface CreatedSceneReference {
  sceneId: string;
  sceneVersionId: string;
}

export type SceneCreator = (request: SceneCreationRequest) => Promise<CreatedSceneReference>;

export type SceneCreationState =
  | { phase: "idle" }
  | { phase: "creating" }
  | { phase: "created"; sceneVersionId: string }
  | { phase: "failed"; error: SceneCreationError };

export class SceneCreationError extends Error {
  constructor(readonly code: "SCENE_NAME_REQUIRED" | "NAVIGATION_REQUIRED" | "ASSET_REQUIRED", message: string) {
    super(message);
    this.name = "SceneCreationError";
  }
}

export class SceneCreationController {
  private state: SceneCreationState = { phase: "idle" };

  constructor(private readonly creator: SceneCreator) {}

  snapshot(): SceneCreationState {
    return this.state;
  }

  async create(request: SceneCreationRequest): Promise<CreatedSceneReference> {
    try {
      validateCreationRequest(request);
    } catch (error) {
      const creationError = error instanceof SceneCreationError
        ? error
        : new SceneCreationError("ASSET_REQUIRED", "无法创建场景。");
      this.state = { phase: "failed", error: creationError };
      throw creationError;
    }

    this.state = { phase: "creating" };
    try {
      const created = await this.creator(snapshotRequest(request));
      this.state = { phase: "created", sceneVersionId: created.sceneVersionId };
      return created;
    } catch (error) {
      const creationError = error instanceof SceneCreationError
        ? error
        : new SceneCreationError("ASSET_REQUIRED", "场景创建请求失败。")
      this.state = { phase: "failed", error: creationError };
      throw creationError;
    }
  }
}

function validateCreationRequest(request: SceneCreationRequest): void {
  if (!request.name.trim()) {
    throw new SceneCreationError("SCENE_NAME_REQUIRED", "场景名称不能为空。");
  }
  if (!request.navigationInstruction.trim()) {
    throw new SceneCreationError("NAVIGATION_REQUIRED", "导航输入不能为空。");
  }
  if (!request.cameras.some((camera) => camera.assets.length > 0)) {
    throw new SceneCreationError("ASSET_REQUIRED", "至少需要一个已上传资产。");
  }
}

function snapshotRequest(request: SceneCreationRequest): SceneCreationRequest {
  return {
    ...request,
    cameras: request.cameras.map((camera) => ({
      ...camera,
      assets: camera.assets.map((asset) => ({ ...asset })),
    })),
  };
}

export function createSceneCreationController(creator: SceneCreator): SceneCreationController {
  return new SceneCreationController(creator);
}
