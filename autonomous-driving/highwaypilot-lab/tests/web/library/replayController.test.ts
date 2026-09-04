import { describe, expect, it, vi } from "vitest";

import {
  ReplayController,
  type ReplayDocument,
  type SceneRenderer,
} from "../../../web/src/features/replay/replayController.ts";


function replay(): ReplayDocument<{ time: number }> {
  return {
    schema_version: "highwaypilot-replay/v1",
    episode_id: "episode-001",
    initial_frame: { time: 0 },
    actions: [
      { index: 0, action: "IDLE", frame: { time: 1 }, reward: { speed: 1 } },
      { index: 1, action: "FASTER", frame: { time: 2 }, reward: { speed: 2 } },
    ],
  };
}


describe("ReplayController", () => {
  it("reuses the injected Three.js scene seam and distinguishes historical state", () => {
    const render = vi.fn<SceneRenderer<{ time: number }>["render"]>();
    const scene = { render };
    const controller = new ReplayController(scene);

    controller.load(replay());

    expect(controller.view()).toEqual({
      mode: "historical",
      playback: "paused",
      episodeId: "episode-001",
      timelineIndex: 0,
      timelineLength: 3,
      canStepBackward: false,
      canStepForward: true,
    });
    expect(render).toHaveBeenLastCalledWith({ time: 0 }, { mode: "historical", index: 0, length: 3 });
  });

  it("supports start, pause, step, seek, and timeline boundaries", () => {
    const scene = { render: vi.fn() };
    const controller = new ReplayController(scene);
    controller.load(replay());

    controller.start();
    expect(controller.view().playback).toBe("playing");
    expect(controller.tick()).toBe(true);
    expect(controller.view().timelineIndex).toBe(1);
    controller.pause();
    expect(controller.view().playback).toBe("paused");
    expect(controller.step(1)).toBe(true);
    expect(controller.view().timelineIndex).toBe(2);
    expect(controller.tick()).toBe(false);
    expect(controller.view().playback).toBe("paused");
    expect(controller.seek(0)).toBe(true);
    expect(controller.step(-1)).toBe(false);
    expect(() => controller.seek(3)).toThrow("timeline index");
  });

  it("returns the same scene seam to live mode without retaining replay controls", () => {
    const scene = { render: vi.fn() };
    const controller = new ReplayController(scene);
    controller.load(replay());
    controller.returnToLive({ time: 99 });

    expect(controller.view()).toEqual({
      mode: "live",
      playback: "paused",
      episodeId: null,
      timelineIndex: 0,
      timelineLength: 0,
      canStepBackward: false,
      canStepForward: false,
    });
    expect(scene.render).toHaveBeenLastCalledWith(
      { time: 99 },
      { mode: "live", index: 0, length: 0 },
    );
  });
});
