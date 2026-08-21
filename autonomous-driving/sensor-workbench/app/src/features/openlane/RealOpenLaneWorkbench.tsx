import { useEffect, useMemo, useState } from "react";

import type { OpenLaneFrame } from "./model";
import { OpenLaneFeature } from "./OpenLaneFeature";
import type { OpenLaneReadonlyAudit } from "./readonly";

interface LocalOpenLaneFrame {
  readonly frameRef: string;
  readonly imageUrl: string;
  readonly frame: OpenLaneFrame;
}

interface LocalOpenLaneManifest {
  readonly schemaVersion: "local-openlane-workbench.v1";
  readonly datasetVersion: "v1.2";
  readonly sourceDigest: string;
  readonly frames: readonly LocalOpenLaneFrame[];
}

function isManifest(value: unknown): value is LocalOpenLaneManifest {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<LocalOpenLaneManifest>;
  return candidate.schemaVersion === "local-openlane-workbench.v1"
    && candidate.datasetVersion === "v1.2"
    && typeof candidate.sourceDigest === "string"
    && /^sha256:[0-9a-f]{64}$/.test(candidate.sourceDigest)
    && Array.isArray(candidate.frames)
    && candidate.frames.length > 0
    && candidate.frames.every((item) => item && typeof item.frameRef === "string" && typeof item.imageUrl === "string" && item.frame?.datasetVersion === "v1.2");
}

function frameLabel(frameRef: string): string {
  const parts = frameRef.split("/");
  return `${parts.at(-2) ?? "segment"} / ${(parts.at(-1) ?? frameRef).replace(/\.json$/, "")}`;
}

function frameOptionLabel(frameRef: string, index: number): string {
  const imageId = (frameRef.split("/").at(-1) ?? frameRef).replace(/\.json$/, "");
  return `样本 ${index + 1} · ${imageId}`;
}

export interface RealOpenLaneWorkbenchProps {
  readonly onAvailabilityChange: (available: boolean) => void;
}

export function RealOpenLaneWorkbench({ onAvailabilityChange }: RealOpenLaneWorkbenchProps) {
  const [manifest, setManifest] = useState<LocalOpenLaneManifest | null>(null);
  const [frameIndex, setFrameIndex] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    void fetch("/local-openlane/manifest", { signal: controller.signal })
      .then((response) => response.ok ? response.json() as Promise<unknown> : Promise.reject(new TypeError("local OpenLane manifest unavailable")))
      .then((result) => {
        if (!isManifest(result)) throw new TypeError("invalid local OpenLane manifest");
        setManifest(result);
        onAvailabilityChange(true);
      })
      .catch(() => onAvailabilityChange(false));
    return () => controller.abort();
  }, [onAvailabilityChange]);

  const audit = useMemo<OpenLaneReadonlyAudit | null>(() => manifest ? ({
    schemaVersion: "openlane-readonly-audit.v1",
    datasetVersion: "v1.2",
    rootId: `openlane:${manifest.sourceDigest.slice(7, 23)}`,
    dataRootBeforeDigest: manifest.sourceDigest,
    dataRootAfterDigest: manifest.sourceDigest,
    unchanged: true,
    fileCount: 2,
    mediaIncluded: false,
    absolutePathsIncluded: false,
    acquisitionRequired: true,
    nonCommercialUseOnly: true,
  }) : null, [manifest]);

  const current = manifest?.frames[frameIndex] ?? null;
  if (!manifest || !audit || !current) return null;
  const segmentCount = new Set(manifest.frames.map((item) => item.frameRef.split("/").at(-2))).size;
  const move = (offset: number) => setFrameIndex((index) => (index + offset + manifest.frames.length) % manifest.frames.length);

  return (
    <section className="swb-dataset-module" data-testid="real-openlane-panel" aria-label="真实 OpenLane validation 浏览器">
      <header className="swb-module-heading">
        <div>
          <p className="swb-eyebrow">LANE GEOMETRY REVIEW</p>
          <h3>OpenLane 车道标注浏览</h3>
          <p>选择演示帧并点击车道，在真实前视图与鸟瞰视图中核对同一条车道的二维、三维标注。</p>
        </div>
        <span className="swb-status-badge">只读数据</span>
      </header>

      <div className="swb-real-source swb-openlane-source">
        <strong>OpenLane V1.2 · Validation</strong>
        <label>演示帧
          <select data-testid="openlane-frame-select" value={frameIndex} onChange={(event) => setFrameIndex(Number(event.target.value))}>
            {manifest.frames.map((item, index) => <option key={item.frameRef} value={index}>{frameOptionLabel(item.frameRef, index)}</option>)}
          </select>
        </label>
        <span>从本地压缩包按需读取，共载入 {manifest.frames.length} 帧、{segmentCount} 个道路片段</span>
      </div>

      <section className="swb-timeline" data-testid="openlane-timeline-controls" aria-label="OpenLane 演示帧导航">
        <div className="swb-action-row">
          <button type="button" onClick={() => move(-1)}>上一张</button>
          <button type="button" onClick={() => move(1)}>下一张</button>
        </div>
        <output data-testid="openlane-timeline-position">第 {frameIndex + 1} / {manifest.frames.length} 张</output>
        <p data-testid="openlane-real-frame-ref">当前帧：{frameLabel(current.frameRef)}</p>
      </section>

      <OpenLaneFeature
        key={current.frameRef}
        frame={current.frame}
        audit={audit}
        fixtureDigest={manifest.sourceDigest}
        imageUrl={current.imageUrl}
        dataMode="local"
      />
    </section>
  );
}
