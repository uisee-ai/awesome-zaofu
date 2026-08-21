import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { OpenLaneFeature } from "../../src/features/openlane/OpenLaneFeature";
import {
  OPENLANE_ADAPTER_DESCRIPTOR,
  createOpenLaneViewModel,
  parseOpenLaneAnnotation,
} from "../../src/features/openlane/model";
import {
  createOpenLaneReadonlyAudit,
  scanOpenLaneDataRoot,
  summarizeOpenLaneDataRoot,
} from "../../src/features/openlane/readonly";

const fixtureDirectory = new URL("../fixtures/synthetic/openlane/", import.meta.url);
const fixtureRoot = new URL("root/", fixtureDirectory);
const manifestBytes = readFileSync(new URL("manifest.json", fixtureDirectory));
const annotationBytes = readFileSync(
  new URL("root/lane3d_1000/validation/synthetic-segment/frame-0001.json", fixtureDirectory),
);
const manifest = JSON.parse(manifestBytes.toString("utf8"));
const annotation = JSON.parse(annotationBytes.toString("utf8"));
const expectedRootDigest = "f63d05a3772587bc3cbc80091d62ed538bb5f885025eebc127677c512dc302f6";

describe("digest-bound OpenLane V1.2 synthetic fixture", () => {
  it("pins the full manifest, license boundary, source refs, and source-shaped annotation", () => {
    expect(Object.keys(manifest)).toEqual([
      "schema_version",
      "fixture_id",
      "dataset_version",
      "annotation_ref",
      "source_refs",
      "license",
    ]);
    expect(manifest.dataset_version).toBe("v1.2");
    expect(manifest.source_refs).toEqual([
      "https://github.com/OpenDriveLab/OpenLane/blob/ec98fda7cb21ecf51ffdf70c37c411076985dbd6/README.md",
      "https://github.com/OpenDriveLab/OpenLane/blob/ec98fda7cb21ecf51ffdf70c37c411076985dbd6/anno_criterion/Lane/README.md",
      "https://github.com/OpenDriveLab/OpenLane/blob/ec98fda7cb21ecf51ffdf70c37c411076985dbd6/data/Coordinate_Sys.md",
    ]);
    expect(manifest.license).toEqual({
      data_terms: "CC BY-NC-SA and Waymo Dataset License Agreement for Non-Commercial Use (August 2019)",
      commercial_use: "prohibited",
      code_license: "Apache-2.0",
      acquisition: "Register with Waymo Open Dataset, accept its terms, then use the OpenLane download request form.",
    });
    expect(Object.keys(annotation)).toEqual([
      "intrinsic",
      "extrinsic",
      "pose",
      "lane_lines",
      "file_path",
      "future_v2_field",
    ]);
    expect(annotation.lane_lines).toEqual([
      {
        category: 2,
        visibility: [1, 1, 0],
        uv: [[720, 760, 810], [700, 620, 560]],
        xyz: [[5, 10, 15], [2.5, 2.25, 2], [0, 0.1, 0.2]],
        attribute: 2,
        track_id: 101,
      },
      {
        category: 8,
        visibility: [1, 0.5, 0],
        uv: [[1120, 1090, 1050], [700, 620, 560]],
        xyz: [[5, 10, 15], [-2.5, -2.25, -2], [0, 0.1, 0.2]],
        attribute: 3,
        track_id: 102,
      },
    ]);
    expect(createHash("sha256").update(annotationBytes).digest("hex")).toBe(
      "2062fabc301f1c1268d9b9cfeb7542fe04f14150166728913d2ba1b0c578eb43",
    );
    expect(readFileSync(new URL("openlane-v1.2.root.sha256", fixtureDirectory), "utf8")).toBe(
      `${expectedRootDigest}  root\n`,
    );
  });
});

describe("OpenLane V1.2 model", () => {
  it("parses complete ordered 2D/3D points, visibility, categories, attributes, and stable references", () => {
    const frame = parseOpenLaneAnnotation(annotation, {
      datasetVersion: manifest.dataset_version,
      frameRef: manifest.annotation_ref,
    });

    expect(frame).toEqual({
      datasetVersion: "v1.2",
      frameRef: "lane3d_1000/validation/synthetic-segment/frame-0001.json",
      imageRef: "validation/synthetic-segment/frame-0001.jpg",
      intrinsic: annotation.intrinsic,
      extrinsic: annotation.extrinsic,
      pose: annotation.pose,
      lanes: [
        {
          laneRef: "openlane:validation/synthetic-segment/frame-0001.jpg#lane:101",
          lane2dRef: "openlane:validation/synthetic-segment/frame-0001.jpg#lane:101:2d",
          lane3dRef: "openlane:validation/synthetic-segment/frame-0001.jpg#lane:101:3d",
          trackId: 101,
          category: { id: 2, name: "white-solid" },
          attribute: { id: 2, name: "left" },
          visibility: [1, 1, 0],
          points2d: [[720, 700], [760, 620], [810, 560]],
          points3d: [[5, 2.5, 0], [10, 2.25, 0.1], [15, 2, 0.2]],
        },
        {
          laneRef: "openlane:validation/synthetic-segment/frame-0001.jpg#lane:102",
          lane2dRef: "openlane:validation/synthetic-segment/frame-0001.jpg#lane:102:2d",
          lane3dRef: "openlane:validation/synthetic-segment/frame-0001.jpg#lane:102:3d",
          trackId: 102,
          category: { id: 8, name: "yellow-solid" },
          attribute: { id: 3, name: "right" },
          visibility: [1, 0.5, 0],
          points2d: [[1120, 700], [1090, 620], [1050, 560]],
          points3d: [[5, -2.5, 0], [10, -2.25, 0.1], [15, -2, 0.2]],
        },
      ],
    });
    expect(OPENLANE_ADAPTER_DESCRIPTOR).toEqual({
      schemaVersion: "adapter.v1",
      adapterId: "openlane-v1.2",
      datasetKind: "openlane",
      datasetVersion: "v1.2",
      displayName: "OpenLane V1.2",
      capabilities: ["scan", "browse", "coordinate_projection", "review"],
      unsupportedCapabilities: ["model_comparison", "official_evaluation", "raw_data_mutation"],
      fallbackBehavior: "report_unsupported",
      ignoredSourceFields: ["future_v2_field", "cipo", "scene_tags"],
      readOnly: true,
    });
  });

  it("rejects point/visibility length drift and absolute media paths", () => {
    const mismatched = structuredClone(annotation);
    mismatched.lane_lines[0].visibility = [1, 1];
    expect(() => parseOpenLaneAnnotation(mismatched, {
      datasetVersion: "v1.2",
      frameRef: manifest.annotation_ref,
    })).toThrow(/same point count/);

    expect(() => parseOpenLaneAnnotation({ ...annotation, file_path: "/private/raw/frame.jpg" }, {
      datasetVersion: "v1.2",
      frameRef: manifest.annotation_ref,
    })).toThrow(/relative/);
  });

  it("accepts official v1.2 frames where 2D sampling is denser than 3D visibility and attribute 0 is unknown", () => {
    const realShape = structuredClone(annotation);
    realShape.lane_lines = [{
      category: 1,
      attribute: 0,
      track_id: 7,
      visibility: [1, 1, .5],
      uv: [[720, 740, 760, 780], [700, 670, 640, 610]],
      xyz: [[5, 10, 15], [2.5, 2.25, 2], [0, .1, .2]],
    }];

    const frame = parseOpenLaneAnnotation(realShape, {
      datasetVersion: "v1.2",
      frameRef: "lane3d_1000/validation/real-segment/frame.json",
    });

    expect(frame.lanes[0]).toMatchObject({
      attribute: { id: 0, name: "unknown" },
      points2d: [[720, 700], [740, 670], [760, 640], [780, 610]],
      points3d: [[5, 2.5, 0], [10, 2.25, .1], [15, 2, .2]],
    });
  });

  it("selects one stable lane reference for both 2D and 3D views", () => {
    const frame = parseOpenLaneAnnotation(annotation, {
      datasetVersion: "v1.2",
      frameRef: manifest.annotation_ref,
    });
    const selected = createOpenLaneViewModel(
      frame,
      "openlane:validation/synthetic-segment/frame-0001.jpg#lane:102",
    );

    expect(selected.selectedLane).toEqual(frame.lanes[1]);
    expect(selected.selectedLane?.lane2dRef).toContain("#lane:102:2d");
    expect(selected.selectedLane?.lane3dRef).toContain("#lane:102:3d");
  });
});

describe("OpenLane read-only data boundary", () => {
  it("scans with read-only operations and produces an unchanged redacted audit without media", async () => {
    const before = await summarizeOpenLaneDataRoot(fixtureRoot);
    const scan = await scanOpenLaneDataRoot(fixtureRoot);
    const after = await summarizeOpenLaneDataRoot(fixtureRoot);
    const audit = createOpenLaneReadonlyAudit(before, after);

    expect(before).toEqual(after);
    expect(before.digest).toBe(`sha256:${expectedRootDigest}`);
    expect(scan).toEqual({
      schemaVersion: "openlane-scan.v1",
      datasetVersion: "v1.2",
      rootId: `openlane:${expectedRootDigest.slice(0, 16)}`,
      rootDigest: `sha256:${expectedRootDigest}`,
      annotationFileCount: 1,
      laneCount: 2,
      imageFileCount: 0,
      missingAssets: ["image:validation/synthetic-segment/frame-0001.jpg"],
      affectedScopes: ["frame:lane3d_1000/validation/synthetic-segment/frame-0001.json"],
    });
    expect(audit).toEqual({
      schemaVersion: "openlane-readonly-audit.v1",
      datasetVersion: "v1.2",
      rootId: `openlane:${expectedRootDigest.slice(0, 16)}`,
      dataRootBeforeDigest: `sha256:${expectedRootDigest}`,
      dataRootAfterDigest: `sha256:${expectedRootDigest}`,
      unchanged: true,
      fileCount: 1,
      mediaIncluded: false,
      absolutePathsIncluded: false,
      acquisitionRequired: true,
      nonCommercialUseOnly: true,
    });
    expect(JSON.stringify(audit)).not.toContain(fixtureRoot.pathname);
    expect(JSON.stringify(audit)).not.toContain(".jpg");
  });
});

describe("OpenLane feature UI", () => {
  it("renders linked 2D/3D references, ordered points, visibility, attributes, and license notice", async () => {
    const frame = parseOpenLaneAnnotation(annotation, {
      datasetVersion: "v1.2",
      frameRef: manifest.annotation_ref,
    });
    const summary = await summarizeOpenLaneDataRoot(fixtureRoot);
    const audit = createOpenLaneReadonlyAudit(summary, summary);
    const html = renderToStaticMarkup(createElement(OpenLaneFeature, {
      frame,
      audit,
      fixtureDigest: `sha256:${expectedRootDigest}`,
      initialSelectedLaneRef: "openlane:validation/synthetic-segment/frame-0001.jpg#lane:102",
    }));

    expect(html).toContain("OpenLane V1.2");
    expect(html).toContain("openlane:validation/synthetic-segment/frame-0001.jpg#lane:102:2d");
    expect(html).toContain("openlane:validation/synthetic-segment/frame-0001.jpg#lane:102:3d");
    expect(html).toContain("yellow-solid");
    expect(html).toContain("right");
    expect(html).toContain("1, 0.5, 0");
    expect(html).toContain("Non-commercial use only");
    expect(html).toContain(expectedRootDigest);
  });
});

describe("OpenLane assembly-ready E2E contract", () => {
  it("pins V1.2 digest, linked lanes, network/read-only audit, and evidence receipt fields", () => {
    const spec = readFileSync(new URL("../e2e/specs/openlane.spec.ts", import.meta.url), "utf8");

    for (const required of [
      "@playwright/test",
      `sha256:${expectedRootDigest}`,
      "openlane-2d-selected-ref",
      "openlane-3d-selected-ref",
      "nonLoopbackRequests",
      "openlane-data-root-before",
      "openlane-data-root-after",
      "openlane-media-included",
      "openlane-absolute-paths-included",
      "schema_version",
      "command_id",
      "source_commit",
      "production_build_digest",
      "runner",
      "browser",
      "fixture",
      "started_at",
      "finished_at",
      "exit_status",
      "exit_code",
      "data_root_before_digest",
      "data_root_after_digest",
      "artifacts",
      "network",
      "result",
    ]) {
      expect(spec).toContain(required);
    }
  });
});

describe("OpenLane delivery boundary", () => {
  it("documents acquisition/license limits and records a redacted implementation manifest", () => {
    const documentation = readFileSync(new URL("../../docs/openlane/README.md", import.meta.url), "utf8");
    const implementation = JSON.parse(
      readFileSync(new URL("../../artifacts/tasks/openlane/implementation-manifest.json", import.meta.url), "utf8"),
    );

    expect(documentation).toContain("Waymo Open Dataset");
    expect(documentation).toContain("CC BY-NC-SA");
    expect(documentation).toContain("Non-Commercial Use");
    expect(documentation).toContain("原始媒体不会进入源码仓库、workspace 或 evidence receipt");
    expect(implementation).toEqual({
      schema_version: "openlane-implementation-manifest.v1",
      task_id: "SWB-OPENLANE-003-R3",
      dataset_version: "v1.2",
      fixture: {
        kind: "synthetic",
        root_sha256: expectedRootDigest,
        annotation_sha256: "2062fabc301f1c1268d9b9cfeb7542fe04f14150166728913d2ba1b0c578eb43",
        raw_media_included: false,
      },
      data_boundary: {
        data_root_mode: "read-only",
        mutable_root_mode: "workspace-only",
        receipt_media_included: false,
        receipt_absolute_paths_included: false,
        commercial_use: "prohibited",
      },
      source_refs: manifest.source_refs,
      acceptance_coverage: {
        "AC-07": ["app/tests/openlane/openlane.test.ts", "app/tests/e2e/specs/openlane.spec.ts"],
        "SWB-OPENLANE-003-R3-AC-READONLY-LICENSE": [
          "app/tests/openlane/openlane.test.ts",
          "app/docs/openlane/README.md",
        ],
        "SWB-OPENLANE-003-R3-AC-E2E-SPEC": ["app/tests/e2e/specs/openlane.spec.ts"],
      },
      verification_commands: [
        "npm --prefix app run test:openlane",
        "npm --prefix app run verify:e2e-specs:openlane",
      ],
      rework_evidence: {
        task_map_schema_version: "task-map.v1",
        task_map_status: "ready",
        task_map_sha256: "219e595ef6b6869d552f752e7ff13a081e48cdae6a8992b68a3e0da5186d3149",
      },
    });
    expect(JSON.stringify(implementation)).not.toMatch(/\/home\/|[A-Za-z]:\\/);
  });
});
