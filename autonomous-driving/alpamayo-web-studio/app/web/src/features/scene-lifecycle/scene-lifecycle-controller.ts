export interface SceneReference {
  sceneId: string;
  sceneVersionId: string;
}

export interface EditSceneRequest {
  sceneId: string;
  name: string;
  navigationInstruction: string;
}

export interface CopySceneRequest {
  sceneId: string;
  name: string;
}

export interface ArchiveSceneRequest {
  sceneId: string;
}

export interface ArchivedSceneReference {
  sceneId: string;
  isArchived: true;
}

export interface SceneLifecycleGateway {
  edit(request: EditSceneRequest): Promise<SceneReference>;
  copy(request: CopySceneRequest): Promise<SceneReference>;
  archive(request: ArchiveSceneRequest): Promise<ArchivedSceneReference>;
}

export type SceneLifecycleState =
  | { phase: "idle" }
  | { phase: "editing" | "copying" | "archiving" }
  | { phase: "edited" | "copied"; sceneVersionId: string }
  | { phase: "archived"; sceneId: string }
  | { phase: "failed"; error: SceneLifecycleError };

export class SceneLifecycleError extends Error {
  constructor(readonly code: "SCENE_ID_REQUIRED" | "SCENE_NAME_REQUIRED" | "NAVIGATION_REQUIRED", message: string) {
    super(message);
    this.name = "SceneLifecycleError";
  }
}

export class SceneLifecycleController {
  private state: SceneLifecycleState = { phase: "idle" };

  constructor(private readonly gateway: SceneLifecycleGateway) {}

  snapshot(): SceneLifecycleState {
    return this.state;
  }

  async edit(request: EditSceneRequest): Promise<SceneReference> {
    this.validateEdit(request);
    this.state = { phase: "editing" };
    return this.perform(() => this.gateway.edit({ ...request }), (result) => ({ phase: "edited", sceneVersionId: result.sceneVersionId }));
  }

  async copy(request: CopySceneRequest): Promise<SceneReference> {
    this.validateSceneAndName(request);
    this.state = { phase: "copying" };
    return this.perform(() => this.gateway.copy({ ...request }), (result) => ({ phase: "copied", sceneVersionId: result.sceneVersionId }));
  }

  async archive(request: ArchiveSceneRequest): Promise<ArchivedSceneReference> {
    this.validateSceneId(request.sceneId);
    this.state = { phase: "archiving" };
    return this.perform(() => this.gateway.archive({ ...request }), (result) => ({ phase: "archived", sceneId: result.sceneId }));
  }

  private async perform<T>(operation: () => Promise<T>, onSuccess: (result: T) => SceneLifecycleState): Promise<T> {
    try {
      const result = await operation();
      this.state = onSuccess(result);
      return result;
    } catch (error) {
      const lifecycleError = error instanceof SceneLifecycleError
        ? error
        : new SceneLifecycleError("SCENE_ID_REQUIRED", "场景生命周期请求失败。");
      this.state = { phase: "failed", error: lifecycleError };
      throw lifecycleError;
    }
  }

  private validateEdit(request: EditSceneRequest): void {
    this.validateSceneAndName(request);
    if (!request.navigationInstruction.trim()) {
      throw new SceneLifecycleError("NAVIGATION_REQUIRED", "导航输入不能为空。");
    }
  }

  private validateSceneAndName(request: { sceneId: string; name: string }): void {
    this.validateSceneId(request.sceneId);
    if (!request.name.trim()) {
      throw new SceneLifecycleError("SCENE_NAME_REQUIRED", "场景名称不能为空。");
    }
  }

  private validateSceneId(sceneId: string): void {
    if (!sceneId.trim()) {
      throw new SceneLifecycleError("SCENE_ID_REQUIRED", "场景标识不能为空。");
    }
  }
}

export function createSceneLifecycleController(gateway: SceneLifecycleGateway): SceneLifecycleController {
  return new SceneLifecycleController(gateway);
}
