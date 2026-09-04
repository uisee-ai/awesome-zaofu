export type ReplayMode = "live" | "historical";
export type PlaybackState = "paused" | "playing";

export interface ReplayAction<TFrame> {
  index: number;
  action: string;
  frame: TFrame;
  reward: Record<string, number>;
}

export interface ReplayDocument<TFrame> {
  schema_version: "highwaypilot-replay/v1";
  episode_id: string;
  initial_frame: TFrame;
  actions: Array<ReplayAction<TFrame>>;
}

export interface SceneRenderState {
  mode: ReplayMode;
  index: number;
  length: number;
}

/** The existing Three.js renderer implements this seam for both live and historical frames. */
export interface SceneRenderer<TFrame> {
  render(frame: TFrame, state: SceneRenderState): void;
}

export interface ReplayView {
  mode: ReplayMode;
  playback: PlaybackState;
  episodeId: string | null;
  timelineIndex: number;
  timelineLength: number;
  canStepBackward: boolean;
  canStepForward: boolean;
}

export class ReplayController<TFrame> {
  readonly #scene: SceneRenderer<TFrame>;
  #mode: ReplayMode = "live";
  #playback: PlaybackState = "paused";
  #episodeId: string | null = null;
  #frames: TFrame[] = [];
  #index = 0;

  constructor(scene: SceneRenderer<TFrame>) {
    this.#scene = scene;
  }

  load(replay: ReplayDocument<TFrame>): void {
    if (replay.schema_version !== "highwaypilot-replay/v1") {
      throw new Error("unsupported replay schema");
    }
    replay.actions.forEach((action, index) => {
      if (action.index !== index) {
        throw new Error("replay action indexes must be contiguous");
      }
    });
    this.#mode = "historical";
    this.#playback = "paused";
    this.#episodeId = replay.episode_id;
    this.#frames = [replay.initial_frame, ...replay.actions.map((action) => action.frame)];
    this.#index = 0;
    this.#render();
  }

  start(): void {
    this.#requireReplay();
    if (this.#index === this.#frames.length - 1) {
      this.#index = 0;
      this.#render();
    }
    this.#playback = "playing";
  }

  pause(): void {
    this.#playback = "paused";
  }

  tick(): boolean {
    if (this.#playback !== "playing") {
      return false;
    }
    const moved = this.step(1);
    if (!moved || this.#index === this.#frames.length - 1) {
      this.#playback = "paused";
    }
    return moved;
  }

  step(direction: -1 | 1 = 1): boolean {
    this.#requireReplay();
    const target = this.#index + direction;
    if (target < 0 || target >= this.#frames.length) {
      return false;
    }
    this.#index = target;
    this.#render();
    return true;
  }

  seek(index: number): boolean {
    this.#requireReplay();
    if (!Number.isInteger(index) || index < 0 || index >= this.#frames.length) {
      throw new RangeError("timeline index is out of bounds");
    }
    if (this.#index === index) {
      return false;
    }
    this.#index = index;
    this.#render();
    return true;
  }

  returnToLive(frame: TFrame): void {
    this.#mode = "live";
    this.#playback = "paused";
    this.#episodeId = null;
    this.#frames = [];
    this.#index = 0;
    this.#scene.render(frame, { mode: "live", index: 0, length: 0 });
  }

  view(): ReplayView {
    const timelineLength = this.#frames.length;
    return {
      mode: this.#mode,
      playback: this.#playback,
      episodeId: this.#episodeId,
      timelineIndex: this.#index,
      timelineLength,
      canStepBackward: this.#mode === "historical" && this.#index > 0,
      canStepForward: this.#mode === "historical" && this.#index < timelineLength - 1,
    };
  }

  #requireReplay(): void {
    if (this.#mode !== "historical" || this.#frames.length === 0) {
      throw new Error("no historical replay is loaded");
    }
  }

  #render(): void {
    this.#scene.render(this.#frames[this.#index]!, {
      mode: "historical",
      index: this.#index,
      length: this.#frames.length,
    });
  }
}
