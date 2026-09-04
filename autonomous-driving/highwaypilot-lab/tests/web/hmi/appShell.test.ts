import { describe, expect, it } from "vitest";

import { formatSnapshotTelemetry, renderHmiShell } from "../../../web/src/hmi/App.js";
import { HmiState } from "../../../web/src/hmi/HmiState.js";
import type { HighwaySnapshot } from "../../../web/src/hmi/renderer/HighwayScene.js";


describe("HMI application shell", () => {
  it("renders the complete Chinese user journey around a real canvas", () => {
    const state = new HmiState();
    const html = renderHmiShell(state.view(), state.copy());

    expect(html).toContain('lang="zh-CN"');
    expect(html).toContain('data-testid="highway-canvas"');
    expect(html).toContain('data-camera="follow"');
    expect(html).toContain('data-camera="top"');
    expect(html).toContain('data-camera="free"');
    expect(html).toContain("连接状态");
    expect(html).toContain("会话状态");
    expect(html).toContain("仿真状态");
    expect(html).toContain("奖励分解");
    expect(html).toContain("决策解释");
    expect(html).toContain("Episode 与回放");
    expect(html).toContain('data-testid="replay-timeline"');
    expect(html).toContain("危险切入");
    expect(html).toContain("不会自动运行");
    expect(html).toContain('data-action="scene-reset"');
    expect(html).toContain('placeholder="整数"');
    expect(html).toContain('placeholder="0–50"');
    expect(html).toContain('placeholder="0–3"');
    expect(html).toContain('placeholder=">120"');
    expect(html).toContain('placeholder="1–300"');
    expect(html).toContain('data-config="reward.safe_lane"');
    expect(html).toContain('class="strategy-comparison"');
    expect(html).toContain('data-action="evaluate"');
    expect(html).toContain('data-testid="evaluation-count"');
    expect(html).toContain('data-testid="evaluation-status"');
  });

  it("renders explicit English copy after language switching", () => {
    const state = new HmiState();
    state.setLanguage("en-US");

    const html = renderHmiShell(state.view(), state.copy());

    expect(html).toContain('lang="en-US"');
    expect(html).toContain("Start session");
    expect(html).toContain("Connection");
    expect(html).toContain("Episode & Replay");
  });

  it("presents every Python-authoritative reward component and terminal state", () => {
    const snapshot: HighwaySnapshot = {
      schema_version: "simulation-snapshot/v1",
      authority: "python",
      road: { lanes_count: 3, lane_width_m: 4, length_m: 1000, speed_limit_mps: 30 },
      construction: {
        side: "right",
        closed_lane_index: 2,
        target_lane_index: 1,
        zone_start_m: 260,
        zone_end_m: 340,
        authoritative_merge_action: "LANE_LEFT",
      },
      ego: {
        vehicle_id: "ego",
        position_m: { x: 280, y: 8 },
        speed_mps: 18.25,
        heading_rad: 0,
        lane_index: 2,
        target_lane_index: 1,
        crashed: true,
        scenario_event: false,
      },
      vehicles: [],
      objects: [],
      reward: {
        total: -1.125,
        components: { progress: 0.5, collision: -2, comfort: 0.375 },
      },
      safety: { min_ttc_s: 1.234, collision: true },
      status: { terminated: true, truncated: false, termination_reason: "collision" },
      last_action: "SLOWER",
      available_actions: [],
    };

    expect(formatSnapshotTelemetry(snapshot)).toEqual({
      speed: "18.3 m/s",
      ttc: "1.23 s",
      rewardTotal: "-1.125",
      rewardComponents: [
        ["collision", "-2.000"],
        ["comfort", "0.375"],
        ["progress", "0.500"],
      ],
      explanation: "SLOWER · collision",
    });
  });
});
