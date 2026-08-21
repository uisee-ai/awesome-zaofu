import { describe, expect, it } from "vitest";

import {
  createOpenLaneAssembly,
  createRuntimeEvidenceReceipt,
  createSyntheticNuScenesAdapter,
} from "../../src/shell/synthetic-adapters";

describe("synthetic production adapters", () => {
  it("adapts the nuScenes fixture through the feature APIs without changing its data root", async () => {
    const adapter = createSyntheticNuScenesAdapter();

    await adapter.selectFrame("sample-0001");
    const selected = await adapter.selectFrame("sample-0002");

    expect(selected.context?.frameContextId).toBe("scene-0061:sample-0002:g2");
    expect(selected.context?.sensorFrames.find((sensor) => sensor.sensorId === "CAM_FRONT")?.deltaMs).toBe(10);
    expect(adapter.selectInstance("instance-vehicle-01").stableInstanceRef).toBe("instance-vehicle-01");
    expect(adapter.search("depot", "rain")).toEqual([
      expect.objectContaining({
        stableId: "scene-0061:sample-0001",
        ruleVersion: "scene-derivation.v1",
      }),
    ]);
    expect(adapter.evidence.dataRootBefore).toBe(adapter.evidence.dataRootAfter);
  });

  it("adapts the OpenLane fixture into linked read-only views and canonical receipts", () => {
    const openLane = createOpenLaneAssembly();
    const receipt = createRuntimeEvidenceReceipt(
      "SWB-ASSEMBLY-005-R3-CMD-04",
      "openlane",
      openLane.fixtureDigest,
      {
        sourceCommit: "1234567890abcdef1234567890abcdef12345678",
        productionBuildDigest: "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
        runnerVersion: "1.62.1",
        browserVersion: "140.0.0.0",
        startedAt: "2026-08-04T12:00:00.000Z",
        finishedAt: "2026-08-04T12:00:01.000Z",
        observedResourceUrls: ["http://127.0.0.1:4273/assets/index.js"],
      },
    );

    expect(openLane.frame.lanes[1]).toMatchObject({
      lane2dRef: "openlane:validation/synthetic-segment/frame-0001.jpg#lane:102:2d",
      lane3dRef: "openlane:validation/synthetic-segment/frame-0001.jpg#lane:102:3d",
    });
    expect(openLane.audit).toMatchObject({
      unchanged: true,
      mediaIncluded: false,
      absolutePathsIncluded: false,
    });
    expect(receipt).toMatchObject({
      commandId: "SWB-ASSEMBLY-005-R3-CMD-04",
      sourceCommit: "1234567890abcdef1234567890abcdef12345678",
      productionBuildDigest: "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
      browser: { name: "chromium", version: "140.0.0.0" },
      fixture: { kind: "openlane", digest: openLane.fixtureDigest },
      network: { loopbackOnly: true, nonLoopbackRequests: [] },
      result: "passed",
    });
  });
});
