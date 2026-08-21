import { createHash } from "node:crypto";
import { lstat, readdir, readFile, readlink } from "node:fs/promises";
import { relative, resolve, sep } from "node:path";

import type { DatasetScanResultV1 } from "../../contracts";

interface RequiredAssetRecord {
  readonly asset_id: string;
  readonly relative_path: string;
  readonly affected_scopes: readonly string[];
}

interface NuScenesMetadata {
  readonly schema_version: "sensor-workbench.synthetic-nuscenes.v1";
  readonly dataset_version: string;
  readonly required_assets: readonly RequiredAssetRecord[];
}

async function walk(root: string, directory: string): Promise<readonly string[]> {
  const entries = await readdir(directory, { withFileTypes: true });
  const paths: string[] = [];
  for (const entry of entries.sort((left, right) => left.name.localeCompare(right.name))) {
    const path = resolve(directory, entry.name);
    if (entry.isDirectory()) paths.push(...(await walk(root, path)));
    else paths.push(relative(root, path).split(sep).join("/"));
  }
  return paths;
}

export async function digestDataRoot(dataRoot: string): Promise<string> {
  const hash = createHash("sha256");
  for (const relativePath of await walk(dataRoot, dataRoot)) {
    const absolutePath = resolve(dataRoot, relativePath);
    const status = await lstat(absolutePath);
    hash.update(relativePath);
    hash.update("\0");
    if (status.isSymbolicLink()) {
      hash.update("symlink:");
      hash.update(await readlink(absolutePath));
    } else {
      hash.update(await readFile(absolutePath));
    }
    hash.update("\0");
  }
  return `sha256:${hash.digest("hex")}`;
}

function parseMetadata(input: unknown): NuScenesMetadata {
  if (typeof input !== "object" || input === null) throw new TypeError("metadata must be an object");
  const value = input as Partial<NuScenesMetadata>;
  if (value.schema_version !== "sensor-workbench.synthetic-nuscenes.v1") {
    throw new TypeError("metadata.schema_version is unsupported");
  }
  if (typeof value.dataset_version !== "string" || value.dataset_version.length === 0) {
    throw new TypeError("metadata.dataset_version is required");
  }
  if (!Array.isArray(value.required_assets)) throw new TypeError("metadata.required_assets must be an array");
  return value as NuScenesMetadata;
}

async function exists(path: string): Promise<boolean> {
  try {
    const status = await lstat(path);
    return status.isFile() && !status.isSymbolicLink();
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return false;
    throw error;
  }
}

export async function scanNuScenesDataRoot(dataRoot: string): Promise<DatasetScanResultV1> {
  const metadata = parseMetadata(JSON.parse(await readFile(resolve(dataRoot, "metadata.json"), "utf8")));
  const missing = [] as RequiredAssetRecord[];
  for (const asset of metadata.required_assets) {
    if (!(await exists(resolve(dataRoot, asset.relative_path)))) missing.push(asset);
  }
  return {
    datasetKind: "nuscenes",
    datasetVersion: metadata.dataset_version,
    rootDigest: await digestDataRoot(dataRoot),
    missingAssets: missing.map((asset) => asset.asset_id),
    affectedScopes: [...new Set(missing.flatMap((asset) => asset.affected_scopes))],
  };
}
