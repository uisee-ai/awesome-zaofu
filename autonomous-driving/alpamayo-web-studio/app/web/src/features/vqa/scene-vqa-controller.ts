export type VqaRating = "correct" | "partially_correct" | "incorrect" | "unable_to_determine";

export interface SceneVqaSubmission {
  sceneVersionId: string;
  cameraIds: readonly number[];
  question: string;
}

export interface SceneVqaResult extends SceneVqaSubmission {
  id: string;
  answer: string;
  generationParameters: Record<string, unknown>;
  rating: VqaRating | null;
  remark: string;
}

export interface SceneVqaReview {
  rating: VqaRating | null;
  remark: string;
}

export interface SceneVqaGateway {
  submit(input: SceneVqaSubmission): Promise<SceneVqaResult>;
  copyAnswer(resultId: string): Promise<string>;
  exportResult(resultId: string): Promise<string>;
  review(resultId: string, review: SceneVqaReview): Promise<SceneVqaResult>;
}

export type SceneVqaState =
  | { phase: "idle" }
  | { phase: "submitting" }
  | { phase: "ready"; result: SceneVqaResult }
  | { phase: "error"; message: string };

export class SceneVqaController {
  state: SceneVqaState = { phase: "idle" };

  constructor(private readonly gateway: SceneVqaGateway) {}

  async submit(input: SceneVqaSubmission): Promise<SceneVqaResult> {
    this.state = { phase: "submitting" };
    try {
      const result = await this.gateway.submit(copy(input));
      this.state = { phase: "ready", result: copy(result) };
      return copy(result);
    } catch (error) {
      const message = error instanceof Error ? error.message : "VQA 提交失败。";
      this.state = { phase: "error", message };
      throw error;
    }
  }

  copyAnswer(resultId: string): Promise<string> {
    return this.gateway.copyAnswer(resultId);
  }

  exportResult(resultId: string): Promise<string> {
    return this.gateway.exportResult(resultId);
  }

  review(resultId: string, review: SceneVqaReview): Promise<SceneVqaResult> {
    return this.gateway.review(resultId, copy(review));
  }
}

export function createSceneVqaController(gateway: SceneVqaGateway): SceneVqaController {
  return new SceneVqaController(gateway);
}

function copy<T>(value: T): T {
  return structuredClone(value);
}
