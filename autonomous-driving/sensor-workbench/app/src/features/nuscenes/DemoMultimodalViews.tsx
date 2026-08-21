import type { FrameContextV1 } from "../../contracts";

export interface DemoPoint {
  readonly x: number;
  readonly y: number;
  readonly z: number;
  readonly intensity: number;
}

export interface DemoFrameVisual {
  readonly frameRef: string;
  readonly sequence: number;
  readonly location: string;
  readonly timeLabel: string;
  readonly object: {
    readonly stableInstanceRef: string;
    readonly category: string;
    readonly velocityMps: number;
    readonly x: number;
    readonly y: number;
    readonly headingDeg: number;
  };
  readonly points: readonly DemoPoint[];
}

export interface ProjectionSummary {
  readonly projected: number;
  readonly behindCamera: number;
  readonly outsideImage: number;
  readonly distanceFiltered: number;
}

const CAMERA_CHANNELS = [
  { id: "CAM_FRONT", label: "前视" },
  { id: "CAM_FRONT_RIGHT", label: "前右" },
  { id: "CAM_BACK_RIGHT", label: "后右" },
  { id: "CAM_BACK", label: "后视" },
  { id: "CAM_BACK_LEFT", label: "后左" },
  { id: "CAM_FRONT_LEFT", label: "前左" },
] as const;

function cameraBox(sequence: number, cameraIndex: number) {
  const frontBias = cameraIndex === 0 ? 1 : cameraIndex === 5 ? 0.75 : cameraIndex === 1 ? 0.55 : 0.28;
  return {
    x: 122 + Math.round(frontBias * 76) + sequence * 9,
    y: 80 + Math.round((cameraIndex % 3) * 7),
    width: 44,
    height: 34,
    visible: cameraIndex !== 3 || sequence % 3 !== 1,
  };
}

function project(point: DemoPoint): "projected" | "behind" | "outside" | "filtered" {
  if (point.z <= 0) return "behind";
  if (point.z > 38 || Math.hypot(point.x, point.y) > 36) return "filtered";
  const u = 160 + (point.x / point.z) * 165;
  const v = 94 - (point.y / point.z) * 165;
  return u < 0 || u > 320 || v < 0 || v > 180 ? "outside" : "projected";
}

export function summariseProjection(points: readonly DemoPoint[]): ProjectionSummary {
  return points.reduce<ProjectionSummary>((summary, point) => {
    const result = project(point);
    if (result === "projected") return { ...summary, projected: summary.projected + 1 };
    if (result === "behind") return { ...summary, behindCamera: summary.behindCamera + 1 };
    if (result === "outside") return { ...summary, outsideImage: summary.outsideImage + 1 };
    return { ...summary, distanceFiltered: summary.distanceFiltered + 1 };
  }, { projected: 0, behindCamera: 0, outsideImage: 0, distanceFiltered: 0 });
}

function CameraTile({
  channel,
  frame,
  selected,
  index,
}: {
  readonly channel: (typeof CAMERA_CHANNELS)[number];
  readonly frame: DemoFrameVisual;
  readonly selected: boolean;
  readonly index: number;
}) {
  const box = cameraBox(frame.sequence, index);
  const horizon = 63 + index % 2 * 4;
  const projected = frame.points.filter((point) => project(point) === "projected").slice(index * 4, index * 4 + 13);
  return (
    <figure className="swb-camera-tile" data-testid={`camera-view-${channel.id}`}>
      <figcaption><span>{channel.label}</span><small>{channel.id}</small></figcaption>
      <svg viewBox="0 0 320 180" role="img" aria-label={`${channel.label}合成摄像头画面`}>
        <defs>
          <linearGradient id={`sky-${channel.id}`} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0" stopColor="#304867" />
            <stop offset="1" stopColor="#93b9cd" />
          </linearGradient>
        </defs>
        <rect width="320" height={horizon} fill={`url(#sky-${channel.id})`} />
        <rect y={horizon} width="320" height={180 - horizon} fill="#263b3b" />
        <path d={`M132 ${horizon} L58 180 H262 L188 ${horizon}Z`} fill="#34424b" />
        <path d={`M157 ${horizon + 6} L152 180 M164 ${horizon + 6} L169 180`} stroke="#f6d365" strokeDasharray="11 9" strokeWidth="2" />
        {projected.map((point, pointIndex) => {
          const u = 160 + (point.x / point.z) * 165;
          const v = 94 - (point.y / point.z) * 165;
          return <circle key={pointIndex} cx={u} cy={v} r="1.4" fill="#7dd3fc" opacity=".72" />;
        })}
        {box.visible ? <>
          <rect
            x={box.x}
            y={box.y}
            width={box.width}
            height={box.height}
            fill="none"
            stroke={selected ? "#fbbf24" : "#38bdf8"}
            strokeWidth={selected ? 3 : 2}
            data-testid={`camera-box-${channel.id}`}
          />
          <text x={box.x} y={box.y - 5} fill="#f8fafc" fontSize="10">vehicle-01</text>
        </> : <text x="112" y="104" fill="#cbd5e1" fontSize="11">目标当前不可见</text>}
        <text x="8" y="168" fill="#e2e8f0" fontSize="10">synthetic · frame {frame.sequence + 1}</text>
      </svg>
    </figure>
  );
}

function PointCloudView({ frame, selected }: { readonly frame: DemoFrameVisual; readonly selected: boolean }) {
  return (
    <figure className="swb-spatial-view" data-testid="lidar-view">
      <figcaption>LiDAR 点云 <small>{frame.points.length} 点 · LOD 2</small></figcaption>
      <svg viewBox="0 0 420 250" role="img" aria-label="合成 LiDAR 点云">
        <rect width="420" height="250" fill="#071421" />
        {frame.points.map((point, index) => (
          <circle key={index} cx={210 + point.x * 7} cy={220 - point.z * 4.8 - point.y * 1.5} r={point.intensity > .75 ? 1.8 : 1.1} fill={point.intensity > .75 ? "#fbbf24" : "#60a5fa"} opacity=".75" />
        ))}
        <rect x={210 + frame.object.x * 7 - 21} y={220 - frame.object.y * 4.8 - 52} width="42" height="52" fill="none" stroke={selected ? "#fbbf24" : "#38bdf8"} strokeWidth={selected ? 3 : 2} />
        <text x="10" y="20" fill="#bae6fd" fontSize="11">LIDAR_TOP · x 前方 / z 上方</text>
      </svg>
    </figure>
  );
}

function BevView({ frame, selected }: { readonly frame: DemoFrameVisual; readonly selected: boolean }) {
  return (
    <figure className="swb-spatial-view" data-testid="bev-view">
      <figcaption>BEV 鸟瞰 <small>无 HD 地图</small></figcaption>
      <svg viewBox="0 0 420 250" role="img" aria-label="合成 BEV 鸟瞰图">
        <rect width="420" height="250" fill="#081827" />
        {[70, 140, 210, 280, 350].map((x) => <line key={x} x1={x} y1="20" x2={x} y2="230" stroke="#1e3a4d" />)}
        {[40, 90, 140, 190, 230].map((y) => <line key={y} x1="30" y1={y} x2="390" y2={y} stroke="#1e3a4d" />)}
        <path d="M176 230 L186 20 M244 230 L234 20" stroke="#cbd5e1" strokeDasharray="12 8" opacity=".7" />
        {frame.points.filter((_, index) => index % 3 === 0).map((point, index) => (
          <circle key={index} cx={210 + point.x * 6} cy={220 - point.z * 5.5} r="1.2" fill="#38bdf8" opacity=".62" />
        ))}
        <g transform={`translate(${210 + frame.object.x * 6} ${220 - frame.object.y * 5.5}) rotate(${-frame.object.headingDeg})`}>
          <rect x="-14" y="-28" width="28" height="56" rx="3" fill="#0f766e" stroke={selected ? "#fbbf24" : "#5eead4"} strokeWidth={selected ? 3 : 2} />
          <path d="M0 -22 L-8 -10 H8Z" fill="#ccfbf1" />
        </g>
        <text x="10" y="20" fill="#bae6fd" fontSize="11">车体坐标系 · x 前方 / y 左方</text>
      </svg>
    </figure>
  );
}

export interface DemoMultimodalViewsProps {
  readonly frame: DemoFrameVisual | null;
  readonly context: FrameContextV1 | null;
  readonly selectedInstanceRef: string | null;
}

export function DemoMultimodalViews({ frame, context, selectedInstanceRef }: DemoMultimodalViewsProps) {
  if (!frame || !context) {
    return <p className="swb-empty-view" data-testid="multimodal-empty">选择一个 keyframe 以加载合成相机、点云和 BEV 视图。</p>;
  }
  const selected = selectedInstanceRef === frame.object.stableInstanceRef;
  const projection = summariseProjection(frame.points);
  return (
    <section className="swb-multimodal" data-testid="multimodal-views" data-frame-context-id={context.frameContextId}>
      <header className="swb-view-heading">
        <div><h3>多模态帧 {frame.sequence + 1} / 6</h3><p>{frame.location} · {frame.timeLabel} · 合成演示数据</p></div>
        <div className="swb-object-chip" data-testid="selected-object-summary">{frame.object.category} · {frame.object.velocityMps.toFixed(1)} m/s</div>
      </header>
      <div className="swb-camera-grid">
        {CAMERA_CHANNELS.map((channel, index) => <CameraTile key={channel.id} channel={channel} frame={frame} selected={selected} index={index} />)}
      </div>
      <div className="swb-spatial-grid">
        <PointCloudView frame={frame} selected={selected} />
        <BevView frame={frame} selected={selected} />
        <aside className="swb-projection-summary" data-testid="projection-summary">
          <h4>LiDAR → CAM_FRONT 投影</h4>
          <p>坐标链：LiDAR → ego → global → camera ego → camera</p>
          <dl>
            <dt>有效投影</dt><dd data-testid="projection-valid-count">{projection.projected}</dd>
            <dt>相机后方</dt><dd>{projection.behindCamera}</dd>
            <dt>图像范围外</dt><dd>{projection.outsideImage}</dd>
            <dt>距离过滤</dt><dd>{projection.distanceFiltered}</dd>
          </dl>
          <p className="swb-muted">黄金数值测试覆盖转换与投影；此处展示当前合成帧的可解释统计。</p>
        </aside>
      </div>
    </section>
  );
}
