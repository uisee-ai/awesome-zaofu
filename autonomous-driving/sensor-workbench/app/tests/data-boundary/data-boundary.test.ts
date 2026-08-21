import { mkdtemp, mkdir, readFile, rm, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, resolve } from "node:path";
import { afterEach, describe, expect, test } from "vitest";

import {
  BoundaryViolation,
  assertLoopbackUrl,
  authorizeLocalRequest,
  resolveDataAsset,
} from "../../src/features/data-boundary/security";
import { digestDataRoot, scanNuScenesDataRoot } from "../../src/features/data-boundary/scanner";
import { createReadonlyWorkspace } from "../../src/features/data-boundary/workspace";
import { DeterministicByteCache, planPointCloudRead } from "../../src/features/data-boundary/point-cloud";

const temporaryDirectories: string[] = [];

async function temporaryDirectory(label: string): Promise<string> {
  const directory = await mkdtemp(resolve(tmpdir(), `sensor-workbench-${label}-`));
  temporaryDirectories.push(directory);
  return directory;
}

async function createSyntheticDataRoot(): Promise<string> {
  const root = await temporaryDirectory("data-root");
  const fixture = await readFile(new URL("../fixtures/synthetic/nuscenes/dataset.v1.json", import.meta.url), "utf8");
  await writeFile(resolve(root, "metadata.json"), fixture);
  for (const relativePath of ["samples/CAM_FRONT/front-0001.jpg", "samples/LIDAR_TOP/top-0001.pcd.bin"]) {
    await mkdir(dirname(resolve(root, relativePath)), { recursive: true });
    await writeFile(resolve(root, relativePath), `synthetic:${relativePath}`);
  }
  return root;
}

afterEach(async () => {
  await Promise.all(temporaryDirectories.splice(0).map((directory) => rm(directory, { recursive: true, force: true })));
});

describe("nuScenes data-root boundary", () => {
  test("scans version and complete missing-asset impact without exposing the absolute root", async () => {
    const root = await createSyntheticDataRoot();

    const result = await scanNuScenesDataRoot(root);

    expect(result).toEqual({
      datasetKind: "nuscenes",
      datasetVersion: "v1.0-mini",
      rootDigest: expect.stringMatching(/^sha256:[0-9a-f]{64}$/),
      missingAssets: ["asset:cam-back-0001"],
      affectedScopes: ["camera", "frame:sample-0001"],
    });
    expect(JSON.stringify(result)).not.toContain(root);
  });

  test("keeps the data-root digest unchanged and places every mutable path under output", async () => {
    const root = await createSyntheticDataRoot();
    const output = await temporaryDirectory("workspace-output");
    const before = await digestDataRoot(root);

    const workspace = await createReadonlyWorkspace({
      dataRoot: root,
      outputRoot: output,
      maxCacheBytes: 64,
      now: "2026-08-04T00:00:00.000Z",
    });
    const after = await digestDataRoot(root);

    expect(workspace).toEqual({
      schemaVersion: "workspace.v1",
      workspaceId: `workspace:${before.slice("sha256:".length, "sha256:".length + 12)}`,
      createdAt: "2026-08-04T00:00:00.000Z",
      dataRootDigest: before,
      dataRootMode: "read-only",
      mutableRootMode: "workspace-only",
      maxCacheBytes: 64,
      paths: {
        indexDirectory: "index",
        cacheDirectory: "cache",
        reviewLog: "review/events.jsonl",
        exportDirectory: "exports",
        evidenceDirectory: "evidence",
      },
    });
    expect(after).toBe(before);
  });

  test.each([
    ["traversal", "../secret.bin", "path_traversal"],
    ["encoded traversal", "%2e%2e%2fsecret.bin", "encoded_path_traversal"],
  ])("rejects %s with a redacted receipt", async (_label, unsafePath, expectedCode) => {
    const root = await createSyntheticDataRoot();

    await expect(resolveDataAsset(root, unsafePath)).rejects.toMatchObject({
      name: "BoundaryViolation",
      code: expectedCode,
      receipt: { target: "[redacted]", absolutePathsIncluded: false },
    });
  });

  test("rejects a symlink escape without putting either absolute path in the receipt", async () => {
    const root = await createSyntheticDataRoot();
    const outside = await temporaryDirectory("outside");
    await writeFile(resolve(outside, "secret.bin"), "secret");
    await symlink(resolve(outside, "secret.bin"), resolve(root, "escape.bin"));

    let failure: unknown;
    try {
      await resolveDataAsset(root, "escape.bin");
    } catch (error) {
      failure = error;
    }

    expect(failure).toBeInstanceOf(BoundaryViolation);
    expect(failure).toMatchObject({ code: "symlink_escape" });
    expect(JSON.stringify(failure)).not.toContain(root);
    expect(JSON.stringify(failure)).not.toContain(outside);
  });

  test.each([
    [{ host: "0.0.0.0:4173", origin: "http://127.0.0.1:4173", method: "GET" }, "invalid_host"],
    [{ host: "127.0.0.1:4173", origin: "https://evil.example", method: "GET" }, "invalid_origin"],
    [{ host: "localhost:4173", origin: "http://localhost:4173", method: "POST" }, "csrf_rejected"],
  ])("rejects invalid local request boundaries", (request, expectedCode) => {
    expect(() => authorizeLocalRequest(request)).toThrowError(expect.objectContaining({ code: expectedCode }));
  });

  test("accepts loopback reads and same-origin writes with a CSRF token", () => {
    expect(authorizeLocalRequest({ host: "127.0.0.1:4173", origin: "http://127.0.0.1:4173", method: "GET" })).toEqual({
      loopbackOnly: true,
      sameOrigin: true,
      writeAuthorized: false,
    });
    expect(
      authorizeLocalRequest({
        host: "localhost:4173",
        origin: "http://localhost:4173",
        method: "POST",
        csrfToken: "local-session-token",
        expectedCsrfToken: "local-session-token",
      }),
    ).toEqual({ loopbackOnly: true, sameOrigin: true, writeAuthorized: true });
    expect(assertLoopbackUrl("http://[::1]:4173/assets/frame.bin")).toBe("http://[::1]:4173/assets/frame.bin");
    expect(() => assertLoopbackUrl("https://cdn.example/frame.bin")).toThrowError(
      expect.objectContaining({ code: "non_loopback_request" }),
    );
  });
});

describe("bounded point-cloud reads", () => {
  test("plans bounded chunks, explicit LOD and worker transfer metrics", () => {
    expect(planPointCloudRead({ byteLength: 25, maxChunkBytes: 8, lod: 2 })).toEqual({
      byteLength: 25,
      maxChunkBytes: 8,
      lod: 2,
      worker: true,
      chunks: [
        { offset: 0, length: 8 },
        { offset: 8, length: 8 },
        { offset: 16, length: 8 },
        { offset: 24, length: 1 },
      ],
      metrics: { chunkCount: 4, largestChunkBytes: 8, transferredToWorker: true },
    });
  });

  test("enforces a hard byte ceiling with observable deterministic LRU eviction", () => {
    const cache = new DeterministicByteCache<string>(5);
    cache.set("frame-a", "aaa", 3);
    cache.set("frame-b", "bb", 2);
    expect(cache.get("frame-a")).toBe("aaa");

    cache.set("frame-c", "cccc", 4);

    expect(cache.snapshot()).toEqual({
      maxBytes: 5,
      usedBytes: 4,
      keys: ["frame-c"],
      evictions: [
        { key: "frame-b", bytes: 2, reason: "capacity" },
        { key: "frame-a", bytes: 3, reason: "capacity" },
      ],
    });
  });
});
