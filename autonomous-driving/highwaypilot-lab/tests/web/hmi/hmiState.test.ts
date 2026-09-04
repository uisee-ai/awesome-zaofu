import { describe, expect, it } from "vitest";

import {
  HmiState,
  QUALITY_PROFILES,
  assessWebGLCapability,
} from "../../../web/src/hmi/HmiState.js";


describe("HmiState", () => {
  it("starts in Chinese with onboarding, follow camera, and frozen medium quality", () => {
    const state = new HmiState();

    expect(state.view()).toMatchObject({
      language: "zh-CN",
      onboardingVisible: true,
      cameraMode: "follow",
      requestedQuality: "medium",
      effectiveQuality: "medium",
      connectionStatus: "disconnected",
      sessionStatus: "none",
      simulationStatus: "paused",
    });
    expect(QUALITY_PROFILES.medium).toEqual({
      pixelRatioCap: 1.5,
      antialias: true,
      shadows: false,
      trajectoryPoints: 160,
    });
  });

  it("keeps connection, session, and simulation lifecycle states orthogonal", () => {
    const state = new HmiState();

    state.updateLifecycle({ connectionStatus: "connected" });
    expect(state.view()).toMatchObject({
      connectionStatus: "connected",
      sessionStatus: "none",
      simulationStatus: "paused",
    });
    state.updateLifecycle({ sessionStatus: "active", simulationStatus: "playing" });
    expect(state.view()).toMatchObject({
      connectionStatus: "connected",
      sessionStatus: "active",
      simulationStatus: "playing",
    });
    state.updateLifecycle({ connectionStatus: "disconnected", simulationStatus: "paused" });
    expect(state.view()).toMatchObject({
      connectionStatus: "disconnected",
      sessionStatus: "active",
      simulationStatus: "paused",
    });
  });

  it("switches language explicitly and never starts simulation when loading onboarding preset", () => {
    const state = new HmiState();

    state.setLanguage("en-US");
    state.loadStandardPreset();

    expect(state.view()).toMatchObject({
      language: "en-US",
      onboardingVisible: false,
      selectedPreset: "normal-v1",
      simulationStatus: "paused",
    });
    expect(state.copy().start).toBe("Start session");
  });

  it("falls back to low quality with structured feedback when WebGL2 is unavailable", () => {
    const state = new HmiState();
    state.setQuality("high");
    state.applyWebGLAssessment(assessWebGLCapability(null));

    expect(state.view()).toMatchObject({
      requestedQuality: "high",
      effectiveQuality: "low",
      rendererAvailable: false,
      notice: {
        code: "WEBGL2_UNAVAILABLE",
        severity: "error",
      },
    });
  });

  it("downgrades a weak GPU without describing an unmeasured performance budget", () => {
    const state = new HmiState();
    state.setQuality("high");
    state.applyWebGLAssessment({ available: true, weakGpu: true, renderer: "WebGL 2" });

    expect(state.view()).toMatchObject({
      effectiveQuality: "low",
      rendererAvailable: true,
      notice: {
        code: "WEAK_GPU_FALLBACK",
        severity: "warning",
      },
    });
    expect(state.view().notice?.message).not.toMatch(/fps|帧率|ms|毫秒/i);
  });
});
