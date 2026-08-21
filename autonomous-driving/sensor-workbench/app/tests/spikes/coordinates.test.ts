import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import {
  measureCoordinateFixture,
  openLaneWaymoToStandardCamera,
  projectCameraPoint,
  transformNuScenesLidarToCamera,
} from "../../src/spikes/coordinates.mjs";
import { summarizeSamples, validatePerformanceFixture } from "../../src/spikes/performance.mjs";

const fixtureUrl = new URL("../fixtures/golden/coordinate-fixture.v1.json", import.meta.url);
const digestUrl = new URL("../fixtures/golden/coordinate-fixture.v1.sha256", import.meta.url);
const fixtureBytes = readFileSync(fixtureUrl);
const fixture = JSON.parse(fixtureBytes.toString("utf8"));
const expectedDigest = "a5c402cce5e679e1bcc90f895032fb993d9a97702c5533dc78b76a393d37aa93";

describe("digest-bound coordinate golden fixture", () => {
  it("pins the complete fixture bytes, sources, methods, candidates, fallbacks, and ignored lists", () => {
    expect(createHash("sha256").update(fixtureBytes).digest("hex")).toBe(expectedDigest);
    expect(readFileSync(digestUrl, "utf8")).toBe(`${expectedDigest}  coordinate-fixture.v1.json\n`);
    expect(Object.keys(fixture)).toEqual([
      "schema_version",
      "fixture_id",
      "dataset_versions",
      "source_refs",
      "method",
      "candidate_thresholds",
      "nuscenes",
      "openlane",
    ]);
    expect(fixture.dataset_versions).toEqual({ nuscenes: "v1.0-mini", openlane: "v1.2" });
    expect(fixture.source_refs).toEqual([
      "https://github.com/nutonomy/nuscenes-devkit/blob/d9de17a73bdc06ce97a02f77ae7edb9b0406e851/python-sdk/nuscenes/utils/geometry_utils.py",
      "https://github.com/nutonomy/nuscenes-devkit/blob/d9de17a73bdc06ce97a02f77ae7edb9b0406e851/python-sdk/nuscenes/nuscenes.py",
      "https://github.com/OpenDriveLab/OpenLane/blob/ec98fda7cb21ecf51ffdf70c37c411076985dbd6/data/Coordinate_Sys.md",
    ]);
    expect(fixture.method).toEqual({
      matrix_layout: "row_major",
      point_convention: "homogeneous_column_xyz1",
      projection: "u=fx*x/z+cx; v=fy*y/z+cy; depth=z",
      translation_residual: "euclidean_distance_m",
      projection_residual: "euclidean_distance_px",
      behind_camera_fallback: "not_projected",
      unknown_fixture_fields: "ignored",
    });
    expect(fixture.candidate_thresholds).toEqual({
      translation_m: 0.00001,
      projection_px: 0.5,
      policy: "informational_only_unverified",
    });
    expect(fixture.nuscenes.ignored_modalities).toEqual([
      "radar",
      "lidarseg",
      "panoptic",
      "can_bus",
      "non_keyframe_sweeps",
    ]);
    expect(fixture.openlane.ignored_annotation_fields).toEqual(["future_optional_attributes"]);
  });
});

describe("nuScenes transform and projection", () => {
  it("applies the complete lidar→ego→global→camera-ego→camera chain", () => {
    const actual = transformNuScenesLidarToCamera(
      fixture.nuscenes.point_lidar_m,
      fixture.nuscenes.transforms,
    );

    expect(actual).toEqual(fixture.nuscenes.expected.point_camera_m);
    expect(projectCameraPoint(actual, fixture.nuscenes.camera_intrinsic)).toEqual({
      pixel: fixture.nuscenes.expected.pixel,
      depth: fixture.nuscenes.expected.depth_m,
    });
  });

  it("uses the documented behind-camera fallback instead of dividing by non-positive depth", () => {
    expect(projectCameraPoint([2, 1, 0], fixture.nuscenes.camera_intrinsic)).toBeNull();
    expect(projectCameraPoint([2, 1, -1], fixture.nuscenes.camera_intrinsic)).toBeNull();
  });
});

describe("OpenLane V1.2 transform and projection", () => {
  it("maps x-front/y-left/z-up into x-right/y-down/z-front with the full matrix", () => {
    const actual = openLaneWaymoToStandardCamera(
      fixture.openlane.point_waymo_camera_m,
      fixture.openlane.waymo_to_standard_camera,
    );

    expect(actual).toEqual(fixture.openlane.expected.point_standard_camera_m);
    expect(projectCameraPoint(actual, fixture.openlane.camera_intrinsic)).toEqual({
      pixel: fixture.openlane.expected.pixel,
      depth: fixture.openlane.expected.depth_m,
    });
  });
});

describe("coordinate spike report", () => {
  it("preserves raw expected/actual values and treats candidate thresholds as informational only", () => {
    expect(measureCoordinateFixture(fixture, expectedDigest)).toEqual({
      schema_version: "coordinate-spike-report.v1",
      fixture_id: "sensor-workbench-coordinate-golden-001",
      fixture_sha256: expectedDigest,
      deterministic: true,
      method: fixture.method,
      candidate_thresholds: fixture.candidate_thresholds,
      measurements: {
        nuscenes: {
          input_lidar_m: [4, 1, 1],
          expected_camera_m: [-2, -1, 5],
          actual_camera_m: [-2, -1, 5],
          translation_residual_m: 0,
          expected_pixel: [320, 196],
          actual_pixel: [320, 196],
          projection_residual_px: 0,
          depth_m: 5,
        },
        openlane: {
          input_waymo_camera_m: [20, -2, 1],
          expected_standard_camera_m: [2, -1, 20],
          actual_standard_camera_m: [2, -1, 20],
          translation_residual_m: 0,
          expected_pixel: [1060, 491],
          actual_pixel: [1060, 491],
          projection_residual_px: 0,
          depth_m: 20,
        },
      },
      candidate_evaluation: {
        policy: "record_only_not_a_pass_gate",
        translation_candidate_m: 0.00001,
        projection_candidate_px: 0.5,
      },
      source_refs: fixture.source_refs,
    });
  });
});

describe("real Chrome performance fixture and statistics", () => {
  const performanceFixtureUrl = new URL("../fixtures/golden/performance-fixture.v1.json", import.meta.url);
  const performanceDigestUrl = new URL("../fixtures/golden/performance-fixture.v1.sha256", import.meta.url);
  const performanceBytes = readFileSync(performanceFixtureUrl);
  const performanceFixture = JSON.parse(performanceBytes.toString("utf8"));
  const performanceDigest = "0c69e97a353f228442db1ec42d7381208be134a8a0b37f66f276aec9b775add7";

  it("pins the complete headed Chrome method, repetitions, metrics, candidates, network policy, and output fields", () => {
    expect(createHash("sha256").update(performanceBytes).digest("hex")).toBe(performanceDigest);
    expect(readFileSync(performanceDigestUrl, "utf8")).toBe(
      `${performanceDigest}  performance-fixture.v1.json\n`,
    );
    expect(performanceFixture.workload).toEqual({
      point_count: 120000,
      seed: 20260804,
      repeat_count: 3,
      warm_repetitions_per_session: 3,
      viewport: { width: 1280, height: 720 },
    });
    expect(performanceFixture.browser).toEqual({
      engine: "chromium",
      channel: "chrome",
      distribution: "Google Chrome",
      headless: false,
      tool: "@playwright/test",
      tool_version: "1.62.1",
    });
    expect(performanceFixture.states).toEqual({
      cold: "new branded Chrome process, browser context, page, and empty workload state",
      warm: "same page after the cold workload with point buffer and JIT state retained",
    });
    expect(performanceFixture.metrics).toEqual([
      {
        name: "dataset_open_ms",
        method: "generate deterministic point buffer and compute its digest accumulator",
      },
      {
        name: "first_render_ms",
        method: "project deterministic points and render a bounded sample to a 2D canvas",
      },
      {
        name: "frame_switch_ms",
        method: "apply a fixed rigid transform and projection to the full point buffer",
      },
      {
        name: "interaction_ms",
        method: "scan the full projected buffer for the nearest point to a fixed cursor",
      },
    ]);
    expect(performanceFixture.candidate_thresholds).toEqual({
      dataset_open_ms: 60000,
      first_render_ms: 3000,
      frame_switch_ms: 500,
      interaction_ms: 200,
      policy: "informational_only_unverified",
    });
    expect(performanceFixture.network_policy).toEqual({
      allowed_origins: [],
      page_source: "setContent about:blank",
      external_requests: "fail",
    });
    expect(performanceFixture.output).toEqual({
      raw_samples: true,
      statistics: ["minimum", "maximum", "mean", "median", "p95"],
      environment_fields: [
        "cpu",
        "memory_bytes",
        "os",
        "chrome",
        "storage",
        "fixture_sha256",
        "cold_warm_state",
        "repeat_count",
        "tool",
      ],
    });
    expect(validatePerformanceFixture(performanceFixture)).toBe(true);
  });

  it("rejects a headless or threshold-gated rewrite of the fixed method", () => {
    const headless = structuredClone(performanceFixture);
    headless.browser.headless = true;
    expect(() => validatePerformanceFixture(headless)).toThrow(/headless/);

    const gated = structuredClone(performanceFixture);
    gated.candidate_thresholds.policy = "hard_gate";
    expect(() => validatePerformanceFixture(gated)).toThrow(/informational/);
  });

  it("calculates literal raw-sample statistics with nearest-rank p95", () => {
    expect(summarizeSamples([100, 400, 200, 300])).toEqual({
      minimum: 100,
      maximum: 400,
      mean: 250,
      median: 250,
      p95: 400,
    });
  });
});
