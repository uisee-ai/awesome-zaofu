import {
  type JudgeDecision,
  type RegressionReport,
  type RegressionReportService,
} from "../../../../backend/studio/judge/regression-report.js";

export type RegressionOutputSide = "baseline" | "candidate";

/** Renderer-neutral report view model for scene and immutable raw-output navigation. */
export class RegressionReportPanel {
  constructor(
    private readonly reports: RegressionReportService,
    private readonly reportId: string,
  ) {}

  snapshot(): RegressionReport {
    const report = this.reports.get(this.reportId);
    if (report === null) throw new Error(`Regression report ${this.reportId} is not available.`);
    return report;
  }

  navigateToScene(sceneVersionId: string): string {
    return this.requiredScene(sceneVersionId).links.scene;
  }

  navigateToRawOutput(sceneVersionId: string, side: RegressionOutputSide): string {
    const links = this.requiredScene(sceneVersionId).links;
    const target = side === "baseline" ? links.baselineRawOutput : links.candidateRawOutput;
    if (target === null) throw new Error(`No ${side} raw output is available for scene ${sceneVersionId}.`);
    return target;
  }

  submitJudge(decision: JudgeDecision): JudgeDecision {
    return this.reports.submitJudge(this.reportId, decision);
  }

  private requiredScene(sceneVersionId: string) {
    const scene = this.snapshot().scenes.find((entry) => entry.sceneVersionId === sceneVersionId);
    if (scene === undefined) throw new Error(`Scene ${sceneVersionId} is not in this regression report.`);
    return scene;
  }
}
