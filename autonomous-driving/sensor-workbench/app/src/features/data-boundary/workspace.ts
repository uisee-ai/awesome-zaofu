import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";

import { WORKSPACE_CONTRACT_VERSION, type WorkspaceV1 } from "../../contracts";
import { digestDataRoot } from "./scanner";

export interface ReadonlyWorkspaceOptions {
  readonly dataRoot: string;
  readonly outputRoot: string;
  readonly maxCacheBytes: number;
  readonly now: string;
}

const relativePaths = {
  indexDirectory: "index",
  cacheDirectory: "cache",
  reviewLog: "review/events.jsonl",
  exportDirectory: "exports",
  evidenceDirectory: "evidence",
} as const;

export async function createReadonlyWorkspace(options: ReadonlyWorkspaceOptions): Promise<WorkspaceV1> {
  if (!Number.isSafeInteger(options.maxCacheBytes) || options.maxCacheBytes < 1) {
    throw new RangeError("maxCacheBytes must be a positive safe integer");
  }
  if (Number.isNaN(Date.parse(options.now))) throw new TypeError("now must be an RFC 3339 timestamp");
  for (const path of [
    relativePaths.indexDirectory,
    relativePaths.cacheDirectory,
    "review",
    relativePaths.exportDirectory,
    relativePaths.evidenceDirectory,
  ]) {
    await mkdir(resolve(options.outputRoot, path), { recursive: true });
  }
  const dataRootDigest = await digestDataRoot(options.dataRoot);
  return {
    schemaVersion: WORKSPACE_CONTRACT_VERSION,
    workspaceId: `workspace:${dataRootDigest.slice("sha256:".length, "sha256:".length + 12)}`,
    createdAt: options.now,
    dataRootDigest,
    dataRootMode: "read-only",
    mutableRootMode: "workspace-only",
    maxCacheBytes: options.maxCacheBytes,
    paths: relativePaths,
  };
}
