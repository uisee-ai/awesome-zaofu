import { describe, expect, test } from "vitest";

import { FrameContextCoordinator, type NuScenesKeyframe } from "../../src/features/nuscenes/frame-context";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

const frameOne: NuScenesKeyframe = {
  sceneRef: "scene-0061",
  frameRef: "sample-0001",
  timestampUs: 1_535_099_000_000_000,
  sensors: [
    { sensorId: "CAM_FRONT", modality: "camera", timestampUs: 1_535_099_000_012_000, assetRef: "asset:front-1" },
    { sensorId: "LIDAR_TOP", modality: "lidar", timestampUs: 1_535_099_000_000_000, assetRef: "asset:lidar-1" },
  ],
};

const frameTwo: NuScenesKeyframe = {
  sceneRef: "scene-0061",
  frameRef: "sample-0002",
  timestampUs: 1_535_099_000_500_000,
  sensors: [
    { sensorId: "CAM_FRONT", modality: "camera", timestampUs: 1_535_099_000_510_000, assetRef: "asset:front-2" },
    { sensorId: "LIDAR_TOP", modality: "lidar", timestampUs: 1_535_099_000_500_000, assetRef: "asset:lidar-2" },
  ],
};

describe("FrameContext generation gate", () => {
  test("discards an older generation before any view commit", async () => {
    const slow = deferred<NuScenesKeyframe>();
    const fast = deferred<NuScenesKeyframe>();
    const commits: string[] = [];
    const coordinator = new FrameContextCoordinator(
      (frameRef) => (frameRef === "sample-0001" ? slow.promise : fast.promise),
      (context) => commits.push(context.frameContextId),
    );

    const first = coordinator.select("sample-0001");
    const second = coordinator.select("sample-0002");
    fast.resolve(frameTwo);
    const secondResult = await second;
    slow.resolve(frameOne);
    const firstResult = await first;

    expect(secondResult).toEqual({
      committed: true,
      context: {
        schemaVersion: "frame-context.v1",
        frameContextId: "scene-0061:sample-0002:g2",
        generation: 2,
        adapterId: "nuscenes-v1",
        datasetKind: "nuscenes",
        datasetVersion: "v1.0-mini",
        sceneRef: "scene-0061",
        frameRef: "sample-0002",
        keyframe: true,
        timestampUs: 1_535_099_000_500_000,
        primarySensorId: "LIDAR_TOP",
        coordinateFrame: "ego",
        sensorFrames: [
          {
            sensorId: "CAM_FRONT",
            modality: "camera",
            timestampUs: 1_535_099_000_510_000,
            deltaMs: 10,
            availability: "available",
            assetRef: "asset:front-2",
          },
          {
            sensorId: "LIDAR_TOP",
            modality: "lidar",
            timestampUs: 1_535_099_000_500_000,
            deltaMs: 0,
            availability: "available",
            assetRef: "asset:lidar-2",
          },
        ],
      },
    });
    expect(firstResult).toEqual({ committed: false, context: null });
    expect(commits).toEqual(["scene-0061:sample-0002:g2"]);
    expect(coordinator.current?.frameContextId).toBe("scene-0061:sample-0002:g2");
  });
});
