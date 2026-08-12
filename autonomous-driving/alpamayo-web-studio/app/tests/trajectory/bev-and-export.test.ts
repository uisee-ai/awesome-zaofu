import assert from "node:assert/strict";
import test from "node:test";

import {
  BevTrajectoryVisualization,
  TrajectoryVisualizationError,
} from "../../web/src/features/trajectory/bev-trajectory-visualization.js";
import {
  createTrajectoryExport,
  TrajectoryExportError,
} from "../../backend/studio/trajectory/trajectory-export.js";

const rotation = [
  [1, 0, 0],
  [0, 1, 0],
  [0, 0, 1],
] as const;

function trajectory(offsetY = 0) {
  return Array.from({ length: 64 }, (_, index) => ({
    timeSeconds: Number(((index + 1) * 0.1).toFixed(1)),
    position: [index * 0.5, offsetY + index * 0.1, 0] as const,
    rotation,
  }));
}

test("renders all 64 future points and computes endpoint, mean and maximum lateral differences", () => {
  const visualization = new BevTrajectoryVisualization({
    baseline: { runId: "baseline", trajectory: trajectory() },
    overlays: [{ runId: "candidate", trajectory: trajectory(2) }],
  });

  const snapshot = visualization.snapshot();

  assert.equal(snapshot.baseline.points.length, 64);
  assert.equal(snapshot.overlays[0].points.length, 64);
  assert.deepEqual(snapshot.comparison, {
    endpointLateralDifference: 2,
    averageLateralDifference: 2,
    maximumLateralDifference: 2,
  });
});

test("exports a deterministic JSON document and a PNG data URL for the rendered BEV", () => {
  const visualization = new BevTrajectoryVisualization({
    baseline: { runId: "baseline", trajectory: trajectory() },
    overlays: [{ runId: "candidate", trajectory: trajectory(1) }],
  });

  const json = visualization.exportJson();
  const png = visualization.exportPng();

  assert.equal(json.fileName, "bev-trajectory-baseline.json");
  assert.equal(json.mimeType, "application/json");
  assert.ok(json.contents);
  assert.equal(JSON.parse(json.contents).baseline.points.length, 64);
  assert.equal(png.fileName, "bev-trajectory-baseline.png");
  assert.equal(png.mimeType, "image/png");
  assert.ok(png.dataUrl);
  assert.match(png.dataUrl, /^data:image\/png;base64,iVBORw0KGgo/);
});

test("backend export boundary rejects incomplete trajectories and preserves all visualization fields", () => {
  const visualization = new BevTrajectoryVisualization({
    baseline: { runId: "baseline", trajectory: trajectory() },
    overlays: [{ runId: "candidate", trajectory: trajectory(-1) }],
  });

  const exported = createTrajectoryExport(visualization.snapshot());

  assert.equal(exported.schemaVersion, "bev-trajectory-export.v1");
  assert.equal(exported.baseline.points.length, 64);
  assert.equal(exported.overlays[0].points.length, 64);
  assert.deepEqual(exported.comparison, {
    endpointLateralDifference: 1,
    averageLateralDifference: 1,
    maximumLateralDifference: 1,
  });

  assert.throws(
    () => new BevTrajectoryVisualization({ baseline: { runId: "invalid", trajectory: trajectory().slice(0, 63) } }),
    (error: unknown) => error instanceof TrajectoryVisualizationError && error.code === "TRAJECTORY_POINT_COUNT",
  );
  assert.throws(
    () => createTrajectoryExport({
      ...visualization.snapshot(),
      baseline: { ...visualization.snapshot().baseline, points: visualization.snapshot().baseline.points.slice(0, 63) },
    }),
    (error: unknown) => error instanceof TrajectoryExportError && error.code === "BASELINE_POINT_COUNT",
  );
});
