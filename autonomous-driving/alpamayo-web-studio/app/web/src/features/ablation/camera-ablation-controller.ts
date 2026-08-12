import {
  BevTrajectoryVisualization,
  type BevTrajectory,
  type LateralDifferenceSummary,
} from "../trajectory/bev-trajectory-visualization.js";
import type {
  CameraAblationRequest,
  CameraAblationRun,
} from "../../../../backend/studio/ablation/camera-ablation-service.js";

export interface CameraAblationClient {
  run(request: CameraAblationRequest): Promise<CameraAblationRun> | CameraAblationRun;
}

export type CameraCoverageRiskCode = "MISSING_LEFT_SIDE_CAMERA" | "MISSING_RIGHT_SIDE_CAMERA" | "REDUCED_CAMERA_COVERAGE";

export interface CameraCoverageRisk {
  code: CameraCoverageRiskCode;
  severity: "warning";
  message: string;
}

export interface CameraAblationResultView {
  runId: string;
  cameraIds: number[];
  trajectory: BevTrajectory;
  result: {
    chainOfCausation: string;
    metaAction: string;
  };
  risks: CameraCoverageRisk[];
}

export interface CameraAblationComparisonView {
  baseline: CameraAblationResultView;
  ablation: CameraAblationResultView;
  comparison: LateralDifferenceSummary;
}

export interface CameraAblationComparisonRequest {
  baseline: CameraAblationRequest;
  ablation: CameraAblationRequest;
}

/** Framework-neutral controller for the Camera Ablation side-by-side result view. */
export class CameraAblationController {
  constructor(private readonly client: CameraAblationClient) {}

  async compare(request: CameraAblationComparisonRequest): Promise<CameraAblationComparisonView> {
    const [baseline, ablation] = await Promise.all([
      this.client.run(copyRequest(request.baseline)),
      this.client.run(copyRequest(request.ablation)),
    ]);
    const visualization = new BevTrajectoryVisualization({
      baseline: { runId: baseline.id, trajectory: baseline.result.trajectory },
      overlays: [{ runId: ablation.id, trajectory: ablation.result.trajectory }],
    }).snapshot();

    return {
      baseline: presentRun(baseline, visualization.baseline),
      ablation: presentRun(ablation, visualization.overlays[0]),
      comparison: visualization.comparison!,
    };
  }
}

function copyRequest(request: CameraAblationRequest): CameraAblationRequest {
  return {
    preset: request.preset,
    cameraIds: request.cameraIds === undefined ? undefined : [...request.cameraIds],
    parameters: structuredClone(request.parameters),
    seed: request.seed,
  };
}

function presentRun(run: CameraAblationRun, trajectory: BevTrajectory): CameraAblationResultView {
  return {
    runId: run.id,
    cameraIds: [...run.cameraIds],
    trajectory,
    result: {
      chainOfCausation: run.result.chainOfCausation,
      metaAction: run.result.metaAction,
    },
    risks: coverageRisks(run.cameraIds, run.navigationInstruction),
  };
}

function coverageRisks(cameraIds: readonly number[], navigationInstruction?: string): CameraCoverageRisk[] {
  const normalizedInstruction = navigationInstruction?.toLowerCase() ?? "";
  const has = (cameraId: number): boolean => cameraIds.includes(cameraId);
  if ((normalizedInstruction.includes("right") || normalizedInstruction.includes("右转")) && (!has(2) || !has(5))) {
    const missing = [2, 5].filter((cameraId) => !has(cameraId));
    return [{
      code: "MISSING_RIGHT_SIDE_CAMERA",
      severity: "warning",
      message: `右转场景缺少右侧 Camera ID ${missing.join("、")}，可能无法观察侧向来车。`,
    }];
  }
  if ((normalizedInstruction.includes("left") || normalizedInstruction.includes("左转")) && (!has(0) || !has(3))) {
    const missing = [0, 3].filter((cameraId) => !has(cameraId));
    return [{
      code: "MISSING_LEFT_SIDE_CAMERA",
      severity: "warning",
      message: `左转场景缺少左侧 Camera ID ${missing.join("、")}，可能无法观察侧向来车。`,
    }];
  }
  if (cameraIds.length < 4) {
    return [{
      code: "REDUCED_CAMERA_COVERAGE",
      severity: "warning",
      message: "当前组合少于推荐的四路 Camera，视野覆盖可能不足。",
    }];
  }
  return [];
}
