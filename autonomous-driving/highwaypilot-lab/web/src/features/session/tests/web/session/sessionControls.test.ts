import { describe, expect, it, vi } from "vitest";

import {
  InMemoryResumeCredential,
  SessionControls,
  applySessionControlView,
  type BusinessCommand,
} from "../../../sessionControls.ts";


describe("SessionControls", () => {
  it("disables every business control and sends zero commands without a valid connection/session", () => {
    const sent: BusinessCommand[] = [];
    const controls = new SessionControls((command) => sent.push(command));

    expect(controls.view()).toEqual({
      connectionStatus: "disconnected",
      sessionStatus: "none",
      simulationStatus: "paused",
      controlsDisabled: true,
      notice: {
        code: "NO_ACTIVE_CONNECTION",
        message: "连接尚未建立，控制命令未发送。",
      },
      sentBusinessCommandCount: 0,
    });
    expect(controls.play()).toEqual({
      accepted: false,
      notice: {
        code: "NO_ACTIVE_CONNECTION",
        message: "连接尚未建立，控制命令未发送。",
      },
    });
    expect(controls.manualAction("LANE_LEFT")).toEqual({
      accepted: false,
      notice: {
        code: "NO_ACTIVE_CONNECTION",
        message: "连接尚未建立，控制命令未发送。",
      },
    });
    expect(sent).toEqual([]);
    expect(controls.view().sentBusinessCommandCount).toBe(0);
  });

  it("keeps connection, session, and simulation status orthogonal and sends all five manual actions", () => {
    const sender = vi.fn<(command: BusinessCommand) => void>();
    const controls = new SessionControls(sender);
    controls.setConnectionStatus("connected");
    controls.setSessionStatus("active");

    for (const action of ["LANE_LEFT", "IDLE", "LANE_RIGHT", "FASTER", "SLOWER"] as const) {
      expect(controls.manualAction(action)).toEqual({ accepted: true, notice: null });
    }
    expect(controls.play()).toEqual({ accepted: true, notice: null });
    controls.setSimulationStatus("playing");
    expect(controls.pause()).toEqual({ accepted: true, notice: null });

    expect(sender.mock.calls.map(([command]) => command)).toEqual([
      { name: "manual.action", payload: { action: "LANE_LEFT" } },
      { name: "manual.action", payload: { action: "IDLE" } },
      { name: "manual.action", payload: { action: "LANE_RIGHT" } },
      { name: "manual.action", payload: { action: "FASTER" } },
      { name: "manual.action", payload: { action: "SLOWER" } },
      { name: "simulation.play", payload: {} },
      { name: "simulation.pause", payload: {} },
    ]);
    expect(controls.view().sentBusinessCommandCount).toBe(7);
  });

  it("keeps resume credentials memory-only and redacts all snapshots and string forms", () => {
    const credential = new InMemoryResumeCredential();
    const token = "secret-resume-token-that-must-never-serialize";
    credential.replace(token);

    expect(credential.reveal()).toBe(token);
    expect(credential.toString()).toBe("[REDACTED]");
    expect(credential.toJSON()).toEqual({ redacted: true, present: true });
    expect(JSON.stringify(credential)).not.toContain(token);

    credential.clear();
    expect(credential.reveal()).toBeNull();
    expect(credential.toJSON()).toEqual({ redacted: true, present: false });
  });

  it("writes disabled controls and the structured prompt to the DOM seam without sending", () => {
    const sent: BusinessCommand[] = [];
    const controls = new SessionControls((command) => sent.push(command));
    const buttons = Array.from({ length: 8 }, () => ({ disabled: false }));
    const notice = { hidden: true, textContent: "", dataset: {} as Record<string, string> };

    applySessionControlView(controls.view(), {
      buttons,
      notice,
    });

    expect(buttons.every((button) => button.disabled)).toBe(true);
    expect(notice).toEqual({
      hidden: false,
      textContent: "连接尚未建立，控制命令未发送。",
      dataset: { code: "NO_ACTIVE_CONNECTION" },
    });
    expect(sent).toEqual([]);
    expect(controls.view().sentBusinessCommandCount).toBe(0);
  });
});
