import { useEffect, useState } from "react";

import type { FrameContextV1 } from "../../contracts";
import { DemoMultimodalViews, type DemoFrameVisual } from "./DemoMultimodalViews";
import type { FrameSelectionResult } from "./frame-context";
import type { InstanceSelectionV1 } from "./instance-selection";
import type { NuScenesSearchResult } from "./search";

export interface NuScenesFeatureEvidence {
  readonly dataRootDigestBefore: string;
  readonly dataRootDigestAfter: string;
  readonly absolutePathsIncluded: false;
  readonly pointCloud: {
    readonly worker: true;
    readonly lod: number;
    readonly maxChunkBytes: number;
  };
  readonly cache: {
    readonly hardLimit: true;
    readonly evictionPolicy: "lru";
  };
}

export interface NuScenesWorkbenchProps {
  readonly frameRefs: readonly string[];
  readonly instanceRefs: readonly string[];
  readonly visualsByFrame: Readonly<Record<string, DemoFrameVisual>>;
  readonly selectFrame: (frameRef: string) => Promise<FrameSelectionResult>;
  readonly selectInstance: (instanceRef: string) => InstanceSelectionV1;
  readonly search: (text: string, weather: "rain" | undefined) => readonly NuScenesSearchResult[];
  readonly evidence: NuScenesFeatureEvidence;
  readonly onFrameContextChange?: (context: FrameContextV1) => void;
  readonly onInstanceSelectionChange?: (selection: InstanceSelectionV1) => void;
}

function resultTestId(stableId: string): string {
  return stableId.replaceAll(":", "-");
}

export function NuScenesWorkbench(props: NuScenesWorkbenchProps) {
  const [context, setContext] = useState<FrameContextV1 | null>(null);
  const [selection, setSelection] = useState<InstanceSelectionV1 | null>(null);
  const [query, setQuery] = useState("");
  const [rain, setRain] = useState(false);
  const [results, setResults] = useState<readonly NuScenesSearchResult[]>([]);
  const [activeFrameRef, setActiveFrameRef] = useState(props.frameRefs[0] ?? "");
  const [playing, setPlaying] = useState(false);

  async function jump(frameRef: string) {
    const result = await props.selectFrame(frameRef);
    if (result.committed && result.context) {
      setActiveFrameRef(frameRef);
      setContext(result.context);
      props.onFrameContextChange?.(result.context);
    }
  }

  function moveFrame(offset: number) {
    if (props.frameRefs.length === 0) return;
    const currentIndex = Math.max(0, props.frameRefs.indexOf(activeFrameRef));
    const nextIndex = (currentIndex + offset + props.frameRefs.length) % props.frameRefs.length;
    void jump(props.frameRefs[nextIndex]!);
  }

  useEffect(() => {
    if (!playing || props.frameRefs.length < 2) return undefined;
    const timer = globalThis.setInterval(() => moveFrame(1), 900);
    return () => globalThis.clearInterval(timer);
  });

  function selectInstance(instanceRef: string) {
    const nextSelection = props.selectInstance(instanceRef);
    setSelection(nextSelection);
    props.onInstanceSelectionChange?.(nextSelection);
  }

  function updateSearch(text: string, weatherRain: boolean) {
    setResults(props.search(text, weatherRain ? "rain" : undefined));
  }

  return (
    <section data-testid="adapter-nuscenes-panel" aria-label="nuScenes keyframe workbench">
      <button data-testid="adapter-nuscenes" type="button">
        nuScenes
      </button>
      <nav aria-label="Keyframes">
        {props.frameRefs.map((frameRef) => (
          <button
            key={frameRef}
            aria-label={`选择帧 ${frameRef}`}
            data-testid={`frame-jump-${frameRef}`}
            type="button"
            onClick={() => void jump(frameRef)}
          >
            {frameRef}
          </button>
        ))}
      </nav>
      <section className="swb-timeline" data-testid="timeline-controls" aria-label="Keyframe 时间轴">
        <div>
          <button type="button" aria-label="上一帧" onClick={() => moveFrame(-1)}>上一帧</button>
          <button type="button" aria-label={playing ? "暂停播放" : "播放时间轴"} onClick={() => setPlaying((value) => !value)}>
            {playing ? "暂停" : "播放"}
          </button>
          <button type="button" aria-label="下一帧" onClick={() => moveFrame(1)}>下一帧</button>
        </div>
        <output data-testid="timeline-position">{Math.max(0, props.frameRefs.indexOf(activeFrameRef)) + 1} / {props.frameRefs.length}</output>
        <p>锚点：nuScenes keyframe（2Hz）· 当前同步策略：以 LIDAR_TOP 为基准</p>
      </section>
      <output data-testid="frame-context-id">{context?.frameContextId ?? "unselected"}</output>
      {context?.sensorFrames.map((sensor) => (
        <output key={sensor.sensorId} data-testid={`sensor-delta-${sensor.sensorId}`}>
          {sensor.deltaMs} ms
        </output>
      ))}
      <div aria-label="Instances">
        {props.instanceRefs.map((instanceRef) => (
          <button
            key={instanceRef}
            aria-label={`选择实例 ${instanceRef}`}
            data-testid={`instance-${instanceRef}`}
            type="button"
            onClick={() => selectInstance(instanceRef)}
          >
            {instanceRef}
          </button>
        ))}
      </div>
      {(["camera", "lidar", "bev", "annotation-chain"] as const).map((view) => (
        <div key={view} data-testid={`${view}-selection`} data-stable-ref={selection?.stableInstanceRef ?? "unselected"} />
      ))}
      <DemoMultimodalViews
        frame={context ? props.visualsByFrame[context.frameRef] ?? null : null}
        context={context}
        selectedInstanceRef={selection?.stableInstanceRef ?? null}
      />
      <label>
        Search scenes
        <input
          data-testid="scene-search"
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            updateSearch(event.target.value, rain);
          }}
        />
      </label>
      <label>
        Rain
        <input
          data-testid="filter-weather-rain"
          type="checkbox"
          checked={rain}
          onChange={(event) => {
            setRain(event.target.checked);
            updateSearch(query, event.target.checked);
          }}
        />
      </label>
      <ul>
        {results.map((result) => (
          <li
            key={result.stableId}
            data-testid={`search-result-${resultTestId(result.stableId)}`}
            data-rule-version={result.ruleVersion}
          >
            {result.sourceText}
          </li>
        ))}
      </ul>
      <output
        data-testid="data-boundary-status"
        data-absolute-paths-included={String(props.evidence.absolutePathsIncluded)}
      />
      <output data-testid="data-root-digest-before">{props.evidence.dataRootDigestBefore}</output>
      <output data-testid="data-root-digest-after">{props.evidence.dataRootDigestAfter}</output>
      <output
        data-testid="point-cloud-metrics"
        data-worker={String(props.evidence.pointCloud.worker)}
        data-lod={props.evidence.pointCloud.lod}
        data-max-chunk-bytes={props.evidence.pointCloud.maxChunkBytes}
      />
      <output
        data-testid="cache-metrics"
        data-hard-limit={String(props.evidence.cache.hardLimit)}
        data-eviction-policy={props.evidence.cache.evictionPolicy}
      />
    </section>
  );
}
