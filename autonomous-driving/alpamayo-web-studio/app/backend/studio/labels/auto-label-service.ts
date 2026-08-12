export type LabelCategory =
  | "roadStructure"
  | "trafficParticipants"
  | "potentialRisks"
  | "navigationIntent"
  | "metaAction"
  | "longTailSceneType";

export type CandidateLabels = Record<LabelCategory, string[]>;
export type ReviewStatus = "pending" | "accepted" | "modified" | "rejected";
export type ReviewDecision = Exclude<ReviewStatus, "pending">;

export interface GenerateAutoLabelInput {
  sceneId: string;
  modelVersion: string;
  rawModelOutput: Record<string, unknown> & { candidates: CandidateLabels };
}

export interface ReviewInput {
  decision: ReviewDecision;
  actor: string;
  labels?: CandidateLabels;
  cocSummary?: string;
}

export interface LabelReview {
  decision: ReviewDecision;
  actor: string;
  at: string;
  changes: Record<string, unknown>;
}

export interface AutoLabelAnnotation {
  id: string;
  sceneId: string;
  modelVersion: string;
  rawModelOutput: GenerateAutoLabelInput["rawModelOutput"];
  candidateLabels: CandidateLabels;
  reviewedLabels: CandidateLabels;
  cocSummary?: string;
  reviewStatus: ReviewStatus;
  reviews: LabelReview[];
  createdAt: string;
}

export interface AutoLabelFilter {
  reviewStatus?: ReviewStatus;
  modelVersion?: string;
  tag?: string;
  from?: string;
  to?: string;
}

export interface AutoLabelPersistence {
  load(): AutoLabelAnnotation[];
  replace(annotations: AutoLabelAnnotation[]): void;
}

function copy<T>(value: T): T {
  return structuredClone(value);
}

export class InMemoryAutoLabelPersistence implements AutoLabelPersistence {
  private records: AutoLabelAnnotation[] = [];

  load(): AutoLabelAnnotation[] {
    return copy(this.records);
  }

  replace(annotations: AutoLabelAnnotation[]): void {
    this.records = copy(annotations);
  }
}

/** Keeps model output immutable while storing a complete human review trail. */
export class AutoLabelService {
  private readonly records = new Map<string, AutoLabelAnnotation>();
  private sequence = 0;

  constructor(
    private readonly persistence: AutoLabelPersistence,
    private readonly now: () => Date = () => new Date(),
  ) {
    for (const annotation of persistence.load()) {
      this.records.set(annotation.id, copy(annotation));
      this.sequence = Math.max(this.sequence, sequenceFromId(annotation.id));
    }
  }

  generate(input: GenerateAutoLabelInput): AutoLabelAnnotation {
    const candidateLabels = copy(input.rawModelOutput.candidates);
    const annotation: AutoLabelAnnotation = {
      id: `auto-label-${++this.sequence}`,
      sceneId: input.sceneId,
      modelVersion: input.modelVersion,
      rawModelOutput: copy(input.rawModelOutput),
      candidateLabels,
      reviewedLabels: copy(candidateLabels),
      reviewStatus: "pending",
      reviews: [],
      createdAt: this.now().toISOString(),
    };
    this.replace(annotation);
    return copy(annotation);
  }

  review(annotationId: string, input: ReviewInput): AutoLabelAnnotation {
    const current = this.requireAnnotation(annotationId);
    if (input.decision === "modified" && input.labels === undefined && input.cocSummary === undefined) {
      throw new Error("已修改审核必须提供标签或 CoC 摘要。");
    }

    const reviewedLabels = input.labels === undefined ? current.reviewedLabels : copy(input.labels);
    const cocSummary = input.cocSummary === undefined ? current.cocSummary : input.cocSummary;
    const changes = reviewChanges(current, reviewedLabels, cocSummary);
    const review: LabelReview = {
      decision: input.decision,
      actor: input.actor,
      at: this.now().toISOString(),
      changes,
    };
    const next: AutoLabelAnnotation = {
      ...current,
      reviewedLabels,
      cocSummary,
      reviewStatus: input.decision,
      reviews: [...current.reviews, review],
    };
    this.replace(next);
    return copy(next);
  }

  list(filter: AutoLabelFilter = {}): AutoLabelAnnotation[] {
    return [...this.records.values()]
      .filter((annotation) => matchesFilter(annotation, filter))
      .map(copy);
  }

  exportJsonl(filter: AutoLabelFilter = {}): string {
    const records = this.list(filter).map((annotation) => JSON.stringify({
      sceneId: annotation.sceneId,
      modelVersion: annotation.modelVersion,
      reviewStatus: annotation.reviewStatus,
      candidateLabels: annotation.candidateLabels,
      reviewedLabels: annotation.reviewedLabels,
    }));
    return records.length === 0 ? "" : `${records.join("\n")}\n`;
  }

  private requireAnnotation(annotationId: string): AutoLabelAnnotation {
    const annotation = this.records.get(annotationId);
    if (annotation === undefined) throw new Error(`Unknown auto label annotation: ${annotationId}`);
    return annotation;
  }

  private replace(annotation: AutoLabelAnnotation): void {
    this.records.set(annotation.id, copy(annotation));
    this.persistence.replace([...this.records.values()]);
  }
}

function reviewChanges(
  current: AutoLabelAnnotation,
  reviewedLabels: CandidateLabels,
  cocSummary: string | undefined,
): Record<string, unknown> {
  const labelChanges: Record<string, unknown> = {};
  for (const category of Object.keys(current.reviewedLabels) as LabelCategory[]) {
    if (JSON.stringify(current.reviewedLabels[category]) !== JSON.stringify(reviewedLabels[category])) {
      labelChanges[category] = { before: current.reviewedLabels[category], after: reviewedLabels[category] };
    }
  }
  const changes: Record<string, unknown> = {};
  if (Object.keys(labelChanges).length > 0) changes.labels = labelChanges;
  if (current.cocSummary !== cocSummary) changes.cocSummary = { before: current.cocSummary, after: cocSummary };
  return changes;
}

function matchesFilter(annotation: AutoLabelAnnotation, filter: AutoLabelFilter): boolean {
  if (filter.reviewStatus !== undefined && annotation.reviewStatus !== filter.reviewStatus) return false;
  if (filter.modelVersion !== undefined && annotation.modelVersion !== filter.modelVersion) return false;
  if (filter.from !== undefined && annotation.createdAt < filter.from) return false;
  if (filter.to !== undefined && annotation.createdAt > filter.to) return false;
  if (filter.tag !== undefined && !Object.values(annotation.reviewedLabels).flat().includes(filter.tag)) return false;
  return true;
}

function sequenceFromId(id: string): number {
  const match = /^auto-label-(\d+)$/.exec(id);
  return match === null ? 0 : Number(match[1]);
}
