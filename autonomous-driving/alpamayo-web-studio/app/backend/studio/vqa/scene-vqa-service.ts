export const VQA_QUESTION_TEMPLATES = [
  "前方是否有行人或障碍物？",
  "当前是否适合左转或右转？",
  "哪个交通参与者最需要关注？",
  "交通灯或道路标志是什么状态？",
  "画面中存在什么潜在风险？",
] as const;

export type VqaRating = "correct" | "partially_correct" | "incorrect" | "unable_to_determine";

export interface SceneVqaSubmission {
  sceneVersionId: string;
  cameraIds: readonly number[];
  question: string;
}

export interface SceneVqaGenerationRequest extends SceneVqaSubmission {}

export interface SceneVqaGeneration {
  answer: string;
  generationParameters: Record<string, unknown>;
}

export interface SceneVqaResult extends SceneVqaSubmission, SceneVqaGeneration {
  id: string;
  rating: VqaRating | null;
  remark: string;
}

export interface SceneVqaReview {
  rating: VqaRating | null;
  remark: string;
}

export interface SceneVqaPersistenceSnapshot {
  nextResultNumber: number;
  results: SceneVqaResult[];
}

export interface SceneVqaPersistence {
  load(): SceneVqaPersistenceSnapshot;
  replace(snapshot: SceneVqaPersistenceSnapshot): void;
}

export type SceneVqaGenerator = (request: SceneVqaGenerationRequest) => SceneVqaGeneration;

function copy<T>(value: T): T {
  return structuredClone(value);
}

/** Test-friendly adapter; production storage can implement SceneVqaPersistence. */
export class InMemorySceneVqaPersistence implements SceneVqaPersistence {
  private snapshot: SceneVqaPersistenceSnapshot = { nextResultNumber: 1, results: [] };

  load(): SceneVqaPersistenceSnapshot {
    return copy(this.snapshot);
  }

  replace(snapshot: SceneVqaPersistenceSnapshot): void {
    this.snapshot = copy(snapshot);
  }
}

export class SceneVqaService {
  private nextResultNumber: number;
  private readonly results = new Map<string, SceneVqaResult>();

  constructor(
    private readonly persistence: SceneVqaPersistence,
    private readonly generate: SceneVqaGenerator,
  ) {
    const snapshot = persistence.load();
    this.nextResultNumber = snapshot.nextResultNumber;
    for (const result of snapshot.results) this.results.set(result.id, copy(result));
  }

  submit(input: SceneVqaSubmission): SceneVqaResult {
    const request = normalizeSubmission(input);
    const generation = this.generate(copy(request));
    if (!generation.answer.trim()) throw new Error("VQA answer must not be empty.");

    const result: SceneVqaResult = {
      id: `vqa-${this.nextResultNumber++}`,
      ...request,
      answer: generation.answer,
      generationParameters: copy(generation.generationParameters),
      rating: null,
      remark: "",
    };
    this.results.set(result.id, result);
    this.persist();
    return copy(result);
  }

  get(resultId: string): SceneVqaResult | null {
    const result = this.results.get(resultId);
    return result === undefined ? null : copy(result);
  }

  list(sceneVersionId: string): SceneVqaResult[] {
    return [...this.results.values()]
      .filter((result) => result.sceneVersionId === sceneVersionId)
      .map(copy);
  }

  review(resultId: string, review: SceneVqaReview): SceneVqaResult {
    const current = this.requiredResult(resultId);
    validateReview(review);
    const reviewed = { ...current, rating: review.rating, remark: review.remark.trim() };
    this.results.set(resultId, reviewed);
    this.persist();
    return copy(reviewed);
  }

  copyAnswer(resultId: string): string {
    return this.requiredResult(resultId).answer;
  }

  exportResult(resultId: string): string {
    return JSON.stringify(this.requiredResult(resultId));
  }

  private requiredResult(resultId: string): SceneVqaResult {
    const result = this.results.get(resultId);
    if (result === undefined) throw new Error(`VQA result ${resultId} was not found.`);
    return result;
  }

  private persist(): void {
    this.persistence.replace({
      nextResultNumber: this.nextResultNumber,
      results: [...this.results.values()].map(copy),
    });
  }
}

function normalizeSubmission(input: SceneVqaSubmission): SceneVqaSubmission {
  const sceneVersionId = input.sceneVersionId.trim();
  const question = input.question.trim();
  const cameraIds = [...input.cameraIds];
  if (!sceneVersionId) throw new Error("A scene version is required for VQA.");
  if (!question) throw new Error("A VQA question is required.");
  if (cameraIds.length === 0) throw new Error("At least one camera is required for VQA.");
  if (new Set(cameraIds).size !== cameraIds.length || cameraIds.some((cameraId) => !Number.isInteger(cameraId) || cameraId < 0 || cameraId > 6)) {
    throw new Error("VQA camera IDs must be unique integers from 0 to 6.");
  }
  return { sceneVersionId, cameraIds, question };
}

function validateReview(review: SceneVqaReview): void {
  if (typeof review.remark !== "string") throw new Error("VQA review remark must be text.");
  if (review.rating !== null && !["correct", "partially_correct", "incorrect", "unable_to_determine"].includes(review.rating)) {
    throw new Error("VQA review rating is invalid.");
  }
}
