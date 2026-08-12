export type SceneDeletionGateway = (sceneId: string) => Promise<void>;

export type SceneDeletionState =
  | { phase: "idle" }
  | { phase: "awaiting_confirmation"; sceneId: string }
  | { phase: "deleting"; sceneId: string }
  | { phase: "deleted"; sceneId: string }
  | { phase: "failed"; sceneId: string; error: SceneDeletionError };

export class SceneDeletionError extends Error {
  constructor(
    readonly code: "SCENE_ID_REQUIRED" | "CONFIRMATION_REQUIRED" | "DELETE_FAILED",
    message: string,
  ) {
    super(message);
    this.name = "SceneDeletionError";
  }
}

export class SceneDeletionController {
  private state: SceneDeletionState = { phase: "idle" };

  constructor(private readonly deleteScene: SceneDeletionGateway) {}

  snapshot(): SceneDeletionState {
    return this.state;
  }

  requestDeletion(sceneId: string): void {
    if (!sceneId.trim()) {
      throw new SceneDeletionError("SCENE_ID_REQUIRED", "必须选择要删除的场景。");
    }
    this.state = { phase: "awaiting_confirmation", sceneId };
  }

  async confirmDeletion(): Promise<void> {
    if (this.state.phase !== "awaiting_confirmation") {
      throw new SceneDeletionError("CONFIRMATION_REQUIRED", "请先确认要删除的场景。");
    }

    const { sceneId } = this.state;
    this.state = { phase: "deleting", sceneId };
    try {
      await this.deleteScene(sceneId);
      this.state = { phase: "deleted", sceneId };
    } catch (error) {
      const deletionError = error instanceof SceneDeletionError
        ? error
        : new SceneDeletionError("DELETE_FAILED", "场景删除请求失败。");
      this.state = { phase: "failed", sceneId, error: deletionError };
      throw deletionError;
    }
  }
}

export function createSceneDeletionController(deleteScene: SceneDeletionGateway): SceneDeletionController {
  return new SceneDeletionController(deleteScene);
}
