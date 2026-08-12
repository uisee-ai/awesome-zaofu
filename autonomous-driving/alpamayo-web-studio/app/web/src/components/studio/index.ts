export interface CameraFrameView {
  contentType: string;
  filename: string;
}

export interface CameraSequenceView {
  cameraId: number;
  frames: readonly CameraFrameView[];
}

export interface CameraVisualizationProps {
  cameras: readonly CameraSequenceView[];
  selectedFrameIndex: number;
}

export interface CameraVisualization {
  selectedFrameIndex: number;
  cameras: Array<{ cameraId: number; frame: CameraFrameView }>;
}

/**
 * Produces a synchronised camera view model that any Studio demo can render.
 * Camera IDs are sorted so every consumer presents the same stable order.
 */
export function createCameraVisualization({
  cameras,
  selectedFrameIndex,
}: CameraVisualizationProps): CameraVisualization {
  if (!Number.isInteger(selectedFrameIndex) || selectedFrameIndex < 0) {
    throw new RangeError("selectedFrameIndex must be a non-negative integer");
  }

  return {
    selectedFrameIndex,
    cameras: [...cameras]
      .sort((left, right) => left.cameraId - right.cameraId)
      .map((camera) => {
        const frame = camera.frames[selectedFrameIndex];
        if (frame === undefined) {
          throw new RangeError(`Camera ${camera.cameraId} has no frame at index ${selectedFrameIndex}`);
        }
        return { cameraId: camera.cameraId, frame };
      }),
  };
}

export type RunStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled";
export type RunStatusTone = "neutral" | "info" | "success" | "danger" | "warning";

export interface RunStatusVisualization {
  status: RunStatus;
  label: string;
  tone: RunStatusTone;
}

const runStatusViews: Readonly<Record<RunStatus, Omit<RunStatusVisualization, "status">>> = {
  queued: { label: "等待中", tone: "neutral" },
  running: { label: "运行中", tone: "info" },
  succeeded: { label: "已成功", tone: "success" },
  failed: { label: "失败", tone: "danger" },
  cancelled: { label: "已取消", tone: "warning" },
};

/** Returns display copy and a semantic tone for a persisted inference run. */
export function createRunStatusVisualization(status: RunStatus): RunStatusVisualization {
  return { status, ...runStatusViews[status] };
}

export interface InferenceVisualizationProps {
  chainOfCausation: string;
  metaAction: string;
}

export interface InferenceVisualization extends InferenceVisualizationProps {}

/** Exposes the CoC and Meta Action result fields without coupling demos to a page layout. */
export function createInferenceVisualization({
  chainOfCausation,
  metaAction,
}: InferenceVisualizationProps): InferenceVisualization {
  return { chainOfCausation, metaAction };
}

export interface TrajectoryPointView {
  timeSeconds: number;
  position: readonly [number, number, number];
}

export interface TrajectoryVisualization {
  pointCount: number;
  horizonSeconds: number;
  points: Array<{ timeSeconds: number; x: number; y: number }>;
}

/** Converts trajectory points into a renderer-neutral BEV polyline view model. */
export function createTrajectoryVisualization(points: readonly TrajectoryPointView[]): TrajectoryVisualization {
  return {
    pointCount: points.length,
    horizonSeconds: points.at(-1)?.timeSeconds ?? 0,
    points: points.map(({ timeSeconds, position: [x, y] }) => ({ timeSeconds, x, y })),
  };
}
