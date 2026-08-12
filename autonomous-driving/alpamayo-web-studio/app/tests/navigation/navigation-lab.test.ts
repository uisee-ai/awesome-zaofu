import assert from "node:assert/strict";
import test from "node:test";

import {
  NavigationLab,
  NavigationLabError,
} from "../../backend/studio/navigation/navigation-lab.js";
import { NavigationLabVisualization } from "../../web/src/features/navigation/navigation-lab.js";

const rotation = [
  [1, 0, 0],
  [0, 1, 0],
  [0, 0, 1],
] as const;

function trajectory(offsetY: number) {
  return Array.from({ length: 64 }, (_, index) => ({
    timeSeconds: Number(((index + 1) * 0.1).toFixed(1)),
    position: [index * 0.5, offsetY + index * 0.1, 0] as const,
    rotation,
  }));
}

test("runs two to four navigation branches serially and preserves each independent result", async () => {
  const started: string[] = [];
  const completed: string[] = [];
  const lab = new NavigationLab(async (request) => {
    started.push(request.branchId);
    assert.deepEqual(completed, started.slice(0, -1));
    completed.push(request.branchId);
    return {
      chainOfCausation: `${request.instruction} is safe.`,
      metaAction: request.template,
      trajectory: trajectory(started.length),
    };
  });

  const experiment = await lab.run("scene-version-1", [
    { id: "straight", template: "continue", seed: 7 },
    { id: "left", template: "turn-left", seed: 7 },
    { id: "right", template: "turn-right", seed: 11 },
  ]);

  assert.deepEqual(started, ["straight", "left", "right"]);
  assert.deepEqual(completed, ["straight", "left", "right"]);
  assert.equal(experiment.sceneVersionId, "scene-version-1");
  assert.deepEqual(experiment.branches.map((branch) => branch.status), ["succeeded", "succeeded", "succeeded"]);
  assert.deepEqual(experiment.branches.map((branch) => branch.output?.trajectory.length), [64, 64, 64]);
  assert.equal(experiment.branches[1].instruction, "在下一个路口左转");
});

test("rejects branch counts outside the supported two to four range", async () => {
  const lab = new NavigationLab(async () => ({
    chainOfCausation: "unused",
    metaAction: "unused",
    trajectory: trajectory(0),
  }));

  await assert.rejects(
    lab.run("scene-version-1", [{ id: "only", template: "continue", seed: 1 }]),
    (error: unknown) => error instanceof NavigationLabError && error.code === "BRANCH_COUNT",
  );
  await assert.rejects(
    lab.run("scene-version-1", Array.from({ length: 5 }, (_, index) => ({ id: `branch-${index}`, template: "continue" as const, seed: index }))),
    (error: unknown) => error instanceof NavigationLabError && error.code === "BRANCH_COUNT",
  );
});

test("maps legend colors to instructions, hides a branch, and exports comparison JSON and PNG", async () => {
  const lab = new NavigationLab(async (request) => ({
    chainOfCausation: `${request.branchId} reasoning`,
    metaAction: request.template,
    trajectory: trajectory(request.branchId === "straight" ? 0 : request.branchId === "left" ? 2 : -1),
  }));
  const experiment = await lab.run("scene-version-1", [
    { id: "straight", template: "continue", seed: 1 },
    { id: "left", template: "turn-left", seed: 1 },
    { id: "right", template: "turn-right", seed: 1 },
  ]);
  const visualization = new NavigationLabVisualization(experiment);

  assert.deepEqual(visualization.snapshot().legend.map(({ branchId, instruction, color, visible }) => ({ branchId, instruction, color, visible })), [
    { branchId: "straight", instruction: "继续直行", color: "#22d3ee", visible: true },
    { branchId: "left", instruction: "在下一个路口左转", color: "#fbbf24", visible: true },
    { branchId: "right", instruction: "在下一个路口右转", color: "#f472b6", visible: true },
  ]);
  assert.equal(visualization.snapshot().comparisons[0].endpointDistance, 2);
  assert.equal(visualization.setBranchVisibility("left", false).trajectories.length, 2);

  const json = visualization.exportJson();
  const png = visualization.exportPng();
  assert.equal(json.mimeType, "application/json");
  assert.equal(JSON.parse(json.contents ?? "{}").legend[1].visible, false);
  assert.equal(png.mimeType, "image/png");
  assert.match(png.dataUrl ?? "", /^data:image\/png;base64,iVBORw0KGgo/);
});

test("exports every visible four-branch trajectory with its matching legend color", async () => {
  const lab = new NavigationLab(async (request) => ({
    chainOfCausation: `${request.branchId} reasoning`,
    metaAction: request.template,
    trajectory: trajectory({ straight: 0, left: 3, right: 6, keepLeft: 9 }[request.branchId] ?? 0),
  }));
  const visualization = new NavigationLabVisualization(await lab.run("scene-version-4", [
    { id: "straight", template: "continue", seed: 1 },
    { id: "left", template: "turn-left", seed: 1 },
    { id: "right", template: "turn-right", seed: 1 },
    { id: "keepLeft", template: "keep-left", seed: 1 },
  ]));

  const png = visualization.exportPng();
  const pixels = Buffer.from((png.dataUrl ?? "").split(",")[1], "base64");
  const includesRgba = (color: readonly [number, number, number]) => pixels.some((_, index) =>
    pixels[index] === color[0]
    && pixels[index + 1] === color[1]
    && pixels[index + 2] === color[2]
    && pixels[index + 3] === 255,
  );

  assert.deepEqual(visualization.snapshot().legend.map((item) => item.color), ["#22d3ee", "#fbbf24", "#f472b6", "#a78bfa"]);
  assert.equal(includesRgba([34, 211, 238]), true);
  assert.equal(includesRgba([251, 191, 36]), true);
  assert.equal(includesRgba([244, 114, 182]), true);
  assert.equal(includesRgba([167, 139, 250]), true);
});
