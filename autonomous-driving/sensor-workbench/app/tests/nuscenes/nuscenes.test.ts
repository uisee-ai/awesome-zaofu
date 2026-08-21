import { describe, expect, test } from "vitest";

import { createInstanceSelection } from "../../src/features/nuscenes/instance-selection";
import { NuScenesSearchIndex } from "../../src/features/nuscenes/search";

describe("nuScenes stable instance linkage", () => {
  test("uses the same stable instance in Camera, LiDAR, BEV and the scene annotation chain", () => {
    const selection = createInstanceSelection(
      "scene-0061",
      "instance-vehicle-01",
      [
        {
          annotationRef: "annotation-0001",
          sceneRef: "scene-0061",
          frameRef: "sample-0001",
          instanceRef: "instance-vehicle-01",
          cameraRef: "camera-box-0001",
          lidarRef: "lidar-box-0001",
          bevRef: "bev-box-0001",
          previousAnnotationRef: null,
          nextAnnotationRef: "annotation-0002",
        },
        {
          annotationRef: "annotation-0002",
          sceneRef: "scene-0061",
          frameRef: "sample-0002",
          instanceRef: "instance-vehicle-01",
          cameraRef: "camera-box-0002",
          lidarRef: "lidar-box-0002",
          bevRef: "bev-box-0002",
          previousAnnotationRef: "annotation-0001",
          nextAnnotationRef: null,
        },
      ],
    );

    expect(selection).toEqual({
      stableInstanceRef: "instance-vehicle-01",
      sceneRef: "scene-0061",
      camera: { stableInstanceRef: "instance-vehicle-01", refs: ["camera-box-0001", "camera-box-0002"] },
      lidar: { stableInstanceRef: "instance-vehicle-01", refs: ["lidar-box-0001", "lidar-box-0002"] },
      bev: { stableInstanceRef: "instance-vehicle-01", refs: ["bev-box-0001", "bev-box-0002"] },
      annotationChain: [
        {
          annotationRef: "annotation-0001",
          frameRef: "sample-0001",
          previousAnnotationRef: null,
          nextAnnotationRef: "annotation-0002",
        },
        {
          annotationRef: "annotation-0002",
          frameRef: "sample-0002",
          previousAnnotationRef: "annotation-0001",
          nextAnnotationRef: null,
        },
      ],
    });
  });
});

describe("nuScenes search provenance", () => {
  test("returns index-consistent source text and derived weather/daylight metadata", () => {
    const index = new NuScenesSearchIndex("scene-derivation.v1", [
      {
        stableId: "scene-0061:sample-0001",
        sceneRef: "scene-0061",
        frameRef: "sample-0001",
        sourceText: "Night rain near depot",
      },
      {
        stableId: "scene-0102:sample-0099",
        sceneRef: "scene-0102",
        frameRef: "sample-0099",
        sourceText: "Sunny daytime city street",
      },
    ]);

    expect(index.search({ text: "depot", derivedFilters: { weather: "rain", daylight: "night" } })).toEqual([
      {
        stableId: "scene-0061:sample-0001",
        sceneRef: "scene-0061",
        frameRef: "sample-0001",
        sourceText: "Night rain near depot",
        derived: true,
        derivationSource: "scene.description",
        ruleVersion: "scene-derivation.v1",
        derivedFilters: { weather: "rain", daylight: "night" },
      },
    ]);
    expect(index.snapshot()).toEqual([
      {
        stableId: "scene-0061:sample-0001",
        sourceText: "Night rain near depot",
        derivedFilters: { weather: "rain", daylight: "night" },
        derivationSource: "scene.description",
        ruleVersion: "scene-derivation.v1",
      },
      {
        stableId: "scene-0102:sample-0099",
        sourceText: "Sunny daytime city street",
        derivedFilters: { weather: "clear", daylight: "day" },
        derivationSource: "scene.description",
        ruleVersion: "scene-derivation.v1",
      },
    ]);
  });
});
