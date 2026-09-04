import { SessionControls, type ManualAction } from "../features/session/sessionControls.js";
import { ReplayController, type ReplayDocument, type SceneRenderState } from "../features/replay/replayController.js";
import { buildStrategyComparisonView, type StrategyComparison } from "../features/strategy/comparisonPresenter.js";
import { validateStrategyEvaluation, type StrategyEvaluationResult } from "../features/strategy/evaluationPresenter.js";
import { ApiClient, type HmiServerEvent } from "./ApiClient.js";
import { HmiState, assessWebGLCapability, type ControlMode, type HmiView } from "./HmiState.js";
import { HighwayScene, WebGLUnavailableError, type HighwaySnapshot } from "./renderer/HighwayScene.js";


type Copy = ReturnType<HmiState["copy"]>;

const statusCopy = (view: Readonly<HmiView>) => view.language === "zh-CN"
  ? { connection: "连接状态", session: "会话状态", simulation: "仿真状态", reward: "奖励分解", explain: "决策解释", replay: "Episode 与回放" }
  : { connection: "Connection", session: "Session", simulation: "Simulation", reward: "Reward breakdown", explain: "Decision explanation", replay: "Episode & Replay" };

const displayMetricName = (name: string): string => name === "merge_success" ? "pass" : name;

export type SnapshotTelemetry = {
  speed: string;
  ttc: string;
  rewardTotal: string;
  rewardComponents: Array<[string, string]>;
  explanation: string;
};

const PRESETS = [
  ["normal-v1", "正常", "Normal"],
  ["congested-v1", "拥堵", "Congested"],
  ["aggressive-v1", "激进车辆", "Aggressive"],
  ["dangerous-cut-in-v1", "危险切入", "Dangerous cut-in"],
] as const;

export function formatSnapshotTelemetry(snapshot: HighwaySnapshot): SnapshotTelemetry {
  return {
    speed: `${snapshot.ego.speed_mps.toFixed(1)} m/s`,
    ttc: snapshot.safety.min_ttc_s === null ? "—" : `${snapshot.safety.min_ttc_s.toFixed(2)} s`,
    rewardTotal: snapshot.reward.total.toFixed(3),
    rewardComponents: Object.entries(snapshot.reward.components)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([name, value]) => [name, value.toFixed(3)]),
    explanation: `${snapshot.last_action ?? "—"} · ${snapshot.status.termination_reason ?? "running"}`,
  };
}

export function renderHmiShell(view: Readonly<HmiView>, copy: Copy): string {
  const label = statusCopy(view);
  const selectedPreset = view.selectedPreset ?? "normal-v1";
  const controlsDisabled = view.connectionStatus !== "connected" || view.sessionStatus !== "active";
  const stepDisabled = controlsDisabled || view.simulationStatus !== "paused";
  const presetOptions = PRESETS.map(([value, zh, en]) => `<option value="${value}" ${value === selectedPreset ? "selected" : ""}>${view.language === "zh-CN" ? zh : en}</option>`).join("");
  const laneOptions = [2, 3, 4, 5].map((value) => `<option value="${value}" ${value === view.lanesCount ? "selected" : ""}>${value}</option>`).join("");
  return `
    <div class="hmi" lang="${view.language}">
      <header class="topbar">
        <div><span class="eyebrow">LOCAL · PYTHON AUTHORITY</span><h1>${copy.title}</h1></div>
        <div class="top-actions">
          <button data-language="zh-CN" aria-pressed="${view.language === "zh-CN"}">中文</button>
          <button data-language="en-US" aria-pressed="${view.language === "en-US"}">EN</button>
        </div>
      </header>
      <section class="status-strip" aria-label="runtime status">
        <span>${label.connection}<strong data-testid="connection-status">${view.connectionStatus}</strong></span>
        <span>${label.session}<strong data-testid="session-status">${view.sessionStatus}</strong></span>
        <span>${label.simulation}<strong data-testid="simulation-status">${view.simulationStatus}</strong></span>
      </section>
      ${view.onboardingVisible ? `<aside class="onboarding"><p>${copy.onboarding}</p><button data-action="load-standard">${view.language === "zh-CN" ? "载入标准预设" : "Load standard preset"}</button></aside>` : ""}
      <main class="workspace">
        <section class="viewport-card">
          <canvas data-testid="highway-canvas" aria-label="Three.js driving scene"></canvas>
          <div class="renderer-fallback" data-testid="renderer-fallback" hidden></div>
          <div class="camera-switcher" aria-label="camera mode">
            <button data-camera="follow" aria-pressed="${view.cameraMode === "follow"}">${view.language === "zh-CN" ? "跟随" : "Follow"}</button><button data-camera="top" aria-pressed="${view.cameraMode === "top"}">${view.language === "zh-CN" ? "顶部" : "Top"}</button><button data-camera="free" aria-pressed="${view.cameraMode === "free"}">${view.language === "zh-CN" ? "自由" : "Free"}</button>
          </div>
          <div class="telemetry">
            <span>Speed <strong data-testid="speed">—</strong></span>
            <span>${view.language === "zh-CN" ? "车道" : "Lane"}<strong data-testid="lane">—</strong></span>
            <span>${view.language === "zh-CN" ? "动作" : "Action"}<strong data-testid="action">—</strong></span>
            <span>TTC <strong data-testid="ttc">—</strong></span>
            <span>Reward <strong data-testid="reward-total">—</strong></span>
            <span>${view.language === "zh-CN" ? "状态" : "Status"}<strong data-testid="terminal-status">—</strong></span>
          </div>
          <div class="viewport-insights">
            <section><h2>${label.reward}</h2><dl data-testid="reward-components"><dt>—</dt><dd>—</dd></dl></section>
            <section><h2>${label.explain}</h2><p data-testid="decision-explanation">${view.language === "zh-CN" ? "等待权威状态" : "Waiting for authoritative state"}</p></section>
          </div>
        </section>
        <aside class="control-rail">
          <section><h2>${view.language === "zh-CN" ? "场景配置" : "Scenario"}</h2>
            <label>${view.language === "zh-CN" ? "预设" : "Preset"}<select data-testid="preset">${presetOptions}</select></label>
            <label>${view.language === "zh-CN" ? "画质" : "Quality"}<select data-testid="quality"><option value="high" ${view.requestedQuality === "high" ? "selected" : ""}>${view.language === "zh-CN" ? "高" : "High"}</option><option value="medium" ${view.requestedQuality === "medium" ? "selected" : ""}>${view.language === "zh-CN" ? "中" : "Medium"}</option><option value="low" ${view.requestedQuality === "low" ? "selected" : ""}>${view.language === "zh-CN" ? "低" : "Low"}</option></select></label>
            <label>${view.language === "zh-CN" ? "车道数" : "Lanes"}<select data-testid="lanes-count">${laneOptions}</select></label>
            <label>${view.language === "zh-CN" ? "控制模式" : "Mode"}<select data-testid="control-mode"><option value="manual" ${view.controlMode === "manual" ? "selected" : ""}>${view.language === "zh-CN" ? "人工" : "Manual"}</option><option value="random" ${view.controlMode === "random" ? "selected" : ""}>${view.language === "zh-CN" ? "随机" : "Random"}</option><option value="qualified_rule" ${view.controlMode === "qualified_rule" ? "selected" : ""}>${view.language === "zh-CN" ? "合格规则" : "Qualified rule"}</option><option value="onnx" ${view.controlMode === "onnx" ? "selected" : ""}>ONNX</option></select></label>
            <label>${view.language === "zh-CN" ? "Seed" : "Seed"}<input data-config="seed" type="number" min="0" max="4294967295" step="1" placeholder="${view.language === "zh-CN" ? "整数" : "integer"}"></label>
            <label>${view.language === "zh-CN" ? "车辆数" : "Vehicles"}<input data-config="vehicles_count" type="number" min="0" max="50" step="1" placeholder="0–50"></label>
            <label>${view.language === "zh-CN" ? "密度" : "Density"}<input data-config="density" type="number" min="0.01" max="3" step="0.1" placeholder="0–3"></label>
            <label><span>${view.language === "zh-CN" ? "Ego 初速" : "Ego speed"} <span class="field-unit">(m/s)</span></span><input data-config="initial_speed_mps" type="number" min="5" max="30" step="0.1" placeholder="5–30"></label>
            <label>${view.language === "zh-CN" ? "封闭车道" : "Closed lane"}<input data-config="closed_lane_index" type="number" min="0" max="4" step="1" placeholder="${view.language === "zh-CN" ? "默认" : "default"}"></label>
            <label>${view.language === "zh-CN" ? "施工起点" : "Construction start"}<input data-config="zone_start_m" type="number" min="120.000001" step="1" placeholder=">120"></label>
            <label>${view.language === "zh-CN" ? "施工终点" : "Construction end"}<input data-config="zone_end_m" type="number" min="1" step="1" placeholder="340"></label>
            <label>${view.language === "zh-CN" ? "车流最低速度" : "Traffic min speed"}<input data-config="min_speed_mps" type="number" min="0" step="0.1" placeholder="18"></label>
            <label>${view.language === "zh-CN" ? "车流最高速度" : "Traffic max speed"}<input data-config="max_speed_mps" type="number" min="0" step="0.1" placeholder="28"></label>
            <label>${view.language === "zh-CN" ? "激进车辆比例" : "Aggressive fraction"}<input data-config="aggressive_fraction" type="number" min="0" max="1" step="0.05" placeholder="0–1"></label>
            <label>${view.language === "zh-CN" ? "时限(s)" : "Duration(s)"}<input data-config="duration_s" type="number" min="1" max="300" step="1" placeholder="1–300"></label>
            <button class="primary scene-reset" data-action="scene-reset" title="${view.language === "zh-CN" ? "清空场景配置；下次启动时使用默认值" : "Clear scenario inputs; defaults are used on next start"}">${view.language === "zh-CN" ? "场景重置" : "Reset scene"}</button>
            <details class="config-advanced"><summary>${view.language === "zh-CN" ? "奖励权重" : "Reward weights"}</summary><div class="config-grid">${(["collision","speed","safe_lane","lane_change","merge_success","ttc","comfort"] as const).map((key) => `<label>${displayMetricName(key)}<input data-config="reward.${key}" type="number" step="0.01" placeholder="${key === "speed" ? (view.language === "zh-CN" ? "任意" : "any finite") : key === "merge_success" || key === "safe_lane" ? "≥0" : "≤0"}"></label>`).join("")}</div></details>
            <div class="button-grid config-actions"><button data-config-action="preview">${view.language === "zh-CN" ? "预览" : "Preview"}</button><button data-config-action="reset">${view.language === "zh-CN" ? "恢复默认" : "Reset"}</button><button data-config-action="export">${view.language === "zh-CN" ? "导出 JSON" : "Export JSON"}</button><label class="file-button">${view.language === "zh-CN" ? "导入 JSON" : "Import JSON"}<input data-config-action="import" type="file" accept="application/json,.json"></label></div>
            <p data-testid="config-summary" class="control-hint">${view.language === "zh-CN" ? "尚未创建会话" : "No session configuration yet"}</p>
            <details><summary>${view.language === "zh-CN" ? "查看完整生效配置" : "View effective configuration"}</summary><pre data-testid="effective-config" class="config-preview">{}</pre></details>
            <button data-action="compare">${view.language === "zh-CN" ? "单次比较四种策略" : "Compare four strategies once"}</button>
            <div class="evaluation-controls"><label>${view.language === "zh-CN" ? "每策略次数" : "Runs per strategy"}<select data-testid="evaluation-count"><option>10</option><option selected>20</option><option>50</option><option>100</option></select></label><button data-action="evaluate">${view.language === "zh-CN" ? "批量评估" : "Batch evaluation"}</button><button data-action="cancel-evaluation" disabled>${view.language === "zh-CN" ? "取消评估" : "Cancel"}</button></div><div data-testid="evaluation-status" class="strategy-comparison" aria-live="polite"></div>
            <div data-testid="comparison-status" class="strategy-comparison" aria-live="polite"></div>
            <button class="primary" data-action="start">${copy.start}</button>
          </section>
          <section class="simulation-panel"><h2>${view.language === "zh-CN" ? "仿真控制" : "Simulation controls"}</h2>
            <div class="button-grid main-controls"><button data-control data-command="simulation.play" ${controlsDisabled ? "disabled" : ""} title="${view.language === "zh-CN" ? "开始或继续仿真" : "Start or resume simulation"}">▶</button><button data-control data-command="simulation.pause" ${controlsDisabled ? "disabled" : ""} title="${view.language === "zh-CN" ? "暂停仿真" : "Pause simulation"}">Ⅱ</button><select data-control data-rate-select aria-label="${view.language === "zh-CN" ? "仿真倍速" : "Simulation speed"}" ${controlsDisabled ? "disabled" : ""}>${([0.5, 1, 2, 4] as const).map((rate) => `<option value="${rate}" ${view.playbackRate === rate ? "selected" : ""}>${rate}×</option>`).join("")}</select><button data-control data-command="simulation.step" ${stepDisabled ? "disabled" : ""} title="${view.language === "zh-CN" ? "暂停时前进一个仿真步" : "Advance one step while paused"}">Step</button><button data-control data-command="simulation.reset" ${controlsDisabled ? "disabled" : ""} title="${view.language === "zh-CN" ? "按当前配置重置" : "Reset with current config"}">Reset</button></div>
            <div class="button-grid manual"><button data-control data-manual="LANE_LEFT" ${controlsDisabled ? "disabled" : ""} title="${view.language === "zh-CN" ? "行驶中即时向左换道" : "Change lane left while driving"}">←</button><button data-control data-manual="FASTER" ${controlsDisabled ? "disabled" : ""} title="${view.language === "zh-CN" ? "提高目标速度" : "Increase target speed"}">W</button><button data-control data-manual="IDLE" ${controlsDisabled ? "disabled" : ""} title="${view.language === "zh-CN" ? "保持当前驾驶状态" : "Hold current state"}">Hold</button><button data-control data-manual="SLOWER" ${controlsDisabled ? "disabled" : ""} title="${view.language === "zh-CN" ? "降低目标速度" : "Decrease target speed"}">S</button><button data-control data-manual="LANE_RIGHT" ${controlsDisabled ? "disabled" : ""} title="${view.language === "zh-CN" ? "行驶中即时向右换道" : "Change lane right while driving"}">→</button></div>
            <p class="control-hint">${view.language === "zh-CN" ? "W 加速 · Hold 保持 · S 减速 · Step 单步（暂停时）" : "W faster · Hold steady · S slower · Step while paused"}</p>
            <p data-testid="manual-status" class="control-hint" aria-live="polite"></p>
          </section>
          <section class="replay-panel"><h2>${label.replay}</h2><div class="button-grid"><button data-replay="save">Save</button><button data-replay="play">Play</button><button data-replay="step">Step</button><button data-replay="live">Live</button></div><select data-testid="episode-library-list" aria-label="${view.language === "zh-CN" ? "Episode Library" : "Episode Library"}"><option value="">${view.language === "zh-CN" ? "Library 未加载" : "Library not loaded"}</option></select><div class="button-grid"><button data-replay="refresh-library">${view.language === "zh-CN" ? "刷新 Library" : "Refresh Library"}</button><button data-replay="export-library">${view.language === "zh-CN" ? "导出选中" : "Export selected"}</button></div><p data-testid="episode-quota" class="control-hint"></p><input data-testid="replay-timeline" type="range" min="0" max="0" value="0" aria-label="replay timeline"><p data-testid="replay-status" class="replay-status">${view.language === "zh-CN" ? "尚未保存 Episode" : "No Episode saved"}</p></section>
          <section class="notice" data-testid="structured-notice" data-code="${view.notice?.code ?? ""}" ${view.notice ? "" : "hidden"}>${view.notice?.message ?? ""}</section>
        </aside>
      </main>
    </div>`;
}

export class App {
  readonly #root: HTMLElement;
  readonly #state = new HmiState();
  readonly #client: ApiClient;
  #scene: HighwayScene | null = null;
  #snapshot: HighwaySnapshot | null = null;
  #controls: SessionControls;
  #replayController: ReplayController<HighwaySnapshot> | null = null;
  #replayFrames: HighwaySnapshot[] = [];
  #replayActions: string[] = [];
  #replayGeneration = 0;
  #replayTimer: number | null = null;
  #lastManualAction: { action: ManualAction; until: number } | null = null;
  #preserveSceneOnMount = false;
  #importedConfig: Record<string, unknown> | null = null;
  #lastEffectiveConfig: Record<string, unknown> | null = null;
  #lastDecision: Record<string, unknown> | null = null;
  #pendingInitialControlMode: ControlMode | null = null;
  #webglLostHandler: (() => void) | null = null;
  #webglRestoredHandler: (() => void) | null = null;
  #activeEvaluationId: string | null = null;

  constructor(root: HTMLElement, client = new ApiClient()) {
    this.#root = root;
    this.#client = client;
    this.#controls = new SessionControls((command) => this.#client.send(command));
    this.#client.onEvent((event) => this.#onServerEvent(event));
    this.#client.onConnected(() => {
      const mode = this.#pendingInitialControlMode;
      this.#pendingInitialControlMode = null;
      if (mode) this.#controls.setMode(mode);
    });
    this.#root.addEventListener("keydown", (event) => {
      if (this.#state.view().connectionStatus !== "connected" || this.#state.view().sessionStatus !== "active") return;
      const target = event.target as HTMLElement | null;
      if (target && ["INPUT", "SELECT", "TEXTAREA"].includes(target.tagName)) return;
      const actions: Record<string, ManualAction> = { ArrowLeft: "LANE_LEFT", ArrowRight: "LANE_RIGHT", w: "FASTER", W: "FASTER", s: "SLOWER", S: "SLOWER", " ": "IDLE" };
      const action = actions[event.key];
      if (!action || this.#state.view().controlMode !== "manual") return;
      event.preventDefault();
      const admission = this.#controls.manualAction(action);
      if (admission.accepted) this.#setReplayStatus(`${this.#state.view().language === "zh-CN" ? "键盘动作" : "Keyboard action"}: ${action}`);
    });
  }

  mount(): void {
    this.#stopReplayTimer();
    const preservedCanvas = this.#preserveSceneOnMount
      ? this.#root.querySelector<HTMLCanvasElement>('[data-testid="highway-canvas"]')
      : null;
    this.#preserveSceneOnMount = false;
    if (!preservedCanvas) this.#scene?.dispose();
    this.#root.innerHTML = renderHmiShell(this.#state.view(), this.#state.copy());
    const freshCanvas = this.#root.querySelector<HTMLCanvasElement>('[data-testid="highway-canvas"]');
    if (preservedCanvas && freshCanvas && this.#scene) {
      freshCanvas.replaceWith(preservedCanvas);
    } else {
      this.#mountScene();
    }
    this.#bindActions();
    if (this.#snapshot && this.#scene) this.#scene.render(this.#snapshot, { mode: "live", index: 0, length: 0 });
    this.#syncConfigurationDom();
    this.#syncReplayDom();
    if (!this.#lastEffectiveConfig && !this.#importedConfig) void this.#populatePresetDefaults(this.#state.view().selectedPreset ?? "normal-v1");
  }

  async #populatePresetDefaults(preset: string): Promise<void> {
    try {
      const config = await this.#client.loadPreset(preset);
      const valueAt = (path: string): unknown => path.split(".").reduce<unknown>((current, key) => current && typeof current === "object" ? (current as Record<string, unknown>)[key] : undefined, config);
      const paths: Record<string, string> = {
        seed: "seed", vehicles_count: "traffic.vehicles_count", density: "traffic.density", initial_speed_mps: "ego.initial_speed_mps",
        closed_lane_index: "construction.closed_lane_index", zone_start_m: "construction.zone_start_m", zone_end_m: "construction.zone_end_m",
        min_speed_mps: "traffic.min_speed_mps", max_speed_mps: "traffic.max_speed_mps", aggressive_fraction: "traffic.aggressive_fraction", duration_s: "simulation.duration_s",
      };
      for (const key of ["collision", "speed", "safe_lane", "lane_change", "merge_success", "ttc", "comfort"] as const) paths[`reward.${key}`] = `reward.${key}`;
      const rangeOnly = new Set([
        "seed", "vehicles_count", "density", "initial_speed_mps", "zone_start_m", "aggressive_fraction", "duration_s",
        "reward.collision", "reward.speed", "reward.safe_lane", "reward.lane_change", "reward.merge_success", "reward.ttc", "reward.comfort",
      ]);
      for (const input of this.#root.querySelectorAll<HTMLInputElement>("[data-config]")) {
        if (input.value.trim()) continue;
        if (input.dataset.config === "closed_lane_index") continue;
        if (rangeOnly.has(input.dataset.config ?? "")) continue;
        const value = valueAt(paths[input.dataset.config ?? ""] ?? "");
        if (value !== undefined && value !== null) input.placeholder = String(value);
      }
    } catch { /* preset errors are surfaced by Start/Preview */ }
  }

  #mountScene(): void {
    const canvas = this.#root.querySelector<HTMLCanvasElement>('[data-testid="highway-canvas"]');
    const fallback = this.#root.querySelector<HTMLElement>('[data-testid="renderer-fallback"]');
    if (!canvas || !fallback) return;
    const assessment = assessWebGLCapability(canvas.getContext("webgl2"));
    this.#state.applyWebGLAssessment(assessment);
    if (!assessment.available) {
      canvas.hidden = true;
      fallback.hidden = false;
      fallback.textContent = this.#state.view().notice?.message ?? "WebGL 2 unavailable";
      return;
    }
    try {
      const rect = canvas.getBoundingClientRect();
      this.#scene = new HighwayScene({ canvas, width: Math.max(rect.width, 640), height: Math.max(rect.height, 360), quality: this.#state.view().effectiveQuality });
      const fallbackMessage = this.#root.querySelector<HTMLElement>('[data-testid="renderer-fallback"]');
      this.#webglLostHandler = () => {
        if (fallbackMessage) { fallbackMessage.hidden = false; fallbackMessage.textContent = this.#state.view().language === "zh-CN" ? "WebGL 上下文已丢失，正在尝试恢复…" : "WebGL context lost; attempting recovery…"; }
      };
      this.#webglRestoredHandler = () => {
        if (fallbackMessage) { fallbackMessage.hidden = true; fallbackMessage.textContent = ""; }
      };
      canvas.addEventListener("highwaypilot:webgl-lost", this.#webglLostHandler);
      canvas.addEventListener("highwaypilot:webgl-restored", this.#webglRestoredHandler);
      this.#replayController = new ReplayController<HighwaySnapshot>({
        render: (frame, state) => {
          this.#scene?.render(frame, state);
          this.#updateTelemetry(frame);
          this.#syncReplayDom(state);
        },
      });
    } catch (error) {
      if (!(error instanceof WebGLUnavailableError)) throw error;
      this.#state.applyWebGLAssessment({ available: false, weakGpu: false, renderer: null });
      canvas.hidden = true;
      fallback.hidden = false;
      fallback.textContent = this.#state.view().notice?.message ?? error.message;
    }
  }

  #bindActions(): void {
    this.#root.querySelectorAll<HTMLElement>("[data-language]").forEach((element) => element.addEventListener("click", () => {
      this.#state.setLanguage(element.dataset.language as "zh-CN" | "en-US");
      this.#preserveSceneOnMount = true;
      this.mount();
    }));
    this.#root.querySelector<HTMLElement>('[data-action="load-standard"]')?.addEventListener("click", () => {
      this.#state.loadStandardPreset();
      this.mount();
    });
    this.#root.querySelector<HTMLSelectElement>('[data-testid="preset"]')?.addEventListener("change", (event) => {
      void (async () => {
        const preset = (event.currentTarget as HTMLSelectElement).value;
        this.#state.setPreset(preset);
        this.#importedConfig = null;
        try {
          const config = await this.#client.loadPreset(preset);
          const lanes = (config.road as { lanes_count?: unknown } | undefined)?.lanes_count;
          if (typeof lanes === "number") this.#state.setLanesCount(lanes);
        } catch { /* start/preview will surface the authoritative error */ }
        this.#syncConfigurationDom();
      })();
    });
    this.#root.querySelector<HTMLElement>('[data-action="start"]')?.addEventListener("click", () => void this.#startSession());
    this.#root.querySelector<HTMLElement>('[data-action="scene-reset"]')?.addEventListener("click", () => this.#clearSceneConfigInputs());
    this.#root.querySelector<HTMLElement>('[data-action="compare"]')?.addEventListener("click", () => void this.#compareStrategies());
    this.#root.querySelector<HTMLElement>('[data-action="evaluate"]')?.addEventListener("click", () => void this.#evaluateStrategies());
    this.#root.querySelector<HTMLElement>('[data-action="cancel-evaluation"]')?.addEventListener("click", () => void this.#cancelEvaluation());
    this.#root.querySelectorAll<HTMLElement>("[data-camera]").forEach((element) => element.addEventListener("click", () => {
      const mode = element.dataset.camera as "follow" | "top" | "free";
      this.#state.setCameraMode(mode);
      this.#scene?.setCameraMode(mode);
      this.#root.querySelectorAll<HTMLElement>("[data-camera]").forEach((button) => button.setAttribute("aria-pressed", String(button.dataset.camera === mode)));
    }));
    this.#root.querySelector<HTMLSelectElement>('[data-testid="quality"]')?.addEventListener("change", (event) => {
      const quality = (event.currentTarget as HTMLSelectElement).value as "low" | "medium" | "high";
      this.#state.setQuality(quality);
      this.#scene?.setQuality(this.#state.view().effectiveQuality);
    });
    this.#root.querySelector<HTMLSelectElement>('[data-testid="lanes-count"]')?.addEventListener("change", (event) => {
      this.#state.setLanesCount(Number((event.currentTarget as HTMLSelectElement).value));
    });
    this.#root.querySelector<HTMLSelectElement>('[data-testid="episode-library-list"]')?.addEventListener("change", () => void this.#loadSelectedEpisode());
    this.#root.querySelector<HTMLSelectElement>('[data-testid="control-mode"]')?.addEventListener("change", (event) => {
      const mode = (event.currentTarget as HTMLSelectElement).value as "manual" | "random" | "qualified_rule" | "onnx";
      if (this.#state.view().sessionStatus !== "active") {
        this.#state.setControlMode(mode);
        return;
      }
      const admission = this.#controls.setMode(mode);
      if (admission.accepted) this.#state.setControlMode(mode);
      else {
        (event.currentTarget as HTMLSelectElement).value = this.#state.view().controlMode;
        this.#setReplayStatus(admission.notice?.message ?? "Control mode unavailable");
      }
    });
    this.#root.querySelector<HTMLElement>('[data-config-action="preview"]')?.addEventListener("click", () => void this.#previewConfig());
    this.#root.querySelector<HTMLElement>('[data-config-action="reset"]')?.addEventListener("click", () => this.#resetConfigInputs());
    this.#root.querySelector<HTMLElement>('[data-config-action="export"]')?.addEventListener("click", () => this.#exportConfig());
    this.#root.querySelector<HTMLInputElement>('[data-config-action="import"]')?.addEventListener("change", (event) => void this.#importConfig((event.currentTarget as HTMLInputElement).files?.[0]));
    this.#root.querySelectorAll<HTMLElement>("[data-command]").forEach((element) => element.addEventListener("click", () => {
      const name = element.dataset.command;
      if (name === "simulation.play") this.#controls.play();
      if (name === "simulation.pause") this.#controls.pause();
      if (name === "simulation.step") this.#controls.step();
      if (name === "simulation.reset") {
        this.#controls.reset();
        this.#resetReplayRecording();
      }
    }));
    this.#root.querySelector<HTMLSelectElement>("[data-rate-select]")?.addEventListener("change", (event) => {
      const rate = Number((event.currentTarget as HTMLSelectElement).value) as 0.5 | 1 | 2 | 4;
      const admission = this.#controls.setRate(rate);
      if (admission.accepted) {
        this.#state.setPlaybackRate(rate);
        this.#syncRateDom();
      }
    });
    this.#root.querySelectorAll<HTMLElement>("[data-manual]").forEach((element) => element.addEventListener("click", () => {
      const action = element.dataset.manual as ManualAction;
      const admission = this.#controls.manualAction(action);
      if (admission.accepted) {
        this.#lastManualAction = { action, until: Date.now() + 1200 };
        const status = this.#root.querySelector<HTMLElement>('[data-testid="manual-status"]');
        if (status) status.textContent = this.#state.view().language === "zh-CN" ? `已发送：${action}（行驶中即时生效）` : `Sent: ${action} (applies while driving)`;
      }
    }));
    this.#root.querySelector<HTMLElement>('[data-replay="save"]')?.addEventListener("click", () => void this.#saveReplay());
    this.#root.querySelector<HTMLElement>('[data-replay="play"]')?.addEventListener("click", () => this.#playReplay());
    this.#root.querySelector<HTMLElement>('[data-replay="step"]')?.addEventListener("click", () => this.#stepReplay());
    this.#root.querySelector<HTMLElement>('[data-replay="live"]')?.addEventListener("click", () => this.#returnToLive());
    this.#root.querySelector<HTMLElement>('[data-replay="refresh-library"]')?.addEventListener("click", () => void this.#refreshLibrary());
    this.#root.querySelector<HTMLElement>('[data-replay="export-library"]')?.addEventListener("click", () => void this.#exportSelectedEpisode());
    this.#root.querySelector<HTMLInputElement>('[data-testid="replay-timeline"]')?.addEventListener("input", (event) => {
      const index = Number((event.currentTarget as HTMLInputElement).value);
      if (this.#replayController?.view().mode === "historical") this.#replayController.seek(index);
    });
  }

  #validateConfigInputs(config: Record<string, unknown>): void {
    const zh = this.#state.view().language === "zh-CN";
    const issues: string[] = [];
    const labels: Record<string, string> = {
      seed: "Seed", vehicles_count: zh ? "车辆数" : "Vehicles", density: zh ? "密度" : "Density",
      initial_speed_mps: zh ? "Ego 初速" : "Ego speed", closed_lane_index: zh ? "封闭车道" : "Closed lane",
      zone_start_m: zh ? "施工起点" : "Construction start", zone_end_m: zh ? "施工终点" : "Construction end",
      min_speed_mps: zh ? "车流最低速度" : "Traffic min speed", max_speed_mps: zh ? "车流最高速度" : "Traffic max speed",
      aggressive_fraction: zh ? "激进车辆比例" : "Aggressive fraction", duration_s: zh ? "时限" : "Duration",
    };
    const rawValue = (key: string): string => this.#root.querySelector<HTMLInputElement>(`[data-config="${key}"]`)?.value.trim() ?? "";
    const numberValue = (key: string): number | undefined => {
      const raw = rawValue(key);
      if (!raw) return undefined;
      const value = Number(raw);
      if (!Number.isFinite(value)) {
        issues.push(`${labels[key] ?? key}: ${zh ? "必须是有限数字" : "must be a finite number"}`);
        return undefined;
      }
      return value;
    };
    const check = (key: string, options: { integer?: boolean; min?: number; max?: number; exclusiveMin?: number }): number | undefined => {
      const value = numberValue(key);
      if (value === undefined) return undefined;
      if (options.integer && !Number.isInteger(value)) issues.push(`${labels[key] ?? key}: ${zh ? "必须是整数" : "must be an integer"}`);
      if (options.min !== undefined && value < options.min) issues.push(`${labels[key] ?? key}: ${zh ? `范围为 ≥ ${options.min}` : `range is ≥ ${options.min}`}`);
      if (options.max !== undefined && value > options.max) issues.push(`${labels[key] ?? key}: ${zh ? `范围为 ≤ ${options.max}` : `range is ≤ ${options.max}`}`);
      if (options.exclusiveMin !== undefined && value <= options.exclusiveMin) issues.push(`${labels[key] ?? key}: ${zh ? `范围为 > ${options.exclusiveMin}` : `range is > ${options.exclusiveMin}`}`);
      return value;
    };

    check("seed", { integer: true, min: 0, max: 4_294_967_295 });
    check("vehicles_count", { integer: true, min: 0, max: 50 });
    check("density", { exclusiveMin: 0, max: 3 });
    check("initial_speed_mps", { min: 5, max: 30 });
    const lanes = Number((config.road as Record<string, unknown> | undefined)?.lanes_count ?? this.#state.view().lanesCount);
    const closedLane = check("closed_lane_index", { integer: true, min: 0, max: Math.max(0, lanes - 1) });
    if (closedLane !== undefined && Number.isInteger(closedLane)) {
      const side = String((config.construction as Record<string, unknown> | undefined)?.side ?? "right");
      const expected = side === "left" ? 0 : Math.max(0, lanes - 1);
      if (closedLane !== expected) issues.push(`${labels.closed_lane_index}: ${zh ? `${side === "left" ? "左侧" : "右侧"}封闭时必须为 ${expected}` : `must be ${expected} when the ${side} side is closed`}`);
    }
    const start = check("zone_start_m", { min: 0 });
    const end = check("zone_end_m", { exclusiveMin: 0 });
    const roadLength = Number((config.road as Record<string, unknown> | undefined)?.length_m ?? 1000);
    const construction = config.construction as Record<string, unknown> | undefined;
    const warningOffsets = Array.isArray(construction?.warning_offsets_m) ? construction.warning_offsets_m : [];
    const maxWarning = warningOffsets.reduce((max, value) => typeof value === "number" && Number.isFinite(value) ? Math.max(max, value) : max, 0);
    if (start !== undefined && maxWarning > 0 && start <= maxWarning) issues.push(`${labels.zone_start_m}: ${zh ? `必须大于最大警示距离 ${maxWarning} m` : `must be greater than the maximum warning distance ${maxWarning} m`}`);
    if (start !== undefined && end !== undefined && end <= start) issues.push(`${labels.zone_end_m}: ${zh ? "必须大于施工起点" : "must be greater than construction start"}`);
    if (end !== undefined && end > roadLength) issues.push(`${labels.zone_end_m}: ${zh ? `范围为 ≤ ${roadLength} m` : `range is ≤ ${roadLength} m`}`);
    const minSpeed = check("min_speed_mps", { min: 0 });
    const maxSpeed = check("max_speed_mps", { min: 0 });
    if (minSpeed !== undefined && maxSpeed !== undefined && minSpeed > maxSpeed) issues.push(`${labels.max_speed_mps}: ${zh ? "必须大于或等于车流最低速度" : "must be at least traffic minimum speed"}`);
    check("aggressive_fraction", { min: 0, max: 1 });
    check("duration_s", { min: 1, max: 300 });
    const rewardLabels: Record<string, string> = { collision: "collision", speed: "speed", safe_lane: "safe_lane", lane_change: "lane_change", merge_success: "pass", ttc: "ttc", comfort: "comfort" };
    for (const key of ["collision", "lane_change", "ttc", "comfort"] as const) {
      const value = numberValue(`reward.${key}`);
      if (value !== undefined && value > 0) issues.push(`${rewardLabels[key]}: ${zh ? "范围为 ≤ 0" : "range is ≤ 0"}`);
    }
    const pass = numberValue("reward.merge_success");
    if (pass !== undefined && pass < 0) issues.push(`${rewardLabels.merge_success}: ${zh ? "范围为 ≥ 0" : "range is ≥ 0"}`);
    const safeLane = numberValue("reward.safe_lane");
    if (safeLane !== undefined && safeLane < 0) issues.push(`${rewardLabels.safe_lane}: ${zh ? "范围为 ≥ 0" : "range is ≥ 0"}`);
    numberValue("reward.speed");
    if (issues.length > 0) throw new Error(issues.join(zh ? "；" : "; "));
  }

  async #startSession(): Promise<void> {
    const enteredConfig = new Map<string, string>();
    this.#root.querySelectorAll<HTMLInputElement>("[data-config]").forEach((input) => enteredConfig.set(input.dataset.config ?? "", input.value));
    try {
      this.#state.updateLifecycle({ connectionStatus: "connecting", sessionStatus: "none", simulationStatus: "paused" });
      const preset = this.#root.querySelector<HTMLSelectElement>('[data-testid="preset"]')?.value ?? this.#state.view().selectedPreset ?? "normal-v1";
      const initialControlMode = (this.#root.querySelector<HTMLSelectElement>('[data-testid="control-mode"]')?.value ?? this.#state.view().controlMode) as ControlMode;
      const config = this.#importedConfig ? structuredClone(this.#importedConfig) : await this.#client.loadPreset(preset);
      const road = (config.road && typeof config.road === "object") ? config.road as Record<string, unknown> : {};
      config.road = { ...road, lanes_count: this.#state.view().lanesCount };
      const numberInput = (key: string): number | undefined => {
        const raw = this.#root.querySelector<HTMLInputElement>(`[data-config="${key}"]`)?.value.trim() ?? "";
        if (!raw) return undefined;
        const value = Number(raw);
        return Number.isFinite(value) ? value : undefined;
      };
      const seed = numberInput("seed");
      if (seed !== undefined) config.seed = seed;
      const vehicles = numberInput("vehicles_count");
      const density = numberInput("density");
      const closedLane = numberInput("closed_lane_index");
      const egoSpeed = numberInput("initial_speed_mps");
      const zoneStart = numberInput("zone_start_m");
      const zoneEnd = numberInput("zone_end_m");
      const duration = numberInput("duration_s");
      const traffic = (config.traffic && typeof config.traffic === "object") ? config.traffic as Record<string, unknown> : {};
      const minSpeed = numberInput("min_speed_mps");
      const maxSpeed = numberInput("max_speed_mps");
      const aggressiveFraction = numberInput("aggressive_fraction");
      config.traffic = { ...traffic, ...(vehicles === undefined ? {} : { vehicles_count: vehicles }), ...(density === undefined ? {} : { density }), ...(minSpeed === undefined ? {} : { min_speed_mps: minSpeed }), ...(maxSpeed === undefined ? {} : { max_speed_mps: maxSpeed }), ...(aggressiveFraction === undefined ? {} : { aggressive_fraction: aggressiveFraction }) };
      const ego = (config.ego && typeof config.ego === "object") ? config.ego as Record<string, unknown> : {};
      config.ego = { ...ego, ...(egoSpeed === undefined ? {} : { initial_speed_mps: egoSpeed }) };
      const construction = (config.construction && typeof config.construction === "object") ? config.construction as Record<string, unknown> : {};
      config.construction = { ...construction, ...(closedLane === undefined ? {} : { closed_lane_index: closedLane }), ...(zoneStart === undefined ? {} : { zone_start_m: zoneStart }), ...(zoneEnd === undefined ? {} : { zone_end_m: zoneEnd }) };
      if (closedLane === undefined) delete (config.construction as Record<string, unknown>).closed_lane_index;
      const simulation = (config.simulation && typeof config.simulation === "object") ? config.simulation as Record<string, unknown> : {};
      config.simulation = { ...simulation, ...(duration === undefined ? {} : { duration_s: duration }) };
      const reward = (config.reward && typeof config.reward === "object") ? config.reward as Record<string, unknown> : {};
      for (const key of ["collision", "speed", "safe_lane", "lane_change", "merge_success", "ttc", "comfort"] as const) {
        const value = numberInput(`reward.${key}`);
        if (value !== undefined) reward[key] = value;
      }
      config.reward = reward;
      const { target_lane_index: _targetLane, ...constructionWithClosedLane } = config.construction as Record<string, unknown>;
      config.construction = constructionWithClosedLane;
      this.#validateConfigInputs(config);
      const created = await this.#client.createSession(config);
      this.#lastEffectiveConfig = structuredClone(created.effective_config ?? config);
      this.#importedConfig = null;
      const summary = this.#root.querySelector<HTMLElement>('[data-testid="config-summary"]');
      if (summary) summary.textContent = `${this.#state.view().language === "zh-CN" ? "生效配置" : "Effective config"} · ${created.config_digest ?? created.snapshot.config_digest ?? "—"}`;
      this.#snapshot = created.snapshot;
      this.#replayGeneration = created.simulation_generation;
      this.#replayFrames = [created.snapshot];
      this.#replayActions = [];
      this.#state.updateLifecycle({ connectionStatus: "connected", sessionStatus: "active", simulationStatus: "paused" });
      this.#controls.setConnectionStatus("connected");
      this.#controls.setSessionStatus("active");
      this.#pendingInitialControlMode = initialControlMode;
      this.#client.connect();
      this.mount();
    } catch (error) {
      this.#pendingInitialControlMode = null;
      this.#state.updateLifecycle({ connectionStatus: "disconnected", sessionStatus: "none", simulationStatus: "paused" });
      this.#state.reportSessionError(error instanceof Error ? error.message : "SESSION_CREATE_FAILED");
      this.mount();
      this.#root.querySelectorAll<HTMLInputElement>("[data-config]").forEach((input) => {
        const value = enteredConfig.get(input.dataset.config ?? "");
        if (value !== undefined) input.value = value;
      });
    }
  }

  #onServerEvent(event: HmiServerEvent): void {
    if (event.type === "command.error") {
      const error = event.error as { code?: unknown; message?: unknown } | undefined;
      const message = typeof error?.message === "string" ? error.message : String(error?.code ?? "COMMAND_ERROR");
      this.#setReplayStatus(message);
      const controlStatus = this.#root.querySelector<HTMLElement>('[data-testid="manual-status"]');
      if (controlStatus) controlStatus.textContent = message;
    }
    if (event.decision) this.#lastDecision = event.decision;
    const result = event.result as { snapshot?: HighwaySnapshot; simulation_status?: string } | undefined;
    const snapshot = event.snapshot ?? result?.snapshot;
    if (snapshot) {
      const generation = typeof event.simulation_generation === "number" ? event.simulation_generation : this.#replayGeneration;
      if (generation !== this.#replayGeneration || (this.#replayFrames.length > 0 && snapshot.step === 0 && this.#replayFrames.at(-1)?.step !== 0)) {
        this.#replayGeneration = generation;
        this.#replayFrames = [snapshot];
        this.#replayActions = [];
      } else if (this.#replayFrames.length === 0) {
        this.#replayFrames = [snapshot];
      } else if ((snapshot.step ?? 0) > (this.#replayFrames.at(-1)?.step ?? -1)) {
        this.#replayFrames.push(snapshot);
        this.#replayActions.push(snapshot.last_action ?? "IDLE");
      }
      this.#snapshot = snapshot;
      if (this.#replayController?.view().mode !== "historical") {
        this.#scene?.render(snapshot, { mode: "live", index: 0, length: 0 });
        this.#updateTelemetry(snapshot);
      }
    }
    const connectionStatus = event.connection_status;
    if (connectionStatus === "disconnected" || connectionStatus === "connecting" || connectionStatus === "connected") {
      this.#state.updateLifecycle({ connectionStatus });
      this.#controls.setConnectionStatus(connectionStatus);
    }
    const sessionStatus = event.session_status;
    if (sessionStatus === "none" || sessionStatus === "active" || sessionStatus === "closed" || sessionStatus === "resume_pending") {
      this.#state.updateLifecycle({ sessionStatus });
      this.#controls.setSessionStatus(sessionStatus);
    }
    const simulationStatus = event.simulation_status ?? result?.simulation_status;
    if (simulationStatus === "playing" || simulationStatus === "paused" || simulationStatus === "terminated") {
      this.#state.updateLifecycle({ simulationStatus });
      this.#controls.setSimulationStatus(simulationStatus);
    }
    const playbackRate = event.playback_rate ?? (event.result as { playback_rate?: unknown } | undefined)?.playback_rate;
    if (playbackRate === 0.5 || playbackRate === 1 || playbackRate === 2 || playbackRate === 4) {
      this.#state.setPlaybackRate(playbackRate);
      this.#syncRateDom();
    }
    const controlMode = event.control_mode ?? (event.result as { control_mode?: unknown } | undefined)?.control_mode;
    if (controlMode === "manual" || controlMode === "random" || controlMode === "qualified_rule" || controlMode === "onnx") {
      this.#state.setControlMode(controlMode);
      const selector = this.#root.querySelector<HTMLSelectElement>('[data-testid="control-mode"]');
      if (selector) selector.value = controlMode;
      if (event.type === "command.result") {
        const controlStatus = this.#root.querySelector<HTMLElement>('[data-testid="manual-status"]');
        if (controlStatus) controlStatus.textContent = `${this.#state.view().language === "zh-CN" ? "控制模式" : "Control mode"}: ${controlMode === "onnx" ? "ONNX" : controlMode}`;
      }
    }
    this.#syncLifecycleDom();
  }

  #replayDocument(): ReplayDocument<HighwaySnapshot> {
    const initial = this.#replayFrames[0];
    if (!initial) throw new Error("no episode has been recorded");
    return {
      schema_version: "highwaypilot-replay/v1",
      episode_id: `episode-${(initial.config_digest ?? "session").slice(0, 12)}-${this.#replayGeneration}`,
      initial_frame: initial,
      actions: this.#replayFrames.slice(1).map((frame, index) => ({
        index,
        action: this.#replayActions[index] ?? frame.last_action ?? "IDLE",
        frame,
        reward: frame.reward.components,
      })),
    };
  }

  async #saveReplay(): Promise<void> {
    try {
      if (!this.#replayController) throw new Error("renderer is not ready");
      this.#replayController.load(this.#replayDocument());
      const item = await this.#client.saveSessionEpisode();
      this.#setReplayStatus(this.#state.view().language === "zh-CN" ? `已保存到 Episode Library：${item.name}` : `Saved to Episode Library: ${item.name}`);
      await this.#refreshLibrary();
    } catch (error) {
      this.#setReplayStatus(error instanceof Error ? error.message : "Episode save failed");
    }
  }

  #playReplay(): void {
    try {
      if (!this.#replayController) throw new Error("renderer is not ready");
      if (this.#replayController.view().mode !== "historical") this.#replayController.load(this.#replayDocument());
      this.#replayController.start();
      this.#stopReplayTimer();
      this.#replayTimer = globalThis.window.setInterval(() => {
        if (!this.#replayController?.tick()) this.#stopReplayTimer();
      }, 180);
      this.#setReplayStatus(this.#state.view().language === "zh-CN" ? "回放播放中" : "Replay playing");
    } catch (error) {
      this.#setReplayStatus(error instanceof Error ? error.message : "Replay unavailable");
    }
  }

  #stepReplay(): void {
    try {
      if (!this.#replayController) throw new Error("renderer is not ready");
      if (this.#replayController.view().mode !== "historical") this.#replayController.load(this.#replayDocument());
      this.#replayController.pause();
      this.#replayController.step();
      this.#setReplayStatus(this.#state.view().language === "zh-CN" ? "回放单步" : "Replay stepped");
    } catch (error) {
      this.#setReplayStatus(error instanceof Error ? error.message : "Replay unavailable");
    }
  }

  #returnToLive(): void {
    this.#stopReplayTimer();
    if (this.#replayController && this.#snapshot) this.#replayController.returnToLive(this.#snapshot);
    this.#setReplayStatus(this.#state.view().language === "zh-CN" ? "实时状态" : "Live state");
  }

  #resetReplayRecording(): void {
    if (this.#snapshot) {
      this.#replayFrames = [this.#snapshot];
      this.#replayActions = [];
    }
    this.#stopReplayTimer();
  }

  #stopReplayTimer(): void {
    if (this.#replayTimer !== null) {
      globalThis.window.clearInterval(this.#replayTimer);
      this.#replayTimer = null;
    }
  }

  #setReplayStatus(message: string): void {
    const element = this.#root.querySelector<HTMLElement>('[data-testid="replay-status"]');
    if (element) element.textContent = message;
  }

  async #previewConfig(): Promise<Record<string, unknown> | null> {
    const summary = this.#root.querySelector<HTMLElement>('[data-testid="config-summary"]');
    try {
      const preset = this.#root.querySelector<HTMLSelectElement>('[data-testid="preset"]')?.value ?? "normal-v1";
      const config = this.#importedConfig ? structuredClone(this.#importedConfig) : await this.#client.loadPreset(preset);
      const road = (config.road && typeof config.road === "object") ? config.road as Record<string, unknown> : {};
      road.lanes_count = this.#state.view().lanesCount; config.road = road;
      const read = (key: string) => {
        const raw = this.#root.querySelector<HTMLInputElement>(`[data-config="${key}"]`)?.value.trim() ?? "";
        return raw ? Number(raw) : undefined;
      };
      const seed = read("seed"); if (seed !== undefined) config.seed = seed;
      const traffic = (config.traffic && typeof config.traffic === "object") ? config.traffic as Record<string, unknown> : {};
      for (const key of ["vehicles_count", "density", "min_speed_mps", "max_speed_mps", "aggressive_fraction"] as const) { const value = read(key); if (value !== undefined) traffic[key] = value; }
      config.traffic = traffic;
      const ego = (config.ego && typeof config.ego === "object") ? config.ego as Record<string, unknown> : {}; const egoSpeed = read("initial_speed_mps"); if (egoSpeed !== undefined) ego.initial_speed_mps = egoSpeed; config.ego = ego;
      const construction = (config.construction && typeof config.construction === "object") ? config.construction as Record<string, unknown> : {}; for (const key of ["closed_lane_index", "zone_start_m", "zone_end_m"] as const) { const value = read(key); if (value !== undefined) construction[key] = value; } config.construction = construction;
      // The target lane is derived from the selected road width, closure side,
      // and closed lane. Keeping a preset's target after changing lane count
      // makes Preview/Compare/Evaluate disagree with Start session.
      delete construction.target_lane_index;
      const simulation = (config.simulation && typeof config.simulation === "object") ? config.simulation as Record<string, unknown> : {}; const duration = read("duration_s"); if (duration !== undefined) simulation.duration_s = duration; config.simulation = simulation;
      const reward = (config.reward && typeof config.reward === "object") ? config.reward as Record<string, unknown> : {}; for (const key of ["collision", "speed", "safe_lane", "lane_change", "merge_success", "ttc", "comfort"] as const) { const value = read(`reward.${key}`); if (value !== undefined) reward[key] = value; } config.reward = reward;
      const effective = await this.#client.validateConfig(config);
      this.#lastEffectiveConfig = structuredClone(effective);
      if (summary) summary.textContent = `${this.#state.view().language === "zh-CN" ? "预览有效" : "Preview valid"} · ${String(effective.schema_version)} · seed=${String(effective.seed)}`;
      return effective;
    } catch (error) {
      if (summary) summary.textContent = error instanceof Error ? error.message : "INVALID_CONFIG";
      return null;
    }
  }

  #resetConfigInputs(): void {
    this.#importedConfig = null;
    this.#root.querySelectorAll<HTMLInputElement>('[data-config]').forEach((input) => { input.value = ""; });
    this.#setReplayStatus(this.#state.view().language === "zh-CN" ? "已恢复预设默认值" : "Preset defaults restored");
  }

  #clearSceneConfigInputs(): void {
    this.#importedConfig = null;
    this.#root.querySelectorAll<HTMLInputElement>('[data-config]').forEach((input) => { input.value = ""; });
    const summary = this.#root.querySelector<HTMLElement>('[data-testid="config-summary"]');
    if (summary) summary.textContent = this.#state.view().language === "zh-CN" ? "场景配置已清空，启动时使用默认值" : "Scenario configuration cleared; defaults will be used on start";
    this.#setReplayStatus(this.#state.view().language === "zh-CN" ? "场景配置已清空" : "Scenario configuration cleared");
  }

  #exportConfig(): void {
    const config = this.#lastEffectiveConfig ?? { schema_version: "construction-config/v1", scenario_id: "construction-v0", seed: 101, road: { lanes_count: this.#state.view().lanesCount } };
    const blob = new Blob([JSON.stringify(config, null, 2)], { type: "application/json" });
    const link = globalThis.document.createElement("a");
    link.href = URL.createObjectURL(blob); link.download = "construction-config.json"; link.click(); URL.revokeObjectURL(link.href);
    this.#setReplayStatus(this.#state.view().language === "zh-CN" ? "配置 JSON 已导出" : "Configuration JSON exported");
  }

  async #importConfig(file: File | undefined): Promise<void> {
    if (!file) return;
    try {
      const parsed = JSON.parse(await file.text()) as Record<string, unknown>;
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("INVALID_CONFIG");
      this.#importedConfig = parsed;
      const importedLanes = (parsed.road as { lanes_count?: unknown } | undefined)?.lanes_count;
      if (typeof importedLanes === "number") this.#state.setLanesCount(importedLanes);
      const summary = this.#root.querySelector<HTMLElement>('[data-testid="config-summary"]');
      if (summary) summary.textContent = this.#state.view().language === "zh-CN" ? "已导入配置，启动时执行严格校验" : "Configuration imported; strict validation runs at start";
    } catch (error) {
      this.#setReplayStatus(error instanceof Error ? error.message : "INVALID_CONFIG");
    }
  }

  async #refreshLibrary(): Promise<void> {
    try {
      const result = await this.#client.listEpisodes();
      const select = this.#root.querySelector<HTMLSelectElement>('[data-testid="episode-library-list"]');
      if (select) {
        select.replaceChildren(...result.items.map((item) => {
          const option = globalThis.document.createElement("option");
          option.value = item.episode_id;
          option.textContent = `${item.name} (${item.canonical_bytes} B)`;
          return option;
        }));
        if (result.items.length === 0) select.append(new Option(this.#state.view().language === "zh-CN" ? "暂无 Episode" : "No Episodes", ""));
      }
      const quota = this.#root.querySelector<HTMLElement>('[data-testid="episode-quota"]');
      if (quota) quota.textContent = `${result.quota.count ?? result.items.length}/${result.quota.max_count ?? 100} · ${result.quota.used_bytes ?? 0}/${result.quota.max_bytes ?? 100000000} B`;
    } catch (error) {
      this.#setReplayStatus(error instanceof Error ? error.message : "Episode library unavailable");
    }
  }

  async #compareStrategies(): Promise<void> {
    const status = this.#root.querySelector<HTMLElement>('[data-testid="comparison-status"]');
    const button = this.#root.querySelector<HTMLButtonElement>('[data-action="compare"]');
    const zh = this.#state.view().language === "zh-CN";
    try {
      if (button) button.disabled = true;
      if (status) status.textContent = this.#state.view().language === "zh-CN" ? "正在运行四种策略…" : "Running four strategies…";
      const config = await this.#previewConfig();
      if (!config) throw new Error(zh ? "当前场景配置无效" : "Current scenario configuration is invalid");
      const result = await this.#client.compareStrategies(config) as unknown as StrategyComparison;
      const comparison = buildStrategyComparisonView(result);
      if (!status) return;
      const meta = globalThis.document.createElement("p");
      meta.className = "control-hint comparison-meta";
      meta.textContent = `${zh ? "同一配置与 Seed" : "Same config and seed"}: ${comparison.seed} · ${comparison.configDigest.slice(0, 12)}…`;
      const table = globalThis.document.createElement("table");
      table.className = "strategy-comparison-table";
      const header = globalThis.document.createElement("thead");
      const headerRow = globalThis.document.createElement("tr");
      const labels = zh
        ? ["策略", "结果", "奖励", "碰撞", "成功", "超时", "均速", "耗时", "换道", "最小 TTC", "舒适度", "Episode"]
        : ["Strategy", "Result", "Reward", "Collision", "Success", "Timeout", "Avg speed", "Time", "Changes", "Min TTC", "Comfort", "Episode"];
      for (const label of labels) {
        const cell = globalThis.document.createElement("th");
        cell.scope = "col";
        cell.textContent = label;
        headerRow.append(cell);
      }
      header.append(headerRow);
      const body = globalThis.document.createElement("tbody");
      for (const row of comparison.rows) {
        const line = globalThis.document.createElement("tr");
        const values = [
          `${row.strategyId}\n${row.version}`,
          displayMetricName(row.result),
          row.episodeReward.toFixed(3),
          row.collision ? (zh ? "是" : "Yes") : (zh ? "否" : "No"),
          row.success ? (zh ? "是" : "Yes") : (zh ? "否" : "No"),
          row.timeout ? (zh ? "是" : "Yes") : (zh ? "否" : "No"),
          `${row.averageSpeedMps.toFixed(2)} m/s`,
          `${row.completionTimeS.toFixed(2)} s`,
          String(row.laneChangeCount),
          row.minimumTtcS === null ? "—" : `${row.minimumTtcS.toFixed(2)} s`,
          row.comfortScore.toFixed(3),
        ];
        for (const value of values) {
          const cell = globalThis.document.createElement("td");
          cell.textContent = value;
          line.append(cell);
        }
        const episodeCell = globalThis.document.createElement("td");
        if (!row.success && row.replay) {
          const save = globalThis.document.createElement("button");
          save.type = "button";
          save.textContent = zh ? "保存失败" : "Save failure";
          save.addEventListener("click", () => void (async () => {
            try {
              save.disabled = true;
              await this.#client.saveEpisode(row.replay!, `comparison-${row.strategyId}-${comparison.seed}`);
              await this.#refreshLibrary();
              save.textContent = zh ? "已保存" : "Saved";
            } catch (error) {
              save.disabled = false;
              save.textContent = error instanceof Error ? error.message : "Save failed";
            }
          })());
          episodeCell.append(save);
        } else {
          episodeCell.textContent = "—";
        }
        line.append(episodeCell);
        body.append(line);
      }
      table.append(header, body);
      const notice = globalThis.document.createElement("p");
      notice.className = "control-hint";
      notice.textContent = zh ? "单 Episode 对比不生成统计率或置信区间。" : comparison.singleEpisodeNotice;
      status.replaceChildren(meta, table, notice);
    } catch (error) {
      if (status) status.textContent = error instanceof Error ? error.message : "Comparison failed";
    } finally {
      if (button) button.disabled = false;
    }
  }

  async #evaluateStrategies(): Promise<void> {
    const evaluate = this.#root.querySelector<HTMLButtonElement>('[data-action="evaluate"]');
    const cancel = this.#root.querySelector<HTMLButtonElement>('[data-action="cancel-evaluation"]');
    const zh = this.#state.view().language === "zh-CN";
    try {
      if (this.#activeEvaluationId !== null) throw new Error(zh ? "已有评估正在运行" : "An evaluation is already running");
      if (evaluate) evaluate.disabled = true;
      if (cancel) cancel.disabled = false;
      const config = await this.#previewConfig();
      if (!config) throw new Error(zh ? "当前场景配置无效" : "Current scenario configuration is invalid");
      const count = Number(this.#root.querySelector<HTMLSelectElement>('[data-testid="evaluation-count"]')?.value ?? 20);
      const seedStart = Number(config.seed ?? 101);
      let status = this.#root.querySelector<HTMLElement>('[data-testid="evaluation-status"]');
      if (status) status.textContent = zh ? "正在创建配对 Seed 评估…" : "Creating paired-Seed evaluation…";
      let job = await this.#client.startStrategyEvaluation(config, count, seedStart);
      const evaluationId = job.evaluation_id;
      this.#activeEvaluationId = evaluationId;
      while (this.#activeEvaluationId === evaluationId && !["completed", "cancelled", "failed"].includes(job.status)) {
        status = this.#root.querySelector<HTMLElement>('[data-testid="evaluation-status"]');
        if (status) status.textContent = `${zh ? "评估进度" : "Evaluation progress"}: ${job.progress.completed}/${job.progress.total}`;
        await new Promise<void>((resolve) => globalThis.setTimeout(resolve, 300));
        job = await this.#client.getStrategyEvaluation(evaluationId);
      }
      if (this.#activeEvaluationId !== evaluationId) return;
      if (job.status === "completed" && job.result) {
        this.#renderStrategyEvaluation(evaluationId, validateStrategyEvaluation(job.result));
      } else if (status) {
        status.textContent = job.status === "cancelled"
          ? (zh ? "评估已在 Episode 边界取消" : "Evaluation cancelled at an Episode boundary")
          : String(job.error ?? (zh ? "评估失败" : "Evaluation failed"));
      }
    } catch (error) {
      const status = this.#root.querySelector<HTMLElement>('[data-testid="evaluation-status"]');
      if (status) status.textContent = error instanceof Error ? error.message : "Evaluation failed";
    } finally {
      this.#activeEvaluationId = null;
      if (evaluate) evaluate.disabled = false;
      if (cancel) cancel.disabled = true;
    }
  }

  async #cancelEvaluation(): Promise<void> {
    if (this.#activeEvaluationId === null) return;
    const status = this.#root.querySelector<HTMLElement>('[data-testid="evaluation-status"]');
    try {
      await this.#client.cancelStrategyEvaluation(this.#activeEvaluationId);
      if (status) status.textContent = this.#state.view().language === "zh-CN" ? "正在安全取消…" : "Cancelling safely…";
    } catch (error) {
      if (status) status.textContent = error instanceof Error ? error.message : "Cancellation failed";
    }
  }

  #renderStrategyEvaluation(evaluationId: string, result: StrategyEvaluationResult): void {
    const status = this.#root.querySelector<HTMLElement>('[data-testid="evaluation-status"]');
    if (!status) return;
    const zh = this.#state.view().language === "zh-CN";
    const resultDetails = globalThis.document.createElement("details");
    resultDetails.className = "evaluation-result";
    resultDetails.open = true;
    const resultSummary = globalThis.document.createElement("summary");
    resultSummary.textContent = `${zh ? "评估结果" : "Evaluation result"} · ${result.episodes.length} Episodes`;
    resultDetails.append(resultSummary);
    const resultBody = globalThis.document.createElement("div");
    resultBody.className = "evaluation-result-body";
    const meta = globalThis.document.createElement("p");
    meta.className = "control-hint comparison-meta";
    meta.textContent = `${zh ? "配对 Seed" : "Paired Seeds"}: ${result.seeds[0]}–${result.seeds.at(-1)} · ${result.episodes_per_strategy} ${zh ? "次/策略" : "runs/strategy"}`;
    const table = globalThis.document.createElement("table");
    table.className = "strategy-comparison-table";
    const header = table.createTHead().insertRow();
    for (const label of (zh
      ? ["策略", "样本", "成功率", "碰撞率", "超时率", "平均奖励", "平均速度", "舒适度"]
      : ["Strategy", "N", "Success rate", "Collision rate", "Timeout rate", "Mean reward", "Mean speed", "Comfort"])) {
      const cell = globalThis.document.createElement("th");
      cell.textContent = label;
      header.append(cell);
    }
    const body = table.createTBody();
    const percent = (value: number): string => `${(value * 100).toFixed(1)}%`;
    for (const aggregate of result.strategies) {
      const row = body.insertRow();
      const strategy = aggregate.strategy.model_version
        ? `${aggregate.strategy.id}\n${aggregate.strategy.version} · model ${aggregate.strategy.model_version}`
        : `${aggregate.strategy.id}\n${aggregate.strategy.version}`;
      const values = [
        strategy,
        String(aggregate.episode_count),
        `${percent(aggregate.rates.success.value)} (${aggregate.rates.success.numerator}/${aggregate.rates.success.denominator})`,
        `${percent(aggregate.rates.collision.value)} (${aggregate.rates.collision.numerator}/${aggregate.rates.collision.denominator})`,
        `${percent(aggregate.rates.timeout.value)} (${aggregate.rates.timeout.numerator}/${aggregate.rates.timeout.denominator})`,
        aggregate.means.episode_reward.toFixed(3),
        `${aggregate.means.average_speed_mps.toFixed(2)} m/s`,
        aggregate.means.comfort_score.toFixed(3),
      ];
      for (const [index, value] of values.entries()) {
        const cell = row.insertCell();
        cell.textContent = value;
        if (index >= 2 && index <= 4) {
          const rate = index === 2 ? aggregate.rates.success : index === 3 ? aggregate.rates.collision : aggregate.rates.timeout;
          cell.title = `95% CI: ${percent(rate.ci95[0])}–${percent(rate.ci95[1])}`;
        }
      }
    }
    const failures = result.episodes.filter((episode) => episode.result !== "merge_success");
    const details = globalThis.document.createElement("details");
    details.className = "evaluation-failures";
    const summary = globalThis.document.createElement("summary");
    summary.textContent = `${zh ? "失败 Episode" : "Failed Episodes"} (${failures.length})`;
    details.append(summary);
    const saveNotice = globalThis.document.createElement("p");
    saveNotice.className = "evaluation-save-notice";
    saveNotice.setAttribute("role", "status");
    saveNotice.hidden = true;
    let noticeTimer: ReturnType<typeof globalThis.setTimeout> | null = null;
    const showSaveNotice = (message: string): void => {
      if (noticeTimer !== null) globalThis.clearTimeout(noticeTimer);
      saveNotice.textContent = message;
      saveNotice.hidden = false;
      noticeTimer = globalThis.setTimeout(() => {
        saveNotice.textContent = "";
        saveNotice.hidden = true;
        noticeTimer = null;
      }, 2000);
    };
    for (const episode of failures) {
      const save = globalThis.document.createElement("button");
      save.type = "button";
      const episodeLabel = `${episode.strategy.id} · Seed ${episode.seed} · ${displayMetricName(episode.result)}`;
      save.textContent = episodeLabel;
      save.addEventListener("click", () => void (async () => {
        try {
          save.disabled = true;
          const replay = await this.#client.getEvaluationReplay(evaluationId, episode.episode_id);
          await this.#client.saveEpisode(replay, `evaluation-${episode.strategy.id}-${episode.seed}`);
          await this.#refreshLibrary();
          showSaveNotice(episode.result === "merge_success"
            ? (zh ? "已保存成功回放" : "Successful replay saved")
            : (zh ? "已保存失败回放" : "Failure replay saved"));
        } catch (error) {
          showSaveNotice(error instanceof Error ? error.message : "Save failed");
        } finally {
          save.disabled = false;
          save.textContent = episodeLabel;
        }
      })());
      details.append(save);
    }
    resultBody.append(meta, table, details, saveNotice);
    resultDetails.append(resultBody);
    status.replaceChildren(resultDetails);
  }

  async #loadSelectedEpisode(): Promise<void> {
    const id = this.#root.querySelector<HTMLSelectElement>('[data-testid="episode-library-list"]')?.value;
    if (!id || !this.#replayController) return;
    try {
      const replay = await this.#client.getEpisode(id);
      this.#replayController.load(replay as unknown as ReplayDocument<HighwaySnapshot>);
      this.#setReplayStatus(this.#state.view().language === "zh-CN" ? `已加载 ${id}，可播放或单步` : `${id} loaded; ready to play or step`);
    } catch (error) {
      this.#setReplayStatus(error instanceof Error ? error.message : "Episode load failed");
    }
  }

  async #exportSelectedEpisode(): Promise<void> {
    const id = this.#root.querySelector<HTMLSelectElement>('[data-testid="episode-library-list"]')?.value;
    if (!id) return this.#setReplayStatus(this.#state.view().language === "zh-CN" ? "请先选择 Episode" : "Select an Episode first");
    try {
      const bytes = await this.#client.exportEpisode(id);
      const blob = new Blob([bytes.buffer as ArrayBuffer], { type: "application/json" });
      const link = globalThis.document.createElement("a");
      link.href = URL.createObjectURL(blob); link.download = `${id}.json`; link.click(); URL.revokeObjectURL(link.href);
      this.#setReplayStatus(this.#state.view().language === "zh-CN" ? "Episode 已导出" : "Episode exported");
    } catch (error) {
      this.#setReplayStatus(error instanceof Error ? error.message : "Episode export failed");
    }
  }

  #syncReplayDom(state?: SceneRenderState): void {
    const replayView = this.#replayController?.view();
    const index = state?.index ?? replayView?.timelineIndex;
    const length = state?.length ?? replayView?.timelineLength;
    const timeline = this.#root.querySelector<HTMLInputElement>('[data-testid="replay-timeline"]');
    if (timeline && index !== undefined && length !== undefined) {
      timeline.max = String(Math.max(0, length - 1));
      timeline.value = String(index);
    }
  }

  #syncConfigurationDom(): void {
    const view = this.#state.view();
    const preset = this.#root.querySelector<HTMLSelectElement>('[data-testid="preset"]');
    const quality = this.#root.querySelector<HTMLSelectElement>('[data-testid="quality"]');
    const lanes = this.#root.querySelector<HTMLSelectElement>('[data-testid="lanes-count"]');
    if (preset && view.selectedPreset) preset.value = view.selectedPreset;
    if (quality) quality.value = view.requestedQuality;
    if (lanes) lanes.value = String(view.lanesCount);
    if (this.#lastEffectiveConfig) {
      const config = this.#lastEffectiveConfig;
      const valueAt = (path: string): unknown => path.split(".").reduce<unknown>((current, key) => current && typeof current === "object" ? (current as Record<string, unknown>)[key] : undefined, config);
      const paths: Record<string, string> = {
        seed: "seed", vehicles_count: "traffic.vehicles_count", density: "traffic.density", initial_speed_mps: "ego.initial_speed_mps",
        closed_lane_index: "construction.closed_lane_index", zone_start_m: "construction.zone_start_m", zone_end_m: "construction.zone_end_m",
        min_speed_mps: "traffic.min_speed_mps", max_speed_mps: "traffic.max_speed_mps", aggressive_fraction: "traffic.aggressive_fraction", duration_s: "simulation.duration_s",
      };
      for (const key of ["collision", "speed", "safe_lane", "lane_change", "merge_success", "ttc", "comfort"] as const) paths[`reward.${key}`] = `reward.${key}`;
      for (const input of this.#root.querySelectorAll<HTMLInputElement>("[data-config]")) {
        const key = input.dataset.config ?? "";
        const value = valueAt(paths[key] ?? key);
        if (value !== undefined && value !== null) input.value = String(value);
      }
      const summary = this.#root.querySelector<HTMLElement>('[data-testid="config-summary"]');
      if (summary) summary.textContent = `${view.language === "zh-CN" ? "生效配置" : "Effective config"} · ${this.#snapshot?.config_digest ?? "—"}`;
      const preview = this.#root.querySelector<HTMLElement>('[data-testid="effective-config"]');
      if (preview) preview.textContent = JSON.stringify(this.#lastEffectiveConfig, null, 2);
    }
  }

  #updateTelemetry(snapshot: HighwaySnapshot): void {
    const telemetry = formatSnapshotTelemetry(snapshot);
    const set = (selector: string, value: string) => { const element = this.#root.querySelector(selector); if (element) element.textContent = value; };
    set('[data-testid="speed"]', telemetry.speed);
    set('[data-testid="lane"]', String(snapshot.ego.lane_index));
    const actionLabel: Record<string, string> = { IDLE: "IDEL", LANE_LEFT: "LEFT", LANE_RIGHT: "RIGHT" };
    set('[data-testid="action"]', snapshot.last_action ? (actionLabel[snapshot.last_action] ?? snapshot.last_action) : "—");
    set('[data-testid="ttc"]', telemetry.ttc);
    set('[data-testid="reward-total"]', telemetry.rewardTotal);
    const terminalStatus = snapshot.status.termination_reason ?? (snapshot.status.terminated || snapshot.status.truncated ? "ended" : "running");
    set('[data-testid="terminal-status"]', displayMetricName(terminalStatus));
    const decisionReason = typeof this.#lastDecision?.reason === "string" ? String(this.#lastDecision.reason) : null;
    const explanation = decisionReason ?? (this.#lastManualAction && Date.now() < this.#lastManualAction.until && snapshot.last_action === "IDLE"
      ? `${this.#lastManualAction.action} · ${snapshot.status.termination_reason ?? "running"}`
      : telemetry.explanation);
    if (this.#lastManualAction && Date.now() >= this.#lastManualAction.until) this.#lastManualAction = null;
    set('[data-testid="decision-explanation"]', explanation);
    const components = this.#root.querySelector<HTMLElement>('[data-testid="reward-components"]');
    if (components) {
      const configuredWeights = this.#lastEffectiveConfig?.reward;
      const weights = configuredWeights && typeof configuredWeights === "object" ? configuredWeights as Record<string, unknown> : {};
      const signed = (value: number): string => value.toFixed(3);
      const weightedComponents = Object.entries(snapshot.reward.components)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([name, value]) => {
          const configured = Number(weights[name]);
          const weight = Number.isFinite(configured) ? configured : 1;
          return [name, signed(value * weight)] as const;
        });
      const nodes = weightedComponents.flatMap(([name, value]) => {
        const term = globalThis.document.createElement("dt");
        term.textContent = displayMetricName(name);
        const description = globalThis.document.createElement("dd");
        description.textContent = value;
        return [term, description];
      });
      components.replaceChildren(...nodes);
    }
  }

  #syncLifecycleDom(): void {
    const view = this.#state.view();
    const set = (testId: string, value: string) => {
      const element = this.#root.querySelector(`[data-testid="${testId}"]`);
      if (element) element.textContent = value;
    };
    set("connection-status", view.connectionStatus);
    set("session-status", view.sessionStatus);
    set("simulation-status", view.simulationStatus);
    const disabled = view.connectionStatus !== "connected" || view.sessionStatus !== "active";
    this.#root.querySelectorAll<HTMLButtonElement>("[data-control]").forEach((button) => {
      button.disabled = disabled || (button.dataset.command === "simulation.step" && view.simulationStatus !== "paused");
    });
    this.#syncRateDom();
  }

  #syncRateDom(): void {
    const rate = this.#state.view().playbackRate;
    const selector = this.#root.querySelector<HTMLSelectElement>("[data-rate-select]");
    if (selector) selector.value = String(rate);
  }

  dispose(): void {
    this.#stopReplayTimer();
    const canvas = this.#root.querySelector<HTMLCanvasElement>('[data-testid="highway-canvas"]');
    if (canvas && this.#webglLostHandler) canvas.removeEventListener("highwaypilot:webgl-lost", this.#webglLostHandler);
    if (canvas && this.#webglRestoredHandler) canvas.removeEventListener("highwaypilot:webgl-restored", this.#webglRestoredHandler);
    this.#webglLostHandler = null;
    this.#webglRestoredHandler = null;
    this.#scene?.dispose();
    this.#client.close();
  }
}
