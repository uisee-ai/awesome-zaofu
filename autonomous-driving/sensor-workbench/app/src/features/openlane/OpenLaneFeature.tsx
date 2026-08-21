import { useEffect, useMemo, useState } from "react";

import type { OpenLaneReadonlyAudit } from "./readonly";
import { createOpenLaneViewModel, type OpenLaneFrame, type OpenLaneLane } from "./model";

export interface OpenLaneFeatureProps {
  readonly frame: OpenLaneFrame;
  readonly audit: OpenLaneReadonlyAudit;
  readonly fixtureDigest: string;
  readonly initialSelectedLaneRef?: string;
  readonly imageUrl?: string;
  readonly dataMode?: "synthetic" | "local";
}

interface OpenLaneLaneSelectionDetail {
  readonly laneRef: string;
}

const OPENLANE_LANE_SELECTION_EVENT = "openlane-lane-selected";
const BEV_WIDTH = 420;
const BEV_HEIGHT = 320;
const BEV_PADDING = 28;

const categoryLabels = new Map<number, string>([
  [0, "未知类型"], [1, "白色虚线"], [2, "白色实线"], [3, "双白虚线"], [4, "双白实线"],
  [5, "左虚右实白线"], [6, "左实右虚白线"], [7, "黄色虚线"], [8, "黄色实线"],
  [9, "双黄虚线"], [10, "双黄实线"], [11, "左虚右实黄线"], [12, "左实右虚黄线"],
  [20, "左侧路缘"], [21, "右侧路缘"],
]);
const attributeLabels = new Map<number, string>([
  [0, "未标注"], [1, "最左侧"], [2, "左侧"], [3, "右侧"], [4, "最右侧"],
]);

function points2d(lane: OpenLaneLane, scale: number): string {
  return lane.points2d.map(([u, v]) => `${u / scale},${v / scale}`).join(" ");
}

function pointSummary(points: readonly (readonly number[])[]): string {
  return `${points.length} 个点；起点 ${JSON.stringify(points.at(0))}，终点 ${JSON.stringify(points.at(-1))}`;
}

function laneLength(lane: OpenLaneLane): number {
  return lane.points3d.slice(1).reduce((total, point, index) => {
    const previous = lane.points3d[index]!;
    return total + Math.hypot(point[0] - previous[0], point[1] - previous[1], point[2] - previous[2]);
  }, 0);
}

function createBevProjection(lanes: readonly OpenLaneLane[]) {
  const points = lanes.flatMap((lane) => lane.points3d);
  const maxForward = Math.max(20, ...points.map(([x]) => x));
  const lateralExtent = Math.max(8, ...points.map(([, y]) => Math.abs(y)));
  const scale = Math.min(
    (BEV_WIDTH - BEV_PADDING * 2) / (lateralExtent * 2),
    (BEV_HEIGHT - BEV_PADDING * 2) / maxForward,
  );
  const project = ([x, y]: readonly [number, number, number]) => [BEV_WIDTH / 2 + y * scale, BEV_HEIGHT - BEV_PADDING - x * scale] as const;
  return {
    maxForward: Math.ceil(maxForward / 10) * 10,
    lateralExtent: Math.ceil(lateralExtent),
    project,
    polyline: (lane: OpenLaneLane) => lane.points3d.map((point) => project(point).join(",")).join(" "),
  };
}

export function OpenLaneFeature({ frame, audit, fixtureDigest, initialSelectedLaneRef, imageUrl, dataMode = "synthetic" }: OpenLaneFeatureProps) {
  const [selectedLaneRef, setSelectedLaneRef] = useState(initialSelectedLaneRef ?? frame.lanes[0]?.laneRef);
  const [categoryFilter, setCategoryFilter] = useState("all");
  const [attributeFilter, setAttributeFilter] = useState("all");
  const [visibleOnly, setVisibleOnly] = useState(false);
  const view = createOpenLaneViewModel(frame, selectedLaneRef);
  const lanes = view.lanes.filter((lane) =>
    (categoryFilter === "all" || lane.category.id === Number(categoryFilter))
    && (attributeFilter === "all" || lane.attribute.id === Number(attributeFilter))
    && (!visibleOnly || lane.visibility.some((visibility) => visibility >= .75)),
  );
  const selected = lanes.find((lane) => lane.laneRef === selectedLaneRef) ?? lanes[0] ?? null;
  const bev = useMemo(() => createBevProjection(lanes), [lanes]);

  const selectLane = (laneRef: string) => {
    setSelectedLaneRef(laneRef);
    globalThis.dispatchEvent(new CustomEvent<OpenLaneLaneSelectionDetail>(OPENLANE_LANE_SELECTION_EVENT, {
      detail: { laneRef },
    }));
  };

  useEffect(() => {
    if (selected && selected.laneRef !== selectedLaneRef) selectLane(selected.laneRef);
  }, [selected, selectedLaneRef]);

  return (
    <section className="swb-openlane" data-testid="openlane-feature" data-dataset-version="v1.2" data-fixture-digest={fixtureDigest} data-mode={dataMode}>
      <header className="swb-openlane-titlebar">
        <div>
          <h4>OpenLane V1.2 · 车道标注联动视图</h4>
          <p>先按类别或位置属性缩小范围，再选择一条车道。黄色表示当前车道，蓝灰色表示同帧其他车道。</p>
        </div>
        <span>{frame.lanes.length} 条原始标注</span>
      </header>
      <p className="swb-license-note" data-testid="openlane-license-notice">
        数据使用说明：本区域仅以只读方式展示本地 OpenLane 样本，不修改或分发原始媒体。Non-commercial use only.
      </p>

      <fieldset className="swb-lane-filters" aria-label="OpenLane 筛选">
        <legend>筛选条件</legend>
        <label><span>车道类别</span>
          <select data-testid="openlane-category-filter" value={categoryFilter} onChange={(event) => setCategoryFilter(event.target.value)}>
            <option value="all">全部类别</option>
            {[...new Map(frame.lanes.map((lane) => [lane.category.id, lane.category.name])).entries()].map(([id, name]) => <option key={id} value={id}>{categoryLabels.get(id) ?? name}</option>)}
          </select>
        </label>
        <label><span>位置属性</span>
          <select data-testid="openlane-attribute-filter" value={attributeFilter} onChange={(event) => setAttributeFilter(event.target.value)}>
            <option value="all">全部属性</option>
            {[...new Map(frame.lanes.map((lane) => [lane.attribute.id, lane.attribute.name])).entries()].map(([id, name]) => <option key={id} value={id}>{attributeLabels.get(id) ?? name}</option>)}
          </select>
        </label>
        <label className="swb-checkbox"><input data-testid="openlane-visible-filter" type="checkbox" checked={visibleOnly} onChange={(event) => setVisibleOnly(event.target.checked)} /><span>仅显示可见车道</span></label>
        <output data-testid="openlane-filter-count">当前显示 {lanes.length} 条</output>
      </fieldset>

      <section className="swb-lane-picker" aria-label="选择车道">
        <div className="swb-subheading"><strong>选择车道</strong><span>选择后将同步更新前视图、鸟瞰图和审核目标</span></div>
        <nav className="swb-lane-list" aria-label="OpenLane lanes">
          {lanes.map((lane) => (
            <button
              type="button"
              key={lane.laneRef}
              data-testid={`openlane-lane-${lane.trackId}`}
              data-lane-ref={lane.laneRef}
              aria-pressed={lane.laneRef === selected?.laneRef}
              aria-label={`选择车道 ${lane.trackId}：${lane.category.name}`}
              onClick={() => selectLane(lane.laneRef)}
            >
              <span>车道 {lane.trackId}</span>
              <small>{categoryLabels.get(lane.category.id) ?? lane.category.name}</small>
            </button>
          ))}
        </nav>
        <div className="swb-technical-ref"><span>当前引用</span><output data-testid="openlane-selection-status" aria-live="polite" aria-label="当前 OpenLane 选择">{selected?.laneRef ?? "none"}</output></div>
      </section>

      <div className="swb-openlane-views" data-testid="openlane-linked-views">
        <figure data-testid="openlane-2d-view">
          <figcaption><span>前视图与二维标注</span><small>图像像素坐标 · 黄色为选中车道</small></figcaption>
          <svg viewBox={imageUrl ? "0 0 1920 1280" : "0 0 480 320"} role="img" aria-label="OpenLane 2D lanes">
            {imageUrl ? <image data-testid="openlane-real-image" href={imageUrl} width="1920" height="1280" preserveAspectRatio="xMidYMid meet" /> : null}
            {lanes.map((lane) => (
              <polyline
                key={lane.lane2dRef}
                data-lane-ref={lane.laneRef}
                data-selected={lane.laneRef === selected?.laneRef}
                points={points2d(lane, imageUrl ? 1 : 4)}
                fill="none"
                stroke={lane.laneRef === selected?.laneRef ? "#fbbf24" : "#7dd3fc"}
                strokeWidth={lane.laneRef === selected?.laneRef ? 6 : 3}
                strokeOpacity={lane.laneRef === selected?.laneRef ? 1 : .72}
                vectorEffect="non-scaling-stroke"
              />
            ))}
          </svg>
          <output data-testid="openlane-2d-selected-ref" aria-label="二维视图稳定引用">{selected?.lane2dRef ?? "none"}</output>
        </figure>

        <figure data-testid="openlane-3d-view">
          <figcaption><span>三维车道鸟瞰</span><small>前方 {bev.maxForward} m · 横向 ±{bev.lateralExtent} m</small></figcaption>
          <svg viewBox={`0 0 ${BEV_WIDTH} ${BEV_HEIGHT}`} role="img" aria-label="OpenLane 3D lanes">
            <rect width={BEV_WIDTH} height={BEV_HEIGHT} fill="#081827" />
            {[.25, .5, .75].map((ratio) => <line key={`h-${ratio}`} x1={BEV_PADDING} y1={BEV_PADDING + (BEV_HEIGHT - BEV_PADDING * 2) * ratio} x2={BEV_WIDTH - BEV_PADDING} y2={BEV_PADDING + (BEV_HEIGHT - BEV_PADDING * 2) * ratio} stroke="#1e3448" />)}
            {[.25, .5, .75].map((ratio) => <line key={`v-${ratio}`} x1={BEV_PADDING + (BEV_WIDTH - BEV_PADDING * 2) * ratio} y1={BEV_PADDING} x2={BEV_PADDING + (BEV_WIDTH - BEV_PADDING * 2) * ratio} y2={BEV_HEIGHT - BEV_PADDING} stroke="#1e3448" />)}
            <text x="12" y="20" fill="#94a3b8" fontSize="11">前方 ↑</text>
            <text x="12" y={BEV_HEIGHT - 10} fill="#94a3b8" fontSize="11">右侧</text>
            <text x={BEV_WIDTH - 36} y={BEV_HEIGHT - 10} fill="#94a3b8" fontSize="11">左侧</text>
            <path d={`M${BEV_WIDTH / 2} ${BEV_HEIGHT - 19} l-7 12 h14z`} fill="#f8fafc" />
            {lanes.map((lane) => (
              <polyline
                key={lane.lane3dRef}
                data-lane-ref={lane.laneRef}
                data-selected={lane.laneRef === selected?.laneRef}
                points={bev.polyline(lane)}
                fill="none"
                stroke={lane.laneRef === selected?.laneRef ? "#fbbf24" : "#7dd3fc"}
                strokeWidth={lane.laneRef === selected?.laneRef ? 4 : 2}
                strokeOpacity={lane.laneRef === selected?.laneRef ? 1 : .62}
                vectorEffect="non-scaling-stroke"
              />
            ))}
            {selected?.points3d.map((point, index) => {
              const [cx, cy] = bev.project(point);
              return <circle key={`${selected.laneRef}-${index}`} cx={cx} cy={cy} r="3" fill="#fbbf24"><title>选中车道采样点 {index + 1}</title></circle>;
            })}
          </svg>
          <output data-testid="openlane-3d-selected-ref" aria-label="三维视图稳定引用">{selected?.lane3dRef ?? "none"}</output>
        </figure>
      </div>

      {selected ? (
        <section className="swb-lane-details" data-testid="openlane-lane-details" aria-label="当前车道详情">
          <header><strong>当前车道详情</strong><span>track {selected.trackId}</span></header>
          <dl>
            <div><dt>标线类别</dt><dd data-testid="openlane-category">{selected.category.id}: {selected.category.name}</dd></div>
            <div><dt>位置属性</dt><dd data-testid="openlane-attribute">{selected.attribute.id}: {selected.attribute.name}</dd></div>
            <div><dt>可见采样</dt><dd data-testid="openlane-visibility">{dataMode === "local" ? `${selected.visibility.filter((value) => value >= .75).length} / ${selected.visibility.length} 个点` : selected.visibility.join(", ")}</dd></div>
            <div><dt>三维长度</dt><dd>{laneLength(selected).toFixed(1)} m</dd></div>
          </dl>
          <details>
            <summary>查看坐标与稳定引用</summary>
            <dl className="swb-technical-details">
              <div><dt>稳定引用</dt><dd data-testid="openlane-selected-ref">{selected.laneRef}</dd></div>
              <div><dt>二维坐标</dt><dd data-testid="openlane-points-2d">{dataMode === "local" ? pointSummary(selected.points2d) : JSON.stringify(selected.points2d)}</dd></div>
              <div><dt>三维坐标</dt><dd data-testid="openlane-points-3d">{dataMode === "local" ? pointSummary(selected.points3d) : JSON.stringify(selected.points3d)}</dd></div>
            </dl>
          </details>
        </section>
      ) : <p className="swb-empty-view">当前筛选条件下没有可显示的车道标注。</p>}

      <aside data-testid="openlane-readonly-audit" data-unchanged={audit.unchanged}>
        <span data-testid="openlane-data-root-before">{audit.dataRootBeforeDigest}</span>
        <span data-testid="openlane-data-root-after">{audit.dataRootAfterDigest}</span>
        <span data-testid="openlane-media-included">{String(audit.mediaIncluded)}</span>
        <span data-testid="openlane-absolute-paths-included">{String(audit.absolutePathsIncluded)}</span>
      </aside>
    </section>
  );
}
