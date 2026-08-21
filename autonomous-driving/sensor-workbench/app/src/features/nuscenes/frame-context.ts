import { FRAME_CONTEXT_VERSION, type FrameContextV1, type SensorFrameV1 } from "../../contracts";

export interface NuScenesSensorSample {
  readonly sensorId: string;
  readonly modality: "camera" | "lidar";
  readonly timestampUs: number;
  readonly assetRef: string | null;
}

export interface NuScenesKeyframe {
  readonly sceneRef: string;
  readonly frameRef: string;
  readonly timestampUs: number;
  readonly sensors: readonly NuScenesSensorSample[];
}

export interface FrameSelectionResult {
  readonly committed: boolean;
  readonly context: FrameContextV1 | null;
}

export type KeyframeLoader = (frameRef: string, signal: AbortSignal) => Promise<NuScenesKeyframe>;

function createFrameContext(frame: NuScenesKeyframe, generation: number): FrameContextV1 {
  if (frame.sensors.length === 0) throw new TypeError("a keyframe requires at least one sensor sample");
  const sensorFrames: SensorFrameV1[] = frame.sensors.map((sensor) => ({
    sensorId: sensor.sensorId,
    modality: sensor.modality,
    timestampUs: sensor.timestampUs,
    deltaMs: (sensor.timestampUs - frame.timestampUs) / 1_000,
    availability: sensor.assetRef === null ? "missing" : "available",
    assetRef: sensor.assetRef,
  }));
  const primarySensorId = sensorFrames.find((sensor) => sensor.sensorId === "LIDAR_TOP")?.sensorId ?? sensorFrames[0]!.sensorId;
  return {
    schemaVersion: FRAME_CONTEXT_VERSION,
    frameContextId: `${frame.sceneRef}:${frame.frameRef}:g${generation}`,
    generation,
    adapterId: "nuscenes-v1",
    datasetKind: "nuscenes",
    datasetVersion: "v1.0-mini",
    sceneRef: frame.sceneRef,
    frameRef: frame.frameRef,
    keyframe: true,
    timestampUs: frame.timestampUs,
    primarySensorId,
    coordinateFrame: "ego",
    sensorFrames,
  };
}

export class FrameContextCoordinator {
  #generation = 0;
  #abortController: AbortController | null = null;
  #current: FrameContextV1 | null = null;

  constructor(
    private readonly load: KeyframeLoader,
    private readonly commit: (context: FrameContextV1) => void = () => undefined,
  ) {}

  get current(): FrameContextV1 | null {
    return this.#current;
  }

  async select(frameRef: string): Promise<FrameSelectionResult> {
    const generation = ++this.#generation;
    this.#abortController?.abort();
    const controller = new AbortController();
    this.#abortController = controller;
    const frame = await this.load(frameRef, controller.signal);
    if (generation !== this.#generation) return { committed: false, context: null };
    const context = createFrameContext(frame, generation);
    this.#current = context;
    this.commit(context);
    return { committed: true, context };
  }
}
