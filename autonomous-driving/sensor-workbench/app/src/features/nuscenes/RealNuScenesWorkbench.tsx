import { useEffect, useMemo, useState } from "react";

import { FRAME_CONTEXT_VERSION, type FrameContextV1 } from "../../contracts";

interface CameraFrame { readonly sensorId: string; readonly timestampUs: number; readonly assetUrl: string }
interface Transform { readonly translation: readonly number[]; readonly rotation: readonly number[] }
interface Annotation { readonly annotationRef: string; readonly instanceRef: string; readonly category: string; readonly translation: readonly number[]; readonly size: readonly number[]; readonly rotation: readonly number[]; readonly numLidarPoints: number }
interface RealFrame { readonly frameRef: string; readonly timestampUs: number; readonly cameras: readonly CameraFrame[]; readonly lidar: null | { readonly timestampUs: number; readonly assetUrl: string | null; readonly calibration: Transform; readonly egoPose: Transform }; readonly annotations: readonly Annotation[] }
interface RealScene { readonly sceneRef: string; readonly description: string; readonly frames: readonly RealFrame[] }
interface Manifest { readonly schemaVersion: "local-nuscenes-workbench.v1"; readonly datasetVersion: "v1.0-mini"; readonly scenes: readonly RealScene[] }
interface Point { readonly x: number; readonly y: number; readonly z: number; readonly intensity: number }

function isManifest(value: unknown): value is Manifest {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<Manifest>;
  return candidate.schemaVersion === "local-nuscenes-workbench.v1"
    && candidate.datasetVersion === "v1.0-mini"
    && Array.isArray(candidate.scenes)
    && candidate.scenes.some((scene) => Array.isArray(scene.frames) && scene.frames.length > 0);
}

const CAMERA_NAMES = new Map([["CAM_FRONT", "前视"], ["CAM_FRONT_RIGHT", "前右"], ["CAM_BACK_RIGHT", "后右"], ["CAM_BACK", "后视"], ["CAM_BACK_LEFT", "后左"], ["CAM_FRONT_LEFT", "前左"]]);
function rotate(vector: readonly number[], quaternion: readonly number[]): [number, number, number] {
  const [w, x, y, z] = quaternion; const [vx, vy, vz] = vector;
  const tx = 2 * (y * vz - z * vy); const ty = 2 * (z * vx - x * vz); const tz = 2 * (x * vy - y * vx);
  return [vx + w * tx + (y * tz - z * ty), vy + w * ty + (z * tx - x * tz), vz + w * tz + (x * ty - y * tx)];
}
function inverse(quaternion: readonly number[]) { return [quaternion[0]!, -quaternion[1]!, -quaternion[2]!, -quaternion[3]!]; }
function multiply(a: readonly number[], b: readonly number[]) {
  return [a[0]! * b[0]! - a[1]! * b[1]! - a[2]! * b[2]! - a[3]! * b[3]!, a[0]! * b[1]! + a[1]! * b[0]! + a[2]! * b[3]! - a[3]! * b[2]!, a[0]! * b[2]! - a[1]! * b[3]! + a[2]! * b[0]! + a[3]! * b[1]!, a[0]! * b[3]! + a[1]! * b[2]! - a[2]! * b[1]! + a[3]! * b[0]!];
}
function yaw(quaternion: readonly number[]) { return Math.atan2(2 * (quaternion[0]! * quaternion[3]! + quaternion[1]! * quaternion[2]!), 1 - 2 * (quaternion[2]! ** 2 + quaternion[3]! ** 2)) * 180 / Math.PI; }
function globalToEgo(position: readonly number[], ego: Transform) { return rotate(position.map((value, index) => value - ego.translation[index]!), inverse(ego.rotation)); }
function lidarToEgo(point: Point, calibration: Transform): Point { const next = rotate([point.x, point.y, point.z], calibration.rotation); return { x: next[0] + calibration.translation[0]!, y: next[1] + calibration.translation[1]!, z: next[2] + calibration.translation[2]!, intensity: point.intensity }; }

function RealSpatialViews({ frame, points }: { readonly frame: RealFrame; readonly points: readonly Point[] }) {
  const lidar = frame.lidar;
  const egoPoints = useMemo(() => lidar ? points.map((point) => lidarToEgo(point, lidar.calibration)) : [], [lidar, points]);
  const boxes = useMemo(() => lidar ? frame.annotations.map((annotation) => ({ annotation, center: globalToEgo(annotation.translation, lidar.egoPose), angle: yaw(multiply(inverse(lidar.egoPose.rotation), annotation.rotation)) })).filter(({ center }) => Math.abs(center[0]) < 50 && Math.abs(center[1]) < 50) : [], [frame.annotations, lidar]);
  return <div className="swb-spatial-grid">
    <figure className="swb-spatial-view" data-testid="lidar-view">
      <figcaption>LiDAR 点云 <small>真实 LIDAR_TOP · {points.length} 个抽样点</small></figcaption>
      <svg viewBox="0 0 420 250" role="img" aria-label="真实 LiDAR 点云侧视图"><rect width="420" height="250" fill="#071421" />
        {points.map((point, index) => <circle key={index} cx={40 + Math.max(-5, Math.min(55, point.x)) * 6.5} cy={195 - point.z * 15} r={point.intensity > 50 ? 1.35 : .8} fill={point.intensity > 50 ? "#fbbf24" : "#60a5fa"} opacity=".72" />)}
        <text x="10" y="20" fill="#bae6fd" fontSize="11">真实传感器坐标 · x 前方 / z 上方</text>
      </svg>
    </figure>
    <figure className="swb-spatial-view" data-testid="bev-view">
      <figcaption>BEV 鸟瞰 <small>{boxes.length} 个当前范围内真实 3D 标注</small></figcaption>
      <svg viewBox="0 0 420 250" role="img" aria-label="真实 BEV 鸟瞰图"><rect width="420" height="250" fill="#081827" />
        {[70, 140, 210, 280, 350].map((x) => <line key={x} x1={x} y1="10" x2={x} y2="240" stroke="#1e3a4d" />)}
        {[25, 75, 125, 175, 225].map((y) => <line key={y} x1="10" y1={y} x2="410" y2={y} stroke="#1e3a4d" />)}
        {egoPoints.filter((point, index) => index % 2 === 0 && Math.abs(point.x) < 50 && Math.abs(point.y) < 50).map((point, index) => <circle key={index} cx={210 - point.y * 4} cy={220 - point.x * 4} r=".65" fill="#38bdf8" opacity=".5" />)}
        {boxes.map(({ annotation, center, angle }) => <g key={annotation.annotationRef} transform={`translate(${210 - center[1] * 4} ${220 - center[0] * 4}) rotate(${-angle})`}><rect x={-annotation.size[0]! * 2} y={-annotation.size[1]! * 2} width={annotation.size[0]! * 4} height={annotation.size[1]! * 4} fill="#0f766e55" stroke="#fbbf24" strokeWidth="1.4" /><title>{annotation.category}</title></g>)}
        <path d="M210 218 l-7 14 h14z" fill="#f8fafc" /><text x="10" y="20" fill="#bae6fd" fontSize="11">真实 ego 坐标 · 相机、点云、标注同帧</text>
      </svg>
    </figure>
    <aside className="swb-projection-summary" data-testid="projection-summary"><h4>真实帧同步状态</h4><p>同一个 sample_token 驱动六路相机、LIDAR_TOP、ego pose 与 sample_annotation。</p><dl><dt>相机</dt><dd data-testid="real-camera-count">{frame.cameras.length}</dd><dt>点云抽样</dt><dd data-testid="real-point-count">{points.length}</dd><dt>全部标注</dt><dd data-testid="real-annotation-count">{frame.annotations.length}</dd><dt>BEV 范围内</dt><dd data-testid="real-bev-annotation-count">{boxes.length}</dd></dl></aside>
  </div>;
}

export interface RealNuScenesWorkbenchProps { readonly onAvailabilityChange: (available: boolean) => void; readonly onFrameContextChange?: (context: FrameContextV1) => void }
export function RealNuScenesWorkbench({ onAvailabilityChange, onFrameContextChange }: RealNuScenesWorkbenchProps) {
  const [manifest, setManifest] = useState<Manifest | null>(null); const [sceneIndex, setSceneIndex] = useState(0); const [frameIndex, setFrameIndex] = useState(0); const [playing, setPlaying] = useState(false); const [points, setPoints] = useState<readonly Point[]>([]);
  useEffect(() => { const controller = new AbortController(); void fetch("/local-nuscenes/manifest", { signal: controller.signal }).then((response) => response.ok ? response.json() as Promise<unknown> : Promise.reject(new TypeError("local nuScenes manifest unavailable"))).then((result) => { if (!isManifest(result)) throw new TypeError("invalid local nuScenes manifest"); setManifest(result); onAvailabilityChange(true); }).catch(() => onAvailabilityChange(false)); return () => controller.abort(); }, [onAvailabilityChange]);
  const scene = manifest?.scenes[sceneIndex] ?? null; const frame = scene?.frames[frameIndex] ?? null;
  useEffect(() => { if (!playing || !scene || scene.frames.length < 2) return; const timer = globalThis.setInterval(() => setFrameIndex((index) => (index + 1) % scene.frames.length), 900); return () => globalThis.clearInterval(timer); }, [playing, scene]);
  useEffect(() => {
    if (!frame || !scene) return; const sensors = [...frame.cameras.map((camera) => ({ sensorId: camera.sensorId, modality: "camera" as const, timestampUs: camera.timestampUs, deltaMs: (camera.timestampUs - frame.timestampUs) / 1000, availability: "available" as const, assetRef: camera.assetUrl })), ...(frame.lidar ? [{ sensorId: "LIDAR_TOP", modality: "lidar" as const, timestampUs: frame.lidar.timestampUs, deltaMs: (frame.lidar.timestampUs - frame.timestampUs) / 1000, availability: frame.lidar.assetUrl ? "available" as const : "missing" as const, assetRef: frame.lidar.assetUrl }] : [])];
    onFrameContextChange?.({ schemaVersion: FRAME_CONTEXT_VERSION, frameContextId: `${scene.sceneRef}:${frame.frameRef}:real`, generation: frameIndex + 1, adapterId: "nuscenes-local-v1", datasetKind: "nuscenes", datasetVersion: "v1.0-mini", sceneRef: scene.sceneRef, frameRef: frame.frameRef, keyframe: true, timestampUs: frame.timestampUs, primarySensorId: "LIDAR_TOP", coordinateFrame: "ego", sensorFrames: sensors });
  }, [frame, frameIndex, onFrameContextChange, scene]);
  useEffect(() => { const controller = new AbortController(); setPoints([]); if (!frame?.lidar?.assetUrl) return () => controller.abort(); void fetch(frame.lidar.assetUrl, { signal: controller.signal }).then((response) => response.arrayBuffer()).then((buffer) => { const values = new Float32Array(buffer); const total = Math.floor(values.length / 5); const step = Math.max(1, Math.ceil(total / 3200)); const next: Point[] = []; for (let i = 0; i + 4 < values.length; i += 5 * step) next.push({ x: values[i]!, y: values[i + 1]!, z: values[i + 2]!, intensity: values[i + 3]! }); setPoints(next); }).catch(() => undefined); return () => controller.abort(); }, [frame]);
  if (!manifest || !scene || !frame) return null;
  const move = (offset: number) => setFrameIndex((index) => (index + offset + scene.frames.length) % scene.frames.length);
  return <section data-testid="real-nuscenes-panel" aria-label="真实 nuScenes keyframe workbench">
    <div className="swb-real-source"><strong>真实 nuScenes v1.0-mini</strong><label>场景 <select value={sceneIndex} onChange={(event) => { setSceneIndex(Number(event.target.value)); setFrameIndex(0); }}>{manifest.scenes.map((item, index) => <option key={item.sceneRef} value={index}>{item.sceneRef}</option>)}</select></label><span>{scene.description}</span></div>
    <section className="swb-timeline" data-testid="timeline-controls"><div><button type="button" onClick={() => move(-1)}>上一帧</button><button type="button" aria-label={playing ? "暂停播放" : "播放时间轴"} onClick={() => setPlaying((value) => !value)}>{playing ? "暂停" : "播放"}</button><button type="button" onClick={() => move(1)}>下一帧</button></div><output data-testid="timeline-position">{frameIndex + 1} / {scene.frames.length}</output><p>真实 sample_token · 以 LIDAR_TOP 为基准同步六路相机、点云和 BEV</p></section>
    <section className="swb-multimodal" data-testid="multimodal-views" data-frame-context-id={`${scene.sceneRef}:${frame.frameRef}:real`}><header className="swb-view-heading"><div><h3>多模态帧 {frameIndex + 1} / {scene.frames.length}</h3><p>{new Date(frame.timestampUs / 1000).toLocaleString("zh-CN", { hour12: false })} · 真实数据</p></div><div className="swb-object-chip">{frame.annotations.length} 个真实标注</div></header>
      <div className="swb-camera-grid">{frame.cameras.map((camera) => <figure className="swb-camera-tile" key={camera.sensorId} data-testid={`camera-view-${camera.sensorId}`}><figcaption><span>{CAMERA_NAMES.get(camera.sensorId) ?? camera.sensorId}</span><small>{camera.sensorId}</small></figcaption><img src={camera.assetUrl} alt={`${camera.sensorId} 真实画面`} /></figure>)}</div>
      <RealSpatialViews frame={frame} points={points} />
    </section>
  </section>;
}
