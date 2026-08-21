import { createHash } from "node:crypto";
import { lstat, readFile, readdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { join, posix, relative, resolve, sep } from "node:path";

import { parseOpenLaneAnnotation } from "./model";

export interface OpenLaneDataRootSummary {
  readonly rootId: string;
  readonly digest: string;
  readonly fileCount: number;
}

export interface OpenLaneScanResult {
  readonly schemaVersion: "openlane-scan.v1";
  readonly datasetVersion: "v1.2";
  readonly rootId: string;
  readonly rootDigest: string;
  readonly annotationFileCount: number;
  readonly laneCount: number;
  readonly imageFileCount: number;
  readonly missingAssets: readonly string[];
  readonly affectedScopes: readonly string[];
}

export interface OpenLaneReadonlyAudit {
  readonly schemaVersion: "openlane-readonly-audit.v1";
  readonly datasetVersion: "v1.2";
  readonly rootId: string;
  readonly dataRootBeforeDigest: string;
  readonly dataRootAfterDigest: string;
  readonly unchanged: boolean;
  readonly fileCount: number;
  readonly mediaIncluded: false;
  readonly absolutePathsIncluded: false;
  readonly acquisitionRequired: true;
  readonly nonCommercialUseOnly: true;
}

function rootPath(root: URL | string): string {
  return resolve(root instanceof URL ? fileURLToPath(root) : root);
}

async function listFiles(root: string, directory = root): Promise<readonly string[]> {
  const entries = await readdir(directory, { withFileTypes: true });
  const files: string[] = [];
  for (const entry of entries) {
    const path = join(directory, entry.name);
    const metadata = await lstat(path);
    if (metadata.isSymbolicLink()) throw new TypeError("OpenLane data roots must not contain symbolic links");
    if (metadata.isDirectory()) files.push(...await listFiles(root, path));
    else if (metadata.isFile()) files.push(posix.normalize(relative(root, path).split(sep).join("/")));
  }
  return files.sort();
}

export async function summarizeOpenLaneDataRoot(root: URL | string): Promise<OpenLaneDataRootSummary> {
  const resolvedRoot = rootPath(root);
  const files = await listFiles(resolvedRoot);
  const rootHash = createHash("sha256");
  for (const file of files) {
    const bytes = await readFile(join(resolvedRoot, ...file.split("/")));
    const fileDigest = createHash("sha256").update(bytes).digest("hex");
    rootHash.update(`${file}\0${fileDigest}\n`);
  }
  const digest = rootHash.digest("hex");
  return { rootId: `openlane:${digest.slice(0, 16)}`, digest: `sha256:${digest}`, fileCount: files.length };
}

export async function scanOpenLaneDataRoot(root: URL | string): Promise<OpenLaneScanResult> {
  const resolvedRoot = rootPath(root);
  const summary = await summarizeOpenLaneDataRoot(resolvedRoot);
  const files = await listFiles(resolvedRoot);
  const annotationFiles = files.filter((file) => /^lane3d_(?:300|1000)\/(?:training|validation|test)\/.+\.json$/.test(file));
  let laneCount = 0;
  let imageFileCount = 0;
  const missingAssets: string[] = [];
  const affectedScopes: string[] = [];

  for (const annotationFile of annotationFiles) {
    const annotation = JSON.parse(await readFile(join(resolvedRoot, ...annotationFile.split("/")), "utf8"));
    const frame = parseOpenLaneAnnotation(annotation, { datasetVersion: "v1.2", frameRef: annotationFile });
    laneCount += frame.lanes.length;
    try {
      const image = await lstat(join(resolvedRoot, "images", ...frame.imageRef.split("/")));
      if (image.isSymbolicLink() || !image.isFile()) throw new TypeError("OpenLane media ref must resolve to a regular file");
      imageFileCount += 1;
    } catch (error) {
      if (error instanceof Error && "code" in error && error.code === "ENOENT") {
        missingAssets.push(`image:${frame.imageRef}`);
        affectedScopes.push(`frame:${annotationFile}`);
      } else {
        throw error;
      }
    }
  }

  return {
    schemaVersion: "openlane-scan.v1",
    datasetVersion: "v1.2",
    rootId: summary.rootId,
    rootDigest: summary.digest,
    annotationFileCount: annotationFiles.length,
    laneCount,
    imageFileCount,
    missingAssets,
    affectedScopes,
  };
}

export function createOpenLaneReadonlyAudit(
  before: OpenLaneDataRootSummary,
  after: OpenLaneDataRootSummary,
): OpenLaneReadonlyAudit {
  return {
    schemaVersion: "openlane-readonly-audit.v1",
    datasetVersion: "v1.2",
    rootId: before.rootId,
    dataRootBeforeDigest: before.digest,
    dataRootAfterDigest: after.digest,
    unchanged: before.digest === after.digest && before.fileCount === after.fileCount,
    fileCount: before.fileCount,
    mediaIncluded: false,
    absolutePathsIncluded: false,
    acquisitionRequired: true,
    nonCommercialUseOnly: true,
  };
}
