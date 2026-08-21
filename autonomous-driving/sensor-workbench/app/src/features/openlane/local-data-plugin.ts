import { createHash } from "node:crypto";
import { execFile, spawn } from "node:child_process";
import { realpath, stat } from "node:fs/promises";

import type { Plugin } from "vite";

import { authorizeLocalRequest, BoundaryViolation, resolveDataAsset } from "../data-boundary/security.ts";
import { parseOpenLaneAnnotation, type OpenLaneFrame } from "./model.ts";

const ANNOTATION_ARCHIVE = "lane3d_1000_v1.2.zip";
const IMAGE_ARCHIVE = "images_validation_0.tar";
const PRIMARY_FRAME_LIMIT = 6;
const EXTRA_SEGMENT_LIMIT = 4;
const IMAGE_ENTRY = /^images_validation_0\/([^/]+)\/([0-9]+)\.jpg$/;

interface LocalOpenLaneFrame {
  readonly frameRef: string;
  readonly imageUrl: string;
  readonly frame: OpenLaneFrame;
}

interface LoadedOpenLane {
  readonly imageArchive: string;
  readonly manifest: {
    readonly schemaVersion: "local-openlane-workbench.v1";
    readonly datasetVersion: "v1.2";
    readonly sourceDigest: string;
    readonly frames: readonly LocalOpenLaneFrame[];
  };
  readonly assets: ReadonlyMap<string, { readonly entry: string }>;
}

function executeText(command: string, args: readonly string[], maxBuffer: number): Promise<string> {
  return new Promise((resolve, reject) => {
    execFile(command, args, { encoding: "utf8", maxBuffer }, (error, stdout) => {
      if (error) reject(error);
      else resolve(stdout);
    });
  });
}

function authorize(request: { readonly headers: { readonly host?: string; readonly origin?: string | readonly string[] }; readonly method?: string }) {
  const origin = request.headers.origin;
  authorizeLocalRequest({
    host: request.headers.host ?? "",
    origin: Array.isArray(origin) ? origin[0] : origin,
    method: request.method ?? "GET",
  });
}

export function localOpenLanePlugin(): Plugin {
  const configuredRoot = process.env.OPENLANE_DATA_ROOT;
  let cache: Promise<LoadedOpenLane | null> | undefined;

  async function load(): Promise<LoadedOpenLane | null> {
    if (!configuredRoot) return null;
    const root = await realpath(configuredRoot);
    const annotationArchive = await resolveDataAsset(root, ANNOTATION_ARCHIVE);
    const imageArchive = await resolveDataAsset(root, IMAGE_ARCHIVE);
    const [annotationInfo, imageInfo] = await Promise.all([stat(annotationArchive), stat(imageArchive)]);
    if (!annotationInfo.isFile() || !imageInfo.isFile()) throw new TypeError("invalid OpenLane archives");

    const listing = await executeText("tar", ["-tf", imageArchive], 32 * 1024 * 1024);
    const candidates = listing.split("\n").flatMap((entry) => {
      const match = IMAGE_ENTRY.exec(entry);
      return match ? [{ entry, segment: match[1]!, imageId: match[2]! }] : [];
    });
    const firstSegment = candidates[0]?.segment;
    if (!firstSegment) throw new TypeError("OpenLane validation image archive is empty");
    const primaryFrames = candidates.filter((candidate) => candidate.segment === firstSegment).slice(0, PRIMARY_FRAME_LIMIT);
    const seenSegments = new Set([firstSegment]);
    const extraFrames: typeof candidates = [];
    for (const candidate of candidates) {
      if (seenSegments.has(candidate.segment)) continue;
      seenSegments.add(candidate.segment);
      extraFrames.push(candidate);
      if (extraFrames.length === EXTRA_SEGMENT_LIMIT) break;
    }
    const selected = [...primaryFrames, ...extraFrames];
    const assets = new Map<string, { readonly entry: string }>();
    const frames = await Promise.all(selected.map(async (candidate, index): Promise<LocalOpenLaneFrame> => {
      const frameRef = `lane3d_1000/validation/${candidate.segment}/${candidate.imageId}.json`;
      const annotationText = await executeText("unzip", ["-p", annotationArchive, frameRef], 8 * 1024 * 1024);
      const frame = parseOpenLaneAnnotation(JSON.parse(annotationText), { datasetVersion: "v1.2", frameRef });
      const assetId = String(index);
      assets.set(assetId, { entry: candidate.entry });
      return { frameRef, imageUrl: `/local-openlane/assets/${assetId}`, frame };
    }));
    if (frames.length === 0) throw new TypeError("OpenLane validation frames are unavailable");

    const sourceDigest = `sha256:${createHash("sha256").update(JSON.stringify({
      annotationBytes: annotationInfo.size,
      annotationMtimeMs: annotationInfo.mtimeMs,
      imageBytes: imageInfo.size,
      imageMtimeMs: imageInfo.mtimeMs,
      frames: frames.map((frame) => frame.frameRef),
    })).digest("hex")}`;
    return {
      imageArchive,
      manifest: { schemaVersion: "local-openlane-workbench.v1", datasetVersion: "v1.2", sourceDigest, frames },
      assets,
    };
  }

  return {
    name: "local-openlane-workbench",
    configureServer(server) {
      server.middlewares.use(async (request, response, next) => {
        const path = new URL(request.url ?? "/", "http://127.0.0.1").pathname;
        if (!path.startsWith("/local-openlane/")) return next();
        try {
          if (!["GET", "HEAD"].includes(request.method ?? "GET")) {
            response.statusCode = 405;
            response.setHeader("Allow", "GET, HEAD");
            response.end();
            return;
          }
          authorize(request);
          cache ??= load();
          const data = await cache;
          if (!data) { response.statusCode = 404; response.end(); return; }
          if (path === "/local-openlane/manifest") {
            response.setHeader("Content-Type", "application/json; charset=utf-8");
            response.setHeader("Cache-Control", "no-store");
            response.end(request.method === "HEAD" ? undefined : JSON.stringify(data.manifest));
            return;
          }
          const assetId = path.match(/^\/local-openlane\/assets\/([0-9]+)$/)?.[1];
          const asset = assetId ? data.assets.get(assetId) : undefined;
          if (!asset) { response.statusCode = 404; response.end(); return; }
          response.setHeader("Content-Type", "image/jpeg");
          response.setHeader("Cache-Control", "private, max-age=3600");
          if (request.method === "HEAD") { response.end(); return; }
          const child = spawn("tar", ["-xOf", data.imageArchive, asset.entry], { stdio: ["ignore", "pipe", "ignore"] });
          child.stdout.pipe(response);
          child.once("error", () => { if (!response.headersSent) response.statusCode = 500; response.destroy(); });
          child.once("close", (code) => { if (code !== 0 && !response.writableEnded) response.destroy(); });
          response.once("close", () => { if (child.exitCode === null) child.kill(); });
        } catch (error) {
          response.statusCode = error instanceof BoundaryViolation ? 403 : 500;
          response.setHeader("Content-Type", "application/json; charset=utf-8");
          response.end(JSON.stringify({ error: "local OpenLane data unavailable" }));
        }
      });
    },
  };
}
