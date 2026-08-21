import { StrictMode, useState } from "react";
import { createRoot } from "react-dom/client";

import { toEvidenceReceiptWire } from "./contracts";
import { NuScenesWorkbench, RealNuScenesWorkbench } from "./features/nuscenes";
import type { FrameContextV1 } from "./contracts";
import type { InstanceSelectionV1 } from "./features/nuscenes";
import { OpenLaneFeature } from "./features/openlane/OpenLaneFeature";
import { RealOpenLaneWorkbench } from "./features/openlane/RealOpenLaneWorkbench";
import { LocalStorageReviewPersistence, ReviewPanel, ReviewStore } from "./features/review";
import {
  createOpenLaneAssembly,
  createRuntimeEvidenceReceipt,
  createSyntheticNuScenesAdapter,
} from "./shell/synthetic-adapters";
import { WorkbenchShell } from "./shell/WorkbenchShell";

const nuScenes = createSyntheticNuScenesAdapter();
const openLane = createOpenLaneAssembly();
const reviewStore = new ReviewStore({
  workspaceId: "synthetic-review-workspace",
  datasetDigest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  persistence: new LocalStorageReviewPersistence(globalThis.localStorage, "synthetic-review-workspace"),
});

function evidenceMeta(name: string, developmentFallback: string): string {
  return document.querySelector<HTMLMetaElement>(`meta[name="${name}"]`)?.content || developmentFallback;
}

function browserVersion(): string {
  return navigator.userAgent.match(/(?:Headless)?Chrome\/([0-9.]+)/)?.[1] ?? "unknown-browser";
}

const pageStartedAt = new Date(performance.timeOrigin).toISOString();

function runtimeEvidenceContext() {
  return {
    sourceCommit: evidenceMeta("swb-source-commit", "0".repeat(40)),
    productionBuildDigest: evidenceMeta("swb-production-build-digest", `sha256:${"0".repeat(64)}`),
    runnerVersion: evidenceMeta("swb-runner-version", "development-server"),
    browserVersion: browserVersion(),
    startedAt: pageStartedAt,
    finishedAt: new Date().toISOString(),
    observedResourceUrls: performance.getEntriesByType("resource").map((entry) => entry.name),
  };
}

function App() {
  const [frameContext, setFrameContext] = useState<FrameContextV1 | null>(null);
  const [instanceSelection, setInstanceSelection] = useState<InstanceSelectionV1 | null>(null);
  const [localNuScenesAvailable, setLocalNuScenesAvailable] = useState(false);
  const [localOpenLaneAvailable, setLocalOpenLaneAvailable] = useState(false);
  const params = new URLSearchParams(globalThis.location.search);
  const reviewFault = params.get("fault") === "review-after-prepare" ? "after_prepare" : undefined;
  const openLaneReceipt = createRuntimeEvidenceReceipt(
    "SWB-ASSEMBLY-005-R3-CMD-04",
    "openlane",
    openLane.fixtureDigest,
    runtimeEvidenceContext(),
  );
  const reviewReceipt = createRuntimeEvidenceReceipt(
    "SWB-REVIEW-004-R3-CMD-04",
    "synthetic",
    "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    runtimeEvidenceContext(),
  );
  const reviewFrameContextId = frameContext?.frameContextId ?? "synthetic:unselected";
  const reviewTarget = instanceSelection
    ? { kind: "annotation" as const, stableId: instanceSelection.stableInstanceRef }
    : { kind: "frame" as const, stableId: frameContext?.frameRef ?? "synthetic:unselected" };

  return (
    <main data-testid="sensor-workbench-production-entry">
      <WorkbenchShell
        frameContext={frameContext}
        selection={instanceSelection}
        localDataAvailable={localNuScenesAvailable || localOpenLaneAvailable}
        localDataSource={localNuScenesAvailable && localOpenLaneAvailable
          ? "nuScenes + OpenLane"
          : localNuScenesAvailable ? "nuScenes" : "OpenLane"}
        rightContent={
          <ReviewPanel
            store={reviewStore}
            reviewId="synthetic-review-0001"
            frameContextId={reviewFrameContextId}
            target={reviewTarget}
            actorId="synthetic-reviewer"
            faultAtNextAppend={reviewFault}
            evidenceReceipt={reviewReceipt}
          />
        }
      >
        <>
          <RealNuScenesWorkbench onAvailabilityChange={setLocalNuScenesAvailable} onFrameContextChange={setFrameContext} />
          {!localNuScenesAvailable && <NuScenesWorkbench
            frameRefs={nuScenes.frameRefs}
            instanceRefs={nuScenes.instanceRefs}
            visualsByFrame={nuScenes.visualsByFrame}
            selectFrame={nuScenes.selectFrame}
            selectInstance={nuScenes.selectInstance}
            search={nuScenes.search}
            evidence={nuScenes.featureEvidence}
            onFrameContextChange={setFrameContext}
            onInstanceSelectionChange={setInstanceSelection}
          />}
          <RealOpenLaneWorkbench onAvailabilityChange={setLocalOpenLaneAvailable} />
          {!localOpenLaneAvailable && <OpenLaneFeature frame={openLane.frame} audit={openLane.audit} fixtureDigest={openLane.fixtureDigest} />}
        </>
      </WorkbenchShell>
      <script type="application/json" data-testid="openlane-evidence-receipt">
        {JSON.stringify(toEvidenceReceiptWire(openLaneReceipt))}
      </script>
    </main>
  );
}

const root = document.getElementById("root");

if (!root) {
  throw new Error("Sensor Workbench root element is missing");
}

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
