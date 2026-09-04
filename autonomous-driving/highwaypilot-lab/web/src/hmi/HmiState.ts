export type Language = "zh-CN" | "en-US";
export type CameraMode = "follow" | "top" | "free";
export type QualityLevel = "low" | "medium" | "high";
export type ConnectionStatus = "disconnected" | "connecting" | "connected";
export type SessionStatus = "none" | "active" | "closed" | "resume_pending";
export type SimulationStatus = "paused" | "playing" | "terminated";
export type ControlMode = "manual" | "random" | "qualified_rule" | "onnx";

export const QUALITY_PROFILES = Object.freeze({
  low: Object.freeze({ pixelRatioCap: 1, antialias: false, shadows: false, trajectoryPoints: 80 }),
  medium: Object.freeze({ pixelRatioCap: 1.5, antialias: true, shadows: false, trajectoryPoints: 160 }),
  high: Object.freeze({ pixelRatioCap: 2, antialias: true, shadows: true, trajectoryPoints: 320 }),
} satisfies Record<QualityLevel, Readonly<{
  pixelRatioCap: number;
  antialias: boolean;
  shadows: boolean;
  trajectoryPoints: number;
}>>);

export type WebGLAssessment = {
  available: boolean;
  weakGpu: boolean;
  renderer: string | null;
};

export type HmiNotice = {
  code: "WEBGL2_UNAVAILABLE" | "WEAK_GPU_FALLBACK" | "SESSION_ERROR";
  severity: "warning" | "error";
  message: string;
};

export type HmiView = {
  language: Language;
  onboardingVisible: boolean;
  selectedPreset: string | null;
  lanesCount: number;
  cameraMode: CameraMode;
  requestedQuality: QualityLevel;
  effectiveQuality: QualityLevel;
  rendererAvailable: boolean;
  connectionStatus: ConnectionStatus;
  sessionStatus: SessionStatus;
  simulationStatus: SimulationStatus;
  playbackRate: 0.5 | 1 | 2 | 4;
  controlMode: ControlMode;
  notice: HmiNotice | null;
};

const COPY = {
  "zh-CN": {
    title: "HighwayPilot 驾驶决策实验室",
    start: "启动会话",
    onboarding: "载入标准施工区预设，检查配置后再启动；不会自动运行。",
  },
  "en-US": {
    title: "HighwayPilot Driving Decision Lab",
    start: "Start session",
    onboarding: "Load the standard construction preset, review it, then start. It will not auto-run.",
  },
} as const;

export function assessWebGLCapability(
  context: WebGL2RenderingContext | null,
): WebGLAssessment {
  if (context === null) {
    return { available: false, weakGpu: false, renderer: null };
  }
  const debug = context.getExtension("WEBGL_debug_renderer_info");
  const renderer = debug
    ? String(context.getParameter(debug.UNMASKED_RENDERER_WEBGL))
    : "WebGL 2";
  const weakGpu = /swiftshader|llvmpipe|software/i.test(renderer);
  return { available: true, weakGpu, renderer };
}
export class HmiState {
  #view: HmiView = {
    language: "zh-CN",
    onboardingVisible: true,
    selectedPreset: "normal-v1",
    lanesCount: 3,
    cameraMode: "follow",
    requestedQuality: "medium",
    effectiveQuality: "medium",
    rendererAvailable: true,
    connectionStatus: "disconnected",
    sessionStatus: "none",
    simulationStatus: "paused",
    playbackRate: 1,
    controlMode: "manual",
    notice: null,
  };

  view(): Readonly<HmiView> {
    return { ...this.#view, notice: this.#view.notice ? { ...this.#view.notice } : null };
  }

  copy(): (typeof COPY)[Language] {
    return COPY[this.#view.language];
  }

  setLanguage(language: Language): void {
    this.#view.language = language;
  }

  setCameraMode(cameraMode: CameraMode): void {
    this.#view.cameraMode = cameraMode;
  }

  setQuality(quality: QualityLevel): void {
    this.#view.requestedQuality = quality;
    this.#view.effectiveQuality = this.#view.rendererAvailable ? quality : "low";
  }

  setPlaybackRate(rate: 0.5 | 1 | 2 | 4): void {
    this.#view.playbackRate = rate;
  }

  setControlMode(mode: ControlMode): void {
    this.#view.controlMode = mode;
  }

  setPreset(preset: string): void {
    this.#view.selectedPreset = preset;
    this.#view.onboardingVisible = false;
  }

  setLanesCount(lanesCount: number): void {
    if (!Number.isInteger(lanesCount) || lanesCount < 2 || lanesCount > 5) {
      throw new RangeError("lanesCount must be between 2 and 5");
    }
    this.#view.lanesCount = lanesCount;
  }

  loadStandardPreset(): void {
    this.#view.selectedPreset = "normal-v1";
    this.#view.onboardingVisible = false;
    this.#view.simulationStatus = "paused";
  }

  dismissOnboarding(): void {
    this.#view.onboardingVisible = false;
  }

  updateLifecycle(update: Partial<Pick<
    HmiView,
    "connectionStatus" | "sessionStatus" | "simulationStatus"
  >>): void {
    Object.assign(this.#view, update);
  }

  applyWebGLAssessment(assessment: WebGLAssessment): void {
    this.#view.rendererAvailable = assessment.available;
    if (!assessment.available) {
      this.#view.effectiveQuality = "low";
      this.#view.notice = {
        code: "WEBGL2_UNAVAILABLE",
        severity: "error",
        message: "WebGL 2 不可用，三维画布已停用。请启用硬件加速后重试。",
      };
      return;
    }
    if (assessment.weakGpu) {
      this.#view.effectiveQuality = "low";
      this.#view.notice = {
        code: "WEAK_GPU_FALLBACK",
        severity: "warning",
        message: "检测到软件或弱 GPU 渲染器，已降级到低画质。",
      };
      return;
    }
    this.#view.effectiveQuality = this.#view.requestedQuality;
    this.#view.notice = null;
  }

  reportSessionError(message: string): void {
    this.#view.notice = { code: "SESSION_ERROR", severity: "error", message };
  }
}
