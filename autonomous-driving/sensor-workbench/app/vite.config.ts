import { createReadStream } from "node:fs";
import { readFile, realpath, stat } from "node:fs/promises";
import { resolve, sep } from "node:path";

import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";
import { authorizeLocalRequest, BoundaryViolation, resolveDataAsset } from "./src/features/data-boundary/security.ts";
import { localOpenLanePlugin } from "./src/features/openlane/local-data-plugin.ts";

const CAMERA_CHANNELS = ["CAM_FRONT", "CAM_FRONT_RIGHT", "CAM_BACK_RIGHT", "CAM_BACK", "CAM_BACK_LEFT", "CAM_FRONT_LEFT"] as const;
interface RecordRow { readonly token: string; readonly [key: string]: unknown }
interface Asset { readonly relativePath: string; readonly mime: "image/jpeg" | "application/octet-stream" }
interface LoadedNuScenes { readonly root: string; readonly manifest: object; readonly assets: ReadonlyMap<string, Asset> }

function rows(value: unknown, name: string): readonly RecordRow[] {
  if (!Array.isArray(value)) throw new TypeError(`${name} must be an array`);
  return value.map((row, index) => {
    if (!row || typeof row !== "object" || typeof (row as RecordRow).token !== "string") throw new TypeError(`${name}[${index}] is invalid`);
    return row as RecordRow;
  });
}
function text(row: RecordRow, key: string): string { const value = row[key]; if (typeof value !== "string") throw new TypeError(`${key} is invalid`); return value; }
function numberValue(row: RecordRow, key: string): number { const value = row[key]; if (typeof value !== "number") throw new TypeError(`${key} is invalid`); return value; }
function arrayValue(row: RecordRow, key: string): readonly number[] { const value = row[key]; if (!Array.isArray(value) || !value.every((item) => typeof item === "number")) throw new TypeError(`${key} is invalid`); return value; }

function localNuScenesPlugin(): Plugin {
  const configuredRoot = process.env.NUSCENES_DATA_ROOT;
  let cache: Promise<LoadedNuScenes | null> | undefined;
  async function table(root: string, name: string) { return rows(JSON.parse(await readFile(resolve(root, "v1.0-mini", name), "utf8")), name); }
  async function load() {
    if (!configuredRoot) return null;
    const root = await realpath(configuredRoot);
    if (!(await stat(resolve(root, "v1.0-mini"))).isDirectory()) throw new TypeError("invalid nuScenes root");
    const [scenes, samples, sampleData, calibrated, sensors, egoPoses, annotations, instances, categories] = await Promise.all([
      table(root, "scene.json"), table(root, "sample.json"), table(root, "sample_data.json"), table(root, "calibrated_sensor.json"),
      table(root, "sensor.json"), table(root, "ego_pose.json"), table(root, "sample_annotation.json"), table(root, "instance.json"), table(root, "category.json"),
    ]);
    const byToken = <T extends RecordRow>(items: readonly T[]) => new Map(items.map((item) => [item.token, item]));
    const sampleMap = byToken(samples); const sensorMap = byToken(sensors); const calibratedMap = byToken(calibrated); const egoMap = byToken(egoPoses);
    const categoryMap = byToken(categories); const instanceMap = byToken(instances);
    const channelByCalibrated = new Map(calibrated.map((item) => [item.token, text(sensorMap.get(text(item, "sensor_token"))!, "channel")]));
    const sampleDataBySample = new Map<string, RecordRow[]>();
    for (const item of sampleData) {
      if (item.is_key_frame !== true) continue;
      const token = text(item, "sample_token");
      sampleDataBySample.set(token, [...(sampleDataBySample.get(token) ?? []), item]);
    }
    const annotationsBySample = new Map<string, RecordRow[]>();
    for (const item of annotations) {
      const token = text(item, "sample_token");
      annotationsBySample.set(token, [...(annotationsBySample.get(token) ?? []), item]);
    }
    const assets = new Map<string, Asset>();
    const safeAsset = (item: RecordRow, mime: Asset["mime"]) => {
      const relativePath = text(item, "filename");
      const candidate = resolve(root, relativePath);
      if (candidate !== root && !candidate.startsWith(`${root}${sep}`)) return null;
      assets.set(item.token, { relativePath, mime });
      return `/local-nuscenes/assets/${item.token}`;
    };
    const manifestScenes = scenes.map((scene) => {
      const frames: object[] = [];
      let sampleToken = text(scene, "first_sample_token");
      while (sampleToken) {
        const sample = sampleMap.get(sampleToken); if (!sample) break;
        const data = sampleDataBySample.get(sampleToken) ?? [];
        const byChannel = new Map(data.map((item) => [channelByCalibrated.get(text(item, "calibrated_sensor_token")), item]));
        const cameras = CAMERA_CHANNELS.flatMap((channel) => {
          const item = byChannel.get(channel); if (!item) return [];
          const assetUrl = safeAsset(item, "image/jpeg"); if (!assetUrl) return [];
          return [{ sensorId: channel, timestampUs: numberValue(item, "timestamp"), assetUrl }];
        });
        const lidar = byChannel.get("LIDAR_TOP");
        const lidarCalibration = lidar ? calibratedMap.get(text(lidar, "calibrated_sensor_token")) : undefined;
        const egoPose = lidar ? egoMap.get(text(lidar, "ego_pose_token")) : undefined;
        const frameAnnotations = (annotationsBySample.get(sampleToken) ?? []).map((annotation) => {
          const instance = instanceMap.get(text(annotation, "instance_token"));
          const category = instance ? categoryMap.get(text(instance, "category_token")) : undefined;
          return {
            annotationRef: annotation.token, instanceRef: text(annotation, "instance_token"), category: category ? text(category, "name") : "unknown",
            translation: arrayValue(annotation, "translation"), size: arrayValue(annotation, "size"), rotation: arrayValue(annotation, "rotation"),
            numLidarPoints: numberValue(annotation, "num_lidar_pts"),
          };
        });
        frames.push({
          frameRef: sample.token, timestampUs: numberValue(sample, "timestamp"), cameras,
          lidar: lidar && lidarCalibration && egoPose ? {
            timestampUs: numberValue(lidar, "timestamp"), assetUrl: safeAsset(lidar, "application/octet-stream"),
            calibration: { translation: arrayValue(lidarCalibration, "translation"), rotation: arrayValue(lidarCalibration, "rotation") },
            egoPose: { translation: arrayValue(egoPose, "translation"), rotation: arrayValue(egoPose, "rotation") },
          } : null,
          annotations: frameAnnotations,
        });
        sampleToken = text(sample, "next");
      }
      return { sceneRef: text(scene, "name"), description: text(scene, "description"), frames };
    });
    return { root, manifest: { schemaVersion: "local-nuscenes-workbench.v1", datasetVersion: "v1.0-mini", scenes: manifestScenes }, assets };
  }
  return {
    name: "local-nuscenes-workbench",
    configureServer(server) {
      server.middlewares.use(async (request, response, next) => {
        const path = new URL(request.url ?? "/", "http://127.0.0.1").pathname;
        if (!path.startsWith("/local-nuscenes/")) return next();
        try {
          if (!["GET", "HEAD"].includes(request.method ?? "GET")) {
            response.statusCode = 405;
            response.setHeader("Allow", "GET, HEAD");
            response.end();
            return;
          }
          const originHeader = request.headers.origin;
          authorizeLocalRequest({
            host: request.headers.host ?? "",
            origin: Array.isArray(originHeader) ? originHeader[0] : originHeader,
            method: request.method ?? "GET",
          });
          cache ??= load(); const data = await cache;
          if (!data) { response.statusCode = 404; response.end(); return; }
          if (path === "/local-nuscenes/manifest") { response.setHeader("Content-Type", "application/json; charset=utf-8"); response.setHeader("Cache-Control", "no-store"); response.end(request.method === "HEAD" ? undefined : JSON.stringify(data.manifest)); return; }
          const id = path.match(/^\/local-nuscenes\/assets\/([a-f0-9]{32})$/)?.[1]; const asset = id ? data.assets.get(id) : undefined;
          if (!asset) { response.statusCode = 404; response.end(); return; }
          const safePath = await resolveDataAsset(data.root, asset.relativePath);
          response.setHeader("Content-Type", asset.mime); response.setHeader("Cache-Control", "private, max-age=3600");
          if (request.method === "HEAD") response.end(); else createReadStream(safePath).pipe(response);
        } catch (error) { response.statusCode = error instanceof BoundaryViolation ? 403 : 500; response.end(JSON.stringify({ error: "local data unavailable" })); }
      });
    },
  };
}

export default defineConfig({
  plugins: [react(), localNuScenesPlugin(), localOpenLanePlugin()],
  server: { host: "127.0.0.1", port: 4173, strictPort: true },
  preview: { host: "127.0.0.1", port: 4173, strictPort: true },
  build: { sourcemap: true },
});
