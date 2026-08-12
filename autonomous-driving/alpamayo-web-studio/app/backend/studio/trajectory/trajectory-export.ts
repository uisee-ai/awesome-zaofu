import type {
  BevTrajectory,
  BevVisualizationSnapshot,
  LateralDifferenceSummary,
} from "../../../web/src/features/trajectory/bev-trajectory-visualization.js";

export type TrajectoryExportErrorCode = "BASELINE_POINT_COUNT" | "OVERLAY_POINT_COUNT";

export class TrajectoryExportError extends Error {
  constructor(
    readonly code: TrajectoryExportErrorCode,
    message: string,
  ) {
    super(message);
    this.name = "TrajectoryExportError";
  }
}

export interface TrajectoryExportDocument {
  schemaVersion: "bev-trajectory-export.v1";
  baseline: BevTrajectory;
  overlays: BevTrajectory[];
  comparison: LateralDifferenceSummary | null;
}

function validateTrajectory(trajectory: BevTrajectory, code: TrajectoryExportErrorCode): void {
  if (trajectory.points.length !== 64) {
    throw new TrajectoryExportError(code, "导出的每条 BEV 轨迹必须完整包含 64 个未来点。");
  }
}

/** Converts the UI-neutral BEV snapshot into the Studio Backend download payload. */
export function createTrajectoryExport(snapshot: BevVisualizationSnapshot): TrajectoryExportDocument {
  validateTrajectory(snapshot.baseline, "BASELINE_POINT_COUNT");
  for (const overlay of snapshot.overlays) {
    validateTrajectory(overlay, "OVERLAY_POINT_COUNT");
  }

  return {
    schemaVersion: "bev-trajectory-export.v1",
    baseline: structuredClone(snapshot.baseline),
    overlays: structuredClone(snapshot.overlays),
    comparison: structuredClone(snapshot.comparison),
  };
}
