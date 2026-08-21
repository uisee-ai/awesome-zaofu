import type { ReactNode } from "react";

import type { FrameContextV1 } from "../contracts";
import type { InstanceSelectionV1 } from "../features/nuscenes";

export interface WorkbenchShellProps {
  readonly children: ReactNode;
  readonly frameContext: FrameContextV1 | null;
  readonly selection: InstanceSelectionV1 | null;
  readonly rightContent?: ReactNode;
  readonly localDataAvailable?: boolean;
  readonly localDataSource?: string;
}

const shellStyles = `
  .swb-shell { background: #0b1220; color: #e2e8f0; min-height: 100vh; padding: 24px; font-family: Inter, "Microsoft YaHei", sans-serif; }
  .swb-shell * { box-sizing: border-box; }
  .swb-shell h1, .swb-shell h2 { color: #f8fafc; }
  .swb-app-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 28px; margin-bottom: 20px; padding: 3px 2px 19px; border-bottom: 1px solid #27364e; }
  .swb-brand { max-width: 760px; }.swb-brand h1 { margin: 4px 0 7px; font-size: 1.8rem; letter-spacing: -.025em; }.swb-brand > p:last-child { max-width: 680px; margin: 0; color: #a9b9cd; line-height: 1.65; font-size: .92rem; }
  .swb-eyebrow { margin: 0; color: #7dd3fc; font-size: .67rem; font-weight: 750; letter-spacing: .14em; }
  .swb-header-status { display: grid; justify-items: end; gap: 8px; min-width: 280px; }.swb-header-status > p { margin: 0; color: #7f94aa; font-size: .74rem; }
  .swb-meta { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; margin: 0; }
  .swb-badge { background: #172554; border: 1px solid #334155; border-radius: 999px; padding: 5px 10px; }
  .swb-layout { display: grid; grid-template-columns: minmax(190px, 0.75fr) minmax(480px, 2.15fr) minmax(280px, 1.05fr); gap: 16px; }
  .swb-panel { background: #111c2e; border: 1px solid #27364e; border-radius: 10px; padding: 16px; min-width: 0; }
  .swb-panel-heading { margin-bottom: 14px; padding-bottom: 12px; border-bottom: 1px solid #24364c; }.swb-panel-heading h2 { margin: 3px 0 5px; font-size: 1.08rem; }.swb-panel-heading p:last-child { margin: 0; color: #91a4ba; line-height: 1.5; font-size: .78rem; }
  .swb-step-list { display: grid; gap: 9px; margin: 13px 0 16px; padding: 0; list-style: none; counter-reset: steps; }.swb-step-list li { display: grid; grid-template-columns: 24px 1fr; gap: 8px; align-items: start; color: #cbd5e1; line-height: 1.45; font-size: .78rem; counter-increment: steps; }.swb-step-list li::before { content: counter(steps); display: grid; place-items: center; width: 22px; height: 22px; color: #bae6fd; background: #16314e; border: 1px solid #31516f; border-radius: 50%; font-size: .7rem; font-weight: 700; }
  .swb-selection-card { padding: 10px; background: #0b1627; border: 1px solid #2b4058; border-radius: 7px; }.swb-selection-card strong { display: block; margin-bottom: 5px; color: #f1f5f9; font-size: .78rem; }.swb-selection-card output { margin: 0; font-size: .74rem; line-height: 1.5; overflow-wrap: anywhere; }
  .swb-panel output { display: block; margin: 8px 0; color: #bfdbfe; }
  .swb-panel > section { min-width: 0; }
  .swb-hint { display: none; border-left: 4px solid #fbbf24; background: #3a2b0b; padding: 12px; margin-bottom: 16px; }
  .swb-shell button, .swb-shell input, .swb-shell select { font: inherit; }
  .swb-shell button { display: inline-flex; align-items: center; justify-content: center; min-height: 34px; margin: 3px; padding: 6px 11px; color: #e2e8f0; background: #1e3a5f; border: 1px solid #475569; border-radius: 5px; line-height: 1.2; text-align: center; }
  .swb-shell button:hover { background: #285786; cursor: pointer; }
  .swb-shell button:focus-visible, .swb-shell input:focus-visible, .swb-shell select:focus-visible { outline: 2px solid #38bdf8; outline-offset: 2px; }
  .swb-action-row { display: flex; flex-wrap: wrap; align-items: center; gap: 7px; }.swb-action-row button { min-width: 84px; margin: 0; }
  .swb-timeline { margin: 12px 0; padding: 10px; border: 1px solid #334155; background: #0b1627; border-radius: 7px; }
  .swb-timeline p { margin: 6px 0 0; color: #94a3b8; font-size: .82rem; }
  .swb-timeline output { display: inline; margin-left: 10px; }
  .swb-empty-view { padding: 28px 12px; color: #94a3b8; border: 1px dashed #475569; border-radius: 8px; }
  .swb-multimodal { margin-top: 16px; }
  .swb-view-heading { display: flex; justify-content: space-between; gap: 12px; align-items: start; }
  .swb-view-heading h3 { margin: 0; }
  .swb-view-heading p { margin: 4px 0 10px; color: #94a3b8; font-size: .85rem; }
  .swb-object-chip { background: #134e4a; border: 1px solid #2dd4bf; border-radius: 999px; padding: 5px 9px; white-space: nowrap; font-size: .8rem; }
  .swb-camera-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
  .swb-camera-tile, .swb-spatial-view { margin: 0; border: 1px solid #334155; background: #091729; border-radius: 6px; overflow: hidden; }
  .swb-camera-tile figcaption, .swb-spatial-view figcaption { display: flex; justify-content: space-between; padding: 5px 7px; font-size: .76rem; color: #e2e8f0; }
  .swb-camera-tile small, .swb-spatial-view small { color: #94a3b8; font-size: .68rem; }
  .swb-camera-tile svg, .swb-spatial-view svg { display: block; width: 100%; height: auto; }
  .swb-camera-tile img { display: block; width: 100%; aspect-ratio: 16 / 9; object-fit: cover; }
  .swb-real-source { display: grid; grid-template-columns: auto auto minmax(0, 1fr); gap: 10px; align-items: center; margin-bottom: 10px; padding: 9px 11px; color: #dbeafe; background: #0b2a3c; border: 1px solid #0ea5e9; border-radius: 7px; }.swb-real-source strong { color: #86efac; }.swb-real-source label { display: flex; gap: 6px; align-items: center; }.swb-real-source select { color: #e2e8f0; background: #081422; border: 1px solid #475569; border-radius: 4px; padding: 4px; }.swb-real-source span { color: #94a3b8; font-size: .76rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .swb-openlane-source { grid-template-columns: auto minmax(0, 1fr); align-items: center; }.swb-openlane-source label { display: grid; grid-template-columns: auto minmax(0, 1fr); min-width: 0; }.swb-openlane-source select { min-width: 0; width: 100%; }.swb-openlane-source > span { grid-column: 1 / -1; white-space: normal; }
  .swb-spatial-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 10px; }
  .swb-projection-summary { grid-column: span 2; border: 1px solid #334155; border-left: 3px solid #38bdf8; background: #0d1b2d; border-radius: 6px; padding: 9px 12px; }
  .swb-projection-summary h4 { margin: 0; }.swb-projection-summary p { margin: 5px 0; color: #94a3b8; font-size: .78rem; }
  .swb-projection-summary dl { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; margin: 9px 0; }.swb-projection-summary dt { color: #94a3b8; font-size: .75rem; }.swb-projection-summary dd { margin: 0; font-size: 1.1rem; color: #e0f2fe; }
  .swb-muted { color: #94a3b8; font-size: .78rem; }
  .swb-dataset-module { margin-top: 22px; padding-top: 18px; border-top: 1px solid #334155; }.swb-module-heading { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; margin-bottom: 12px; }.swb-module-heading h3 { margin: 3px 0 5px; color: #f8fafc; font-size: 1.05rem; }.swb-module-heading p:last-child { max-width: 650px; margin: 0; color: #94a3b8; line-height: 1.55; font-size: .78rem; }.swb-status-badge { flex: 0 0 auto; padding: 5px 9px; color: #86efac; background: #12352e; border: 1px solid #237b63; border-radius: 999px; font-size: .72rem; }
  .swb-openlane { margin-top: 12px; }.swb-openlane-titlebar { display: flex; justify-content: space-between; gap: 14px; align-items: flex-start; }.swb-openlane-titlebar h4 { margin: 0 0 5px; color: #f8fafc; font-size: .95rem; }.swb-openlane-titlebar p { max-width: 650px; margin: 0; color: #9eb0c4; line-height: 1.5; font-size: .78rem; }.swb-openlane-titlebar > span { flex: 0 0 auto; padding: 4px 8px; color: #bae6fd; background: #10283f; border-radius: 999px; font-size: .72rem; }
  .swb-license-note { margin: 10px 0; padding: 8px 10px; color: #a7b8ca; background: #0c1929; border-left: 3px solid #64748b; line-height: 1.5; font-size: .73rem; }
  .swb-lane-filters { display: grid; grid-template-columns: minmax(130px, 1fr) minmax(130px, 1fr) auto auto; gap: 10px; align-items: end; margin: 12px 0; padding: 11px; border: 1px solid #334155; border-radius: 7px; }.swb-lane-filters legend { padding: 0 5px; color: #cbd5e1; font-size: .76rem; }.swb-lane-filters label { display: grid; gap: 5px; color: #b9c7d7; font-size: .74rem; }.swb-lane-filters select { min-height: 34px; width: 100%; color: #e2e8f0; background: #111f32; border: 1px solid #475569; border-radius: 5px; padding: 5px 8px; }.swb-lane-filters .swb-checkbox { display: flex; min-height: 34px; flex-direction: row; align-items: center; white-space: nowrap; }.swb-lane-filters output { display: flex; min-height: 34px; align-items: center; justify-content: center; margin: 0; padding: 0 9px; color: #bae6fd; background: #10283f; border-radius: 5px; font-size: .76rem; white-space: nowrap; }
  .swb-lane-picker { margin: 12px 0; }.swb-subheading { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; margin-bottom: 8px; }.swb-subheading strong { color: #f1f5f9; font-size: .82rem; }.swb-subheading span { color: #879bb1; font-size: .72rem; }.swb-lane-list { display: grid; grid-template-columns: repeat(auto-fit, minmax(128px, 1fr)); gap: 7px; }.swb-lane-list button { display: grid; justify-items: start; gap: 3px; width: 100%; min-height: 49px; margin: 0; padding: 7px 10px; text-align: left; }.swb-lane-list button span { color: #f1f5f9; font-size: .78rem; }.swb-lane-list button small { color: #9eb0c4; font-size: .68rem; }.swb-lane-list button[aria-pressed="true"] { background: #0e7490; border-color: #67e8f9; box-shadow: inset 3px 0 #fbbf24; }.swb-lane-list button[aria-pressed="true"] small { color: #ecfeff; }
  .swb-technical-ref { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 8px; margin-top: 8px; color: #8095aa; font-size: .69rem; }.swb-technical-ref output { margin: 0; color: #9ecaf0; overflow-wrap: anywhere; }
  .swb-openlane-views { display: grid; grid-template-columns: minmax(0, 1.4fr) minmax(250px, .6fr); gap: 10px; }.swb-openlane figure { min-width: 0; margin: 10px 0; overflow: hidden; }.swb-openlane figcaption { display: flex; justify-content: space-between; gap: 8px; margin-bottom: 6px; color: #dbeafe; font-size: .78rem; }.swb-openlane figcaption small { color: #879bb1; font-size: .68rem; text-align: right; }.swb-openlane svg { display: block; width: 100%; max-width: 100%; background: #0a1828; border: 1px solid #334155; border-radius: 5px; }.swb-openlane figure > output { margin: 6px 0 0; color: #7890a7; font-size: .65rem; overflow-wrap: anywhere; }
  .swb-lane-details { margin-top: 10px; padding: 12px; background: #0d1b2d; border: 1px solid #2b4058; border-radius: 7px; }.swb-lane-details > header { display: flex; justify-content: space-between; margin-bottom: 10px; }.swb-lane-details > header strong { color: #f1f5f9; font-size: .84rem; }.swb-lane-details > header span { color: #fbbf24; font-size: .74rem; }.swb-lane-details > dl { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; margin: 0; }.swb-lane-details dl > div { min-width: 0; padding: 8px; background: #091725; border-radius: 5px; }.swb-lane-details dt { color: #8398ad; font-size: .69rem; }.swb-lane-details dd { margin: 4px 0 0; color: #dbeafe; font-size: .76rem; overflow-wrap: anywhere; }.swb-lane-details details { margin-top: 10px; color: #94a3b8; font-size: .72rem; }.swb-lane-details summary { cursor: pointer; }.swb-technical-details { display: grid; gap: 6px; margin: 8px 0 0; }.swb-technical-details > div { display: grid; grid-template-columns: 80px minmax(0, 1fr); }.swb-openlane [data-testid="openlane-readonly-audit"] { display: none; }
  .swb-review-panel { display: grid; gap: 12px; margin-top: 10px; }.swb-review-panel h2, .swb-review-panel h3, .swb-review-panel p { margin: 0; }.swb-review-header { display: flex; align-items: start; justify-content: space-between; gap: 8px; }.swb-review-header h2 { font-size: 1.25rem; }.swb-review-eyebrow { color: #60a5fa; font-size: .62rem; font-weight: 700; letter-spacing: .11em; }.swb-review-revision { color: #bfdbfe; background: #172554; border: 1px solid #334155; border-radius: 999px; padding: 4px 7px; font-size: .72rem; white-space: nowrap; }
  .swb-review-context { display: grid; grid-template-columns: 72px minmax(0, 1fr); gap: 4px 8px; padding: 10px; background: #0b1627; border: 1px solid #263b55; border-radius: 8px; }.swb-review-context > span { color: #94a3b8; font-size: .73rem; }.swb-review-context output { margin: 0; color: #dbeafe; font-size: .75rem; line-height: 1.35; overflow-wrap: anywhere; }
  .swb-review-card, .swb-review-history-card, .swb-review-transfer { display: grid; gap: 9px; padding: 11px; background: #0d1b2d; border: 1px solid #263b55; border-radius: 8px; }.swb-review-card h3, .swb-review-history-card h3, .swb-review-transfer h3 { color: #f1f5f9; font-size: .9rem; }.swb-review-grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(100px, .65fr); align-items: end; gap: 8px; }.swb-review-field { display: grid; gap: 5px; min-width: 0; }.swb-review-field > span { color: #cbd5e1; font-size: .76rem; }.swb-review-field input, .swb-review-field select, .swb-review-field textarea { box-sizing: border-box; width: 100%; color: #e2e8f0; background: #081422; border: 1px solid #475569; border-radius: 5px; padding: 7px 8px; outline: none; }.swb-review-field input:focus, .swb-review-field select:focus, .swb-review-field textarea:focus { border-color: #38bdf8; box-shadow: 0 0 0 2px #0c4a6e; }.swb-review-field textarea { min-height: 68px; resize: vertical; font: .72rem ui-monospace, SFMono-Regular, Consolas, monospace; }.swb-review-panel button { width: fit-content; margin: 0; }.swb-review-primary { width: 100% !important; background: #0369a1 !important; border-color: #38bdf8 !important; }.swb-review-align-end { align-self: end; }.swb-review-panel button:disabled { cursor: wait; opacity: .65; }
  .swb-review-history-heading { display: flex; justify-content: space-between; align-items: center; gap: 8px; }.swb-review-history-heading output { display: inline-flex; margin: 0; color: #fde68a; font-size: .72rem; white-space: nowrap; }.swb-review-history-card ol { display: grid; gap: 7px; max-height: 145px; margin: 0; padding-left: 0; overflow: auto; list-style: none; }.swb-review-history-card li { display: grid; grid-template-columns: 30px minmax(0, 1fr); gap: 2px 7px; padding: 7px; background: #0a1727; border-left: 2px solid #38bdf8; border-radius: 3px; font-size: .74rem; }.swb-review-history-card li strong { color: #7dd3fc; }.swb-review-history-card li span { overflow-wrap: anywhere; }.swb-review-history-card li small { grid-column: 2; color: #94a3b8; overflow-wrap: anywhere; }.swb-review-transfer output, .swb-review-recovery { margin: 0; min-height: 1em; color: #86efac; font-size: .74rem; }
  @media (max-width: 1279px) { .swb-hint { display: block; } .swb-layout { grid-template-columns: 1fr; } }
  @media (max-width: 900px) { .swb-app-header { display: grid; }.swb-header-status { justify-items: start; min-width: 0; }.swb-meta { justify-content: flex-start; }.swb-openlane-views { grid-template-columns: 1fr; } }
  @media (max-width: 720px) { .swb-shell { padding: 14px; }.swb-camera-grid, .swb-spatial-grid, .swb-review-grid, .swb-lane-details > dl { grid-template-columns: 1fr; }.swb-lane-filters { grid-template-columns: 1fr; }.swb-projection-summary { grid-column: span 1; }.swb-projection-summary dl { grid-template-columns: 1fr 1fr; }.swb-review-align-end { justify-self: start; } }
`;

export function WorkbenchShell({ children, frameContext, selection, rightContent, localDataAvailable = false, localDataSource = "local-nuscenes" }: WorkbenchShellProps) {
  const frameRef = frameContext?.frameRef ?? "未选择";
  const instanceRef = selection?.stableInstanceRef ?? "未选择";
  const selectionStatus = selection
    ? `已选择帧 ${frameRef}，实例 ${instanceRef}`
    : `已选择帧 ${frameRef}，尚未选择实例`;

  return (
    <main className="swb-shell" data-testid="workbench-shell">
      <style>{shellStyles}</style>
      <header className="swb-app-header">
        <div className="swb-brand">
          <p className="swb-eyebrow">AUTONOMOUS DRIVING DATA REVIEW</p>
          <h1>Sensor Workbench</h1>
          <p>面向自动驾驶研发与数据质量审核的本地工作台，用于统一浏览多传感器帧、核对二维与三维标注，并记录可追溯的审核结论。</p>
        </div>
        <div className="swb-header-status">
          <div className="swb-meta" aria-label="数据模式与来源">
            <span className="swb-badge" data-testid="workbench-data-source">{localDataAvailable ? localDataSource : "synthetic-only"}</span>
            <span className="swb-badge" data-testid="workbench-readonly-status">只读</span>
          </div>
        </div>
      </header>
      <p className="swb-hint" data-testid="desktop-use-hint" role="status">
        建议使用 1280px 及以上的桌面屏幕，以获得完整三栏工作台体验。
      </p>
      <div className="swb-layout">
        <aside className="swb-panel" aria-label="数据与导航">
          <header className="swb-panel-heading"><p className="swb-eyebrow">NAVIGATION</p><h2>数据与导航</h2><p>按顺序选择数据、帧与标注对象，各视图将保持一致引用。</p></header>
          <ol className="swb-step-list"><li>选择 nuScenes 场景或 OpenLane 演示帧。</li><li>在主视图检查相机、点云、鸟瞰图和车道标注。</li><li>选择目标后，在右侧记录审核结论。</li></ol>
          <div className="swb-selection-card"><strong>当前选择</strong><output data-testid="workbench-selection-status" aria-live="polite">{selectionStatus}</output></div>
        </aside>
        <section className="swb-panel" aria-label="nuScenes 主视图">
          <header className="swb-panel-heading"><p className="swb-eyebrow">MULTIMODAL VIEW</p><h2>多模态数据浏览</h2><p>在同一工作区中核对 nuScenes 传感器帧与 OpenLane 车道几何关系。</p></header>
          {children}
        </section>
        <aside className="swb-panel" aria-label="详情与审核">
          <header className="swb-panel-heading"><p className="swb-eyebrow">REVIEW WORKSPACE</p><h2>详情与审核</h2><p>审核内容写入独立工作区，不会修改第三方原始标注。</p></header>
          <div className="swb-selection-card"><strong>审核上下文</strong><span className="swb-muted">当前帧</span><output data-testid="workbench-detail-frame">{frameRef}</output><span className="swb-muted">当前对象</span><output data-testid="workbench-detail-instance">{instanceRef}</output></div>
          {rightContent ?? <p>审核功能预留区：当前演示只读，不写入原始数据。</p>}
        </aside>
      </div>
    </main>
  );
}
