"use client";

import {
  Activity,
  Beaker,
  Camera,
  Check,
  ChevronRight,
  CircleAlert,
  FlaskConical,
  Gauge,
  ImagePlus,
  Layers3,
  LoaderCircle,
  MessageSquareText,
  Play,
  RefreshCw,
  Route,
  ScanSearch,
  Tag,
  X,
  type LucideIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { BevTrajectoryVisualization } from "../../web/src/features/trajectory/bev-trajectory-visualization";
import {
  createStudioApi,
  type DemoId,
  type InferenceResult,
  type StudioRun,
  type StudioScene,
  waitForTerminalRun,
} from "../lib/studio-api";

const api = createStudioApi();

const DEMOS: Array<{ id: DemoId; label: string; shortLabel: string; icon: LucideIcon }> = [
  { id: "workbench", label: "Scene Workbench", shortLabel: "Workbench", icon: Gauge },
  { id: "navigation", label: "Navigation Lab", shortLabel: "Navigation", icon: Route },
  { id: "ablation", label: "Camera Ablation", shortLabel: "Ablation", icon: Camera },
  { id: "vqa", label: "Scene VQA", shortLabel: "VQA", icon: MessageSquareText },
  { id: "auto-label", label: "Auto Label Studio", shortLabel: "Auto Label", icon: Tag },
  { id: "regression-judge", label: "Regression & Judge", shortLabel: "Regression", icon: Beaker },
];

const CAMERA_NAMES: Record<number, string> = {
  0: "Front Left",
  1: "Front",
  2: "Front Right",
  3: "Rear Left",
  4: "Rear",
  5: "Rear Right",
  6: "Front Telephoto",
};

function trajectoryPath(points: Array<{ x: number; y: number }>, width: number, height: number): string {
  if (!points.length) return "";
  const maxX = Math.max(...points.map((point) => point.x), 1);
  const minY = Math.min(...points.map((point) => point.y), -1);
  const maxY = Math.max(...points.map((point) => point.y), 1);
  const ySpan = Math.max(maxY - minY, 2);
  return points
    .map((point, index) => {
      const x = 34 + (point.x / maxX) * (width - 68);
      const y = height - 28 - ((point.y - minY) / ySpan) * (height - 56);
      return `${index === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
}

function TrajectoryPlot({ result }: { result: InferenceResult }) {
  const width = 620;
  const height = 250;
  const visualization = new BevTrajectoryVisualization({
    baseline: { runId: result.responseSha256, trajectory: result.trajectory },
  }).snapshot();
  const path = trajectoryPath(visualization.baseline.points, width, height);
  return (
    <div className="trajectory-wrap" data-testid="trajectory-plot">
      <div className="section-title-row">
        <div>
          <span className="section-kicker">BEV prediction</span>
          <h3>Future trajectory</h3>
        </div>
        <span className="mono-caption">64 points / 6.4 s</span>
      </div>
      <svg
        aria-label="Predicted bird's-eye-view trajectory"
        className="trajectory-canvas"
        role="img"
        viewBox={`0 0 ${width} ${height}`}
      >
        <rect className="bev-road" height={height - 24} width={width - 24} x="12" y="12" />
        {[1, 2, 3, 4].map((line) => (
          <line
            className="bev-grid"
            key={line}
            x1={line * (width / 5)}
            x2={line * (width / 5)}
            y1="12"
            y2={height - 12}
          />
        ))}
        <line className="bev-center" x1="12" x2={width - 12} y1={height / 2} y2={height / 2} />
        <path className="trajectory-shadow" d={path} />
        <path className="trajectory-line" d={path} data-testid="trajectory-path" />
        <circle className="ego-marker" cx="34" cy={height - 28} r="7" />
      </svg>
    </div>
  );
}

function EmptyResult() {
  return (
    <div className="empty-result">
      <ScanSearch aria-hidden="true" size={24} />
      <strong>No inference selected</strong>
      <span>Run the active demo or select a previous result.</span>
    </div>
  );
}

function summarizeParameters(parameters: Record<string, unknown> | undefined): string {
  if (!parameters || Object.keys(parameters).length === 0) return "Default";
  if (Array.isArray(parameters.cameraIds)) return `Cameras ${parameters.cameraIds.join(", ")}`;
  if (typeof parameters.navigationInstruction === "string") return parameters.navigationInstruction;
  if (typeof parameters.question === "string") return parameters.question;
  if (typeof parameters.suiteSize === "number") return `${parameters.suiteSize}-scene suite`;
  return Object.keys(parameters).sort().join(", ");
}

export default function StudioPage() {
  const [scenes, setScenes] = useState<StudioScene[]>([]);
  const [selectedSceneId, setSelectedSceneId] = useState("");
  const [demo, setDemo] = useState<DemoId>("workbench");
  const [run, setRun] = useState<StudioRun | null>(null);
  const [history, setHistory] = useState<StudioRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [creatingScene, setCreatingScene] = useState(false);
  const [error, setError] = useState("");
  const [providerStatus, setProviderStatus] = useState("checking");
  const [timelineIndex, setTimelineIndex] = useState(3);
  const [question, setQuestion] = useState("What is the safest near-term action?");
  const [navigationInstruction, setNavigationInstruction] = useState("Continue straight and prepare for traffic ahead");
  const [selectedCameras, setSelectedCameras] = useState([0, 1, 2, 6]);

  const selectedScene = scenes.find((scene) => scene.sceneId === selectedSceneId) ?? null;
  const activeDemo = DEMOS.find((item) => item.id === demo) ?? DEMOS[0];
  const result = run?.status === "completed" ? run.result : undefined;
  const sceneCameras = useMemo(
    () => [...(selectedScene?.sceneVersion.cameras ?? [])].sort((left, right) => left.cameraId - right.cameraId),
    [selectedScene],
  );
  const frameCount = Math.max(...sceneCameras.map((camera) => camera.frames.length), 1);

  const loadRuns = useCallback(async (sceneId: string) => {
    const runs = await api.listRuns(sceneId);
    setHistory(runs);
    const latestCompleted = runs.find((item) => item.status === "completed");
    setRun(latestCompleted ?? runs[0] ?? null);
  }, []);

  const selectScene = useCallback((scene: StudioScene) => {
    setSelectedSceneId(scene.sceneId);
    setSelectedCameras(scene.sceneVersion.cameras.map((camera) => camera.cameraId).sort((left, right) => left - right));
    setTimelineIndex(Math.min(3, Math.max(scene.sceneVersion.cameras[0]?.frames.length ?? 1, 1) - 1));
    void loadRuns(scene.sceneId);
  }, [loadRuns]);

  const loadStudio = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [loadedScenes, health] = await Promise.all([api.listScenes(), api.health()]);
      setScenes(loadedScenes);
      setProviderStatus(health.services.provider ?? health.status);
      const sceneId = selectedSceneId || loadedScenes[0]?.sceneId || "";
      setSelectedSceneId(sceneId);
      const initialScene = loadedScenes.find((scene) => scene.sceneId === sceneId);
      if (initialScene) {
        setSelectedCameras(initialScene.sceneVersion.cameras.map((camera) => camera.cameraId).sort((left, right) => left - right));
        setTimelineIndex(Math.min(3, Math.max(initialScene.sceneVersion.cameras[0]?.frames.length ?? 1, 1) - 1));
        await loadRuns(sceneId);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Studio could not be loaded.");
    } finally {
      setLoading(false);
    }
  }, [loadRuns, selectedSceneId]);

  useEffect(() => {
    void loadStudio();
  }, []); // The initial load must not repeat when selection changes.

  const createScene = async () => {
    setCreatingScene(true);
    setError("");
    try {
      const scene = await api.createDemoScene(`Golden road ${scenes.length + 1}`);
      setScenes((current) => [scene, ...current]);
      setSelectedSceneId(scene.sceneId);
      setSelectedCameras(scene.sceneVersion.cameras.map((camera) => camera.cameraId).sort((left, right) => left - right));
      setTimelineIndex(Math.min(3, Math.max(scene.sceneVersion.cameras[0]?.frames.length ?? 1, 1) - 1));
      setHistory([]);
      setRun(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Scene creation failed.");
    } finally {
      setCreatingScene(false);
    }
  };

  const runParameters = useMemo<Record<string, unknown>>(() => {
    if (demo === "vqa") return { question };
    if (demo === "navigation") return { navigationInstruction };
    if (demo === "ablation") return { cameraIds: selectedCameras };
    if (demo === "auto-label") return { labelPolicy: "research-review-required" };
    if (demo === "regression-judge") return { suiteSize: 10, continueOnFailure: true };
    return {};
  }, [demo, navigationInstruction, question, selectedCameras]);

  const submitInference = async () => {
    if (!selectedScene) return;
    setRunning(true);
    setError("");
    try {
      const submitted = await api.submitRun(selectedScene.sceneId, demo, runParameters);
      setRun(submitted);
      const completed = await waitForTerminalRun(api.readRun, submitted.runId, { onUpdate: setRun });
      setRun(completed);
      setHistory((current) => [completed, ...current.filter((item) => item.runId !== completed.runId)]);
      if (completed.status === "failed") {
        setError(completed.error?.message ?? "Inference failed.");
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Inference failed.");
    } finally {
      setRunning(false);
    }
  };

  const saveReview = async (decision: "accepted" | "rejected") => {
    if (!run) return;
    setError("");
    try {
      await api.reviewRun(run.runId, decision, "Reviewed in Auto Label Studio", result?.labels ?? []);
      await loadRuns(selectedSceneId);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Review could not be saved.");
    }
  };

  return (
    <main className="studio-shell">
      <header className="topbar">
        <div className="brand-lockup">
          <div className="brand-mark" aria-hidden="true"><Layers3 size={20} /></div>
          <div>
            <h1>Alpamayo Studio</h1>
            <span>Autonomous-driving research workspace</span>
          </div>
        </div>
        <div className="topbar-status">
          <span className={`status-dot ${providerStatus === "ready" ? "ready" : "warning"}`} />
          <span>Provider {providerStatus}</span>
          <button className="icon-button" onClick={() => void loadStudio()} title="Refresh Studio" type="button">
            <RefreshCw aria-hidden="true" size={17} />
          </button>
        </div>
      </header>

      <nav aria-label="Studio demos" className="demo-tabs">
        {DEMOS.map(({ id, shortLabel, icon: Icon }) => (
          <button
            aria-current={demo === id ? "page" : undefined}
            className={demo === id ? "active" : ""}
            data-demo={id}
            key={id}
            onClick={() => setDemo(id)}
            type="button"
          >
            <Icon aria-hidden="true" size={16} />
            <span>{shortLabel}</span>
          </button>
        ))}
      </nav>

      <section className="workspace-grid">
        <aside className="scene-sidebar" data-testid="scene-library">
          <div className="panel-heading">
            <div>
              <span className="section-kicker">Assets</span>
              <h2>Scene Library</h2>
            </div>
            <button
              className="icon-button"
              disabled={creatingScene}
              onClick={() => void createScene()}
              title="Create demo scene"
              type="button"
            >
              {creatingScene ? <LoaderCircle className="spin" size={17} /> : <ImagePlus size={17} />}
            </button>
          </div>
          <div className="scene-list">
            {loading ? <div className="sidebar-state"><LoaderCircle className="spin" size={18} /> Loading scenes</div> : null}
            {!loading && scenes.length === 0 ? (
              <button className="create-scene-empty" onClick={() => void createScene()} type="button">
                <ImagePlus size={19} />
                Create demo scene
              </button>
            ) : null}
            {scenes.map((scene) => (
              <button
                className={`scene-row ${scene.sceneId === selectedSceneId ? "selected" : ""}`}
                key={scene.sceneId}
                onClick={() => selectScene(scene)}
                type="button"
              >
                <img alt="Road scene preview" src={scene.previewUrl} />
                <span className="scene-copy">
                  <strong>{scene.name}</strong>
                  <span>{scene.sceneVersion.cameras.length} cameras</span>
                </span>
                <ChevronRight aria-hidden="true" size={16} />
              </button>
            ))}
          </div>
          <div className="history-section">
            <div className="history-heading">
              <span>Recent runs</span>
              <span>{history.length}</span>
            </div>
            {history.slice(0, 8).map((item) => (
              <button
                className={`history-row ${run?.runId === item.runId ? "selected" : ""}`}
                key={item.runId}
                onClick={() => setRun(item)}
                type="button"
              >
                <span className={`run-status-mark ${item.status}`} />
                <span>{item.demoId?.replaceAll("-", " ") ?? "inference"}</span>
                <time>{item.runId.slice(-5)}</time>
              </button>
            ))}
          </div>
        </aside>

        <section className="workbench" data-testid="viewport">
          <div className="workbench-toolbar">
            <div>
              <span className="section-kicker">{activeDemo.label}</span>
              <h2>{selectedScene?.name ?? "Select a scene"}</h2>
            </div>
            <div className="run-controls">
              {demo === "vqa" ? (
                <input aria-label="VQA question" onChange={(event) => setQuestion(event.target.value)} value={question} />
              ) : null}
              {demo === "navigation" ? (
                <input
                  aria-label="Navigation instruction"
                  onChange={(event) => setNavigationInstruction(event.target.value)}
                  value={navigationInstruction}
                />
              ) : null}
              <button
                className="primary-button"
                data-testid="run-inference"
                disabled={!selectedScene || running}
                onClick={() => void submitInference()}
                type="button"
              >
                {running ? <LoaderCircle className="spin" size={17} /> : <Play fill="currentColor" size={16} />}
                {running ? "Running" : "Run inference"}
              </button>
            </div>
          </div>

          {error ? (
            <div className="error-banner" role="alert">
              <CircleAlert size={17} />
              <span>{error}</span>
              <button className="icon-button" onClick={() => setError("")} title="Dismiss error" type="button"><X size={16} /></button>
            </div>
          ) : null}

          {demo === "ablation" ? (
            <div className="camera-selector" aria-label="Camera subset">
              {sceneCameras.map((camera) => (
                <label key={camera.cameraId}>
                  <input
                    checked={selectedCameras.includes(camera.cameraId)}
                    onChange={() => setSelectedCameras((current) => current.includes(camera.cameraId)
                      ? current.filter((cameraId) => cameraId !== camera.cameraId)
                      : [...current, camera.cameraId].sort((left, right) => left - right))}
                    type="checkbox"
                  />
                  <span>{CAMERA_NAMES[camera.cameraId] ?? `Camera ${camera.cameraId}`}</span>
                </label>
              ))}
            </div>
          ) : null}

          <div className="camera-grid" data-testid="camera-grid">
            {sceneCameras.map((camera) => {
              const name = CAMERA_NAMES[camera.cameraId] ?? `Camera ${camera.cameraId}`;
              return (
                <figure
                  className={!selectedCameras.includes(camera.cameraId) && demo === "ablation" ? "camera-disabled" : ""}
                  data-camera-id={camera.cameraId}
                  key={camera.cameraId}
                >
                  {selectedScene ? <img alt={`${name} camera road frame`} src={selectedScene.previewUrl} /> : <div className="camera-placeholder" />}
                  <figcaption><Camera size={13} /> Camera {camera.cameraId} / {name}</figcaption>
                </figure>
              );
            })}
          </div>

          <div className="timeline">
            <span className="mono-caption">T-{((frameCount - timelineIndex) * 0.1).toFixed(1)} s</span>
            <input
              aria-label="Synchronized camera time"
              max={Math.max(frameCount - 1, 0)}
              min="0"
              onChange={(event) => setTimelineIndex(Number(event.target.value))}
              type="range"
              value={timelineIndex}
            />
            <span className="mono-caption">Frame {timelineIndex + 1}/{frameCount}</span>
          </div>

          {result ? <TrajectoryPlot result={result} /> : <div className="trajectory-placeholder"><Activity size={20} /> Trajectory pending</div>}
        </section>

        <aside className="result-sidebar">
          <div className="panel-heading">
            <div>
              <span className="section-kicker">Inference</span>
              <h2>Result Inspector</h2>
            </div>
            <span className={`run-pill ${run?.status ?? "idle"}`} data-testid="run-status">
              {running ? "running" : run?.status ?? "idle"}
            </span>
          </div>
          <div className="result-body" data-testid="run-result">
            {!result ? <EmptyResult /> : (
              <>
                <section className="result-section">
                  <span className="section-kicker">VQA answer</span>
                  <p>{result.vqaAnswer}</p>
                </section>
                <section className="result-section">
                  <span className="section-kicker">Meta Action</span>
                  <strong className="meta-action">{result.metaAction.replaceAll("_", " ")}</strong>
                </section>
                <section className="result-section">
                  <span className="section-kicker">Chain of Causation</span>
                  <p>{result.chainOfCausation}</p>
                </section>
                <section className="result-section">
                  <span className="section-kicker">Labels</span>
                  <div className="label-list">{result.labels.map((label) => <span key={label}>{label}</span>)}</div>
                </section>
                {result.warnings.length ? (
                  <section className="warning-list">
                    {result.warnings.map((warning) => <span key={warning}><CircleAlert size={14} />{warning}</span>)}
                  </section>
                ) : null}
                {demo === "auto-label" ? (
                  <div className="review-actions">
                    <button onClick={() => void saveReview("accepted")} type="button"><Check size={16} /> Accept</button>
                    <button onClick={() => void saveReview("rejected")} type="button"><X size={16} /> Reject</button>
                  </div>
                ) : null}
                {demo === "regression-judge" ? (
                  <section className="regression-summary">
                    <FlaskConical size={17} />
                    <div><strong>10-scene suite ready</strong><span>Continue-on-failure enabled</span></div>
                  </section>
                ) : null}
                <dl className="evidence-list">
                  <div><dt>Demo</dt><dd>{run?.demoId ?? result.demoId}</dd></div>
                  <div><dt>Input</dt><dd title={summarizeParameters(run?.parameters)}>{summarizeParameters(run?.parameters)}</dd></div>
                  <div><dt>Provider</dt><dd>{result.provider}</dd></div>
                  <div><dt>Model</dt><dd>{result.modelName}</dd></div>
                  <div><dt>Run</dt><dd>{run?.runId}</dd></div>
                  <div><dt>Digest</dt><dd>{result.responseSha256.slice(0, 12)}</dd></div>
                </dl>
              </>
            )}
          </div>
        </aside>
      </section>

      <footer className="research-notice">
        Alpamayo Studio is for research, evaluation, and demonstration only. Outputs are not safety-certified and must not control a vehicle.
      </footer>
    </main>
  );
}
