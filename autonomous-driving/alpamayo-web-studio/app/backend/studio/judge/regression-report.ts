export type RegressionRunStatus = "succeeded" | "failed";
export type HumanJudgeVerdict = "approved" | "rejected" | "needs_review";

export interface RegressionTrajectoryPoint {
  timeSeconds: number;
  position: readonly [number, number, number];
  rotation: readonly (readonly [number, number, number])[];
}

export interface RegressionOutput {
  chainOfCausation: string;
  metaAction: string;
  trajectory: readonly RegressionTrajectoryPoint[];
}

export interface RegressionRun {
  id: string;
  sceneVersionId: string;
  status: RegressionRunStatus;
  durationMs: number;
  model: {
    name: string;
    version: string;
    parameters: Record<string, unknown>;
  };
  rawOutput: Record<string, unknown>;
  output?: RegressionOutput;
}

export interface JudgeDecision {
  sceneVersionId: string;
  verdict: HumanJudgeVerdict;
  reviewerId: string;
  note: string;
  judgedAt: string;
}

export interface RegressionReportInput {
  baseline: readonly RegressionRun[];
  candidate: readonly RegressionRun[];
}

export interface RegressionReportScene {
  sceneVersionId: string;
  baseline: RegressionRun;
  candidate: RegressionRun | null;
  coc: { changed: boolean; similarity: number | null } | null;
  metaAction: { consistent: boolean } | null;
  trajectory: { averagePointDifference: number; endpointDifference: number } | null;
  links: {
    scene: string;
    baselineRawOutput: string;
    candidateRawOutput: string | null;
  };
  provenance: {
    baseline: { model: RegressionRun["model"] };
    candidate: { model: RegressionRun["model"] } | null;
  };
  judgeDecisions: JudgeDecision[];
}

export interface RegressionReport {
  id: string;
  summary: {
    successRate: { baseline: number; candidate: number; delta: number };
    averageLatencyMs: { baseline: number; candidate: number; delta: number };
  };
  scenes: RegressionReportScene[];
}

export interface RegressionReportStore {
  load(): RegressionReport[];
  replace(reports: RegressionReport[]): void;
}

const copy = <T>(value: T): T => structuredClone(value);

/** Process-local persistence adapter; a database adapter can retain the same immutable report shape. */
export class InMemoryRegressionReportStore implements RegressionReportStore {
  private reports: RegressionReport[] = [];

  load(): RegressionReport[] {
    return copy(this.reports);
  }

  replace(reports: RegressionReport[]): void {
    this.reports = copy(reports);
  }
}

/**
 * Compares two completed evaluation batches without modifying their recorded
 * model outputs. Human Judge decisions are appended as separate report data.
 */
export class RegressionReportService {
  private readonly reports = new Map<string, RegressionReport>();
  private sequence = 0;

  constructor(private readonly store: RegressionReportStore) {
    for (const report of store.load()) {
      this.reports.set(report.id, copy(report));
      this.sequence = Math.max(this.sequence, numericSuffix(report.id));
    }
  }

  compare(input: RegressionReportInput): RegressionReport {
    const baseline = indexRuns(input.baseline, "baseline");
    const candidate = indexRuns(input.candidate, "candidate");
    if (baseline.size === 0 || candidate.size === 0) {
      throw new Error("Both baseline and candidate batches must contain at least one run.");
    }

    const scenes = [...baseline.values()].map((baselineRun) => createScene(baselineRun, candidate.get(baselineRun.sceneVersionId) ?? null));
    const report: RegressionReport = {
      id: `regression-report-${++this.sequence}`,
      summary: {
        successRate: comparison(successRate(input.baseline), successRate(input.candidate)),
        averageLatencyMs: comparison(averageLatency(input.baseline), averageLatency(input.candidate)),
      },
      scenes,
    };
    this.reports.set(report.id, report);
    this.persist();
    return copy(report);
  }

  get(reportId: string): RegressionReport | null {
    const report = this.reports.get(reportId);
    return report === undefined ? null : copy(report);
  }

  submitJudge(reportId: string, decision: JudgeDecision): JudgeDecision {
    validateDecision(decision);
    const report = this.requiredReport(reportId);
    const scene = report.scenes.find((entry) => entry.sceneVersionId === decision.sceneVersionId);
    if (scene === undefined) throw new Error(`Scene ${decision.sceneVersionId} is not part of report ${reportId}.`);

    scene.judgeDecisions.push(copy(decision));
    this.persist();
    return copy(decision);
  }

  private requiredReport(reportId: string): RegressionReport {
    const report = this.reports.get(reportId);
    if (report === undefined) throw new Error(`Regression report ${reportId} was not found.`);
    return report;
  }

  private persist(): void {
    this.store.replace([...this.reports.values()]);
  }
}

function indexRuns(runs: readonly RegressionRun[], batch: string): Map<string, RegressionRun> {
  const indexed = new Map<string, RegressionRun>();
  for (const run of runs) {
    validateRun(run);
    if (indexed.has(run.sceneVersionId)) throw new Error(`${batch} batch contains duplicate scene ${run.sceneVersionId}.`);
    indexed.set(run.sceneVersionId, copy(run));
  }
  return indexed;
}

function validateRun(run: RegressionRun): void {
  if (!run.id.trim() || !run.sceneVersionId.trim()) throw new Error("A regression run requires an id and scene version id.");
  if (!Number.isFinite(run.durationMs) || run.durationMs < 0) throw new Error("Run duration must be a non-negative finite number.");
  if (!run.model.name.trim() || !run.model.version.trim()) throw new Error("Run model name and version are required for report provenance.");
  if (run.status === "succeeded" && run.output === undefined) throw new Error("Succeeded runs require structured output.");
  if (run.output !== undefined) validateOutput(run.output);
}

function validateOutput(output: RegressionOutput): void {
  if (!output.chainOfCausation.trim() || !output.metaAction.trim()) throw new Error("CoC and Meta Action are required in regression output.");
  if (output.trajectory.length !== 64) throw new Error("Regression trajectories must contain 64 points.");
}

function createScene(baseline: RegressionRun, candidate: RegressionRun | null): RegressionReportScene {
  let coc: RegressionReportScene["coc"] = null;
  let metaAction: RegressionReportScene["metaAction"] = null;
  let trajectory: RegressionReportScene["trajectory"] = null;
  if (baseline.status === "succeeded" && candidate?.status === "succeeded" && baseline.output !== undefined && candidate.output !== undefined) {
    coc = cocComparison(baseline.output.chainOfCausation, candidate.output.chainOfCausation);
    metaAction = { consistent: normalize(baseline.output.metaAction) === normalize(candidate.output.metaAction) };
    trajectory = trajectoryComparison(baseline.output.trajectory, candidate.output.trajectory);
  }
  return {
    sceneVersionId: baseline.sceneVersionId,
    baseline: copy(baseline),
    candidate: candidate === null ? null : copy(candidate),
    coc,
    metaAction,
    trajectory,
    links: {
      scene: `/scenes/${baseline.sceneVersionId}`,
      baselineRawOutput: `/runs/${baseline.id}/raw-output`,
      candidateRawOutput: candidate === null ? null : `/runs/${candidate.id}/raw-output`,
    },
    provenance: {
      baseline: { model: copy(baseline.model) },
      candidate: candidate === null ? null : { model: copy(candidate.model) },
    },
    judgeDecisions: [],
  };
}

function successRate(runs: readonly RegressionRun[]): number {
  return runs.filter((run) => run.status === "succeeded").length / runs.length;
}

function averageLatency(runs: readonly RegressionRun[]): number {
  return runs.reduce((total, run) => total + run.durationMs, 0) / runs.length;
}

function comparison(baseline: number, candidate: number): { baseline: number; candidate: number; delta: number } {
  return { baseline, candidate, delta: candidate - baseline };
}

function cocComparison(baseline: string, candidate: string): { changed: boolean; similarity: number } {
  const baselineTerms = new Set(tokens(baseline));
  const candidateTerms = new Set(tokens(candidate));
  const union = new Set([...baselineTerms, ...candidateTerms]);
  const overlap = [...baselineTerms].filter((term) => candidateTerms.has(term)).length;
  return { changed: normalize(baseline) !== normalize(candidate), similarity: union.size === 0 ? 1 : round(overlap / union.size) };
}

function trajectoryComparison(
  baseline: readonly RegressionTrajectoryPoint[],
  candidate: readonly RegressionTrajectoryPoint[],
): { averagePointDifference: number; endpointDifference: number } {
  const differences = baseline.map((point, index) => distance(point.position, candidate[index]!.position));
  return {
    averagePointDifference: round(differences.reduce((total, difference) => total + difference, 0) / differences.length),
    endpointDifference: round(differences.at(-1) ?? 0),
  };
}

function distance(left: readonly number[], right: readonly number[]): number {
  return Math.sqrt(left.reduce((sum, value, index) => sum + (value - right[index]!) ** 2, 0));
}

function tokens(value: string): string[] {
  return normalize(value).split(/[\s,，。；;、]+/).filter(Boolean);
}

function normalize(value: string): string {
  return value.trim().replace(/\s+/g, " ").toLocaleLowerCase();
}

function round(value: number): number {
  return Number(value.toFixed(6));
}

function validateDecision(decision: JudgeDecision): void {
  if (!decision.sceneVersionId.trim() || !decision.reviewerId.trim() || !decision.note.trim()) {
    throw new Error("Judge decisions require a scene, reviewer, and note.");
  }
  if (!Number.isFinite(Date.parse(decision.judgedAt))) throw new Error("Judge decision time must be ISO-8601.");
}

function numericSuffix(id: string): number {
  const matched = /-(\d+)$/.exec(id);
  return matched === null ? 0 : Number(matched[1]);
}
