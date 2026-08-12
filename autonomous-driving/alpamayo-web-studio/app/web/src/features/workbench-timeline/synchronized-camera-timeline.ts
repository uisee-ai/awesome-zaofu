import type { CameraInput, FrameInput } from "../../../../packages/contracts/src/scene.js";

export type TimelineErrorCode =
  | "NO_CAMERAS"
  | "FRAME_COUNT_MISMATCH"
  | "TIME_INDEX_OUT_OF_RANGE";

export class TimelineError extends Error {
  constructor(
    readonly code: TimelineErrorCode,
    message: string,
  ) {
    super(message);
    this.name = "TimelineError";
  }
}

export interface CameraFrameView {
  cameraId: number;
  frame: FrameInput;
}

export interface SynchronizedTimelineSnapshot {
  timeIndex: number;
  frameCount: number;
  cameras: CameraFrameView[];
}

/**
 * A view-model for the Workbench camera grid. It keeps Camera ID ordering and
 * the selected frame index in one place so every camera advances together.
 */
export class SynchronizedCameraTimeline {
  private readonly cameras: readonly CameraInput[];
  private readonly frameCount: number;
  private timeIndex = 0;

  constructor(cameras: readonly CameraInput[]) {
    if (cameras.length === 0) {
      throw new TimelineError("NO_CAMERAS", "时间轴至少需要一路 Camera。");
    }

    this.cameras = [...cameras].sort((left, right) => left.cameraId - right.cameraId);
    this.frameCount = this.cameras[0].frames.length;
    if (this.cameras.some((camera) => camera.frames.length !== this.frameCount)) {
      throw new TimelineError("FRAME_COUNT_MISMATCH", "所有 Camera 必须使用相同数量的同步帧。");
    }
  }

  selectTimeIndex(timeIndex: number): SynchronizedTimelineSnapshot {
    if (!Number.isInteger(timeIndex) || timeIndex < 0 || timeIndex >= this.frameCount) {
      throw new TimelineError(
        "TIME_INDEX_OUT_OF_RANGE",
        `时间点必须是 0 到 ${this.frameCount - 1} 之间的整数。`,
      );
    }

    this.timeIndex = timeIndex;
    return this.snapshot();
  }

  snapshot(): SynchronizedTimelineSnapshot {
    return {
      timeIndex: this.timeIndex,
      frameCount: this.frameCount,
      cameras: this.cameras.map((camera) => ({
        cameraId: camera.cameraId,
        frame: camera.frames[this.timeIndex],
      })),
    };
  }
}
