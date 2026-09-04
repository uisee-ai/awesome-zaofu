export type ConnectionStatus = "disconnected" | "connecting" | "connected";
export type SessionStatus = "none" | "active" | "closed" | "resume_pending";
export type SimulationStatus = "paused" | "playing" | "terminated";
export type ManualAction = "LANE_LEFT" | "IDLE" | "LANE_RIGHT" | "FASTER" | "SLOWER";

export interface BusinessCommand {
  name:
    | "manual.action"
    | "control.action"
    | "control.set_mode"
    | "simulation.play"
    | "simulation.pause"
    | "simulation.step"
    | "simulation.reset"
    | "simulation.set_rate";
  payload: Record<string, unknown>;
}

export interface StructuredNotice {
  code: "NO_ACTIVE_CONNECTION" | "NO_ACTIVE_SESSION";
  message: string;
}

export interface CommandAdmission {
  accepted: boolean;
  notice: StructuredNotice | null;
}

export interface SessionControlView {
  connectionStatus: ConnectionStatus;
  sessionStatus: SessionStatus;
  simulationStatus: SimulationStatus;
  controlsDisabled: boolean;
  notice: StructuredNotice | null;
  sentBusinessCommandCount: number;
}

export interface SessionControlDom {
  buttons: Array<{ disabled: boolean }>;
  notice: {
    hidden: boolean;
    textContent: string | null;
    dataset: Record<string, string | undefined>;
  };
}

type Sender = (command: BusinessCommand) => void;


export class SessionControls {
  readonly #sender: Sender;
  #connectionStatus: ConnectionStatus = "disconnected";
  #sessionStatus: SessionStatus = "none";
  #simulationStatus: SimulationStatus = "paused";
  #sentBusinessCommandCount = 0;

  constructor(sender: Sender) {
    this.#sender = sender;
  }

  setConnectionStatus(status: ConnectionStatus): void {
    this.#connectionStatus = status;
  }

  setSessionStatus(status: SessionStatus): void {
    this.#sessionStatus = status;
  }

  setSimulationStatus(status: SimulationStatus): void {
    this.#simulationStatus = status;
  }

  #notice(): StructuredNotice | null {
    if (this.#connectionStatus !== "connected") {
      return {
        code: "NO_ACTIVE_CONNECTION",
        message: "连接尚未建立，控制命令未发送。",
      };
    }
    if (this.#sessionStatus !== "active") {
      return {
        code: "NO_ACTIVE_SESSION",
        message: "当前没有可控制的会话，控制命令未发送。",
      };
    }
    return null;
  }

  #send(command: BusinessCommand): CommandAdmission {
    const notice = this.#notice();
    if (notice !== null) {
      return { accepted: false, notice };
    }
    this.#sender(command);
    this.#sentBusinessCommandCount += 1;
    return { accepted: true, notice: null };
  }

  manualAction(action: ManualAction): CommandAdmission {
    // Keep the public helper compatible with older embedders; ApiClient
    // canonicalizes this alias to control.action on the wire.
    return this.#send({ name: "manual.action", payload: { action } });
  }

  setMode(mode: "manual" | "random" | "qualified_rule" | "onnx"): CommandAdmission {
    return this.#send({ name: "control.set_mode", payload: { mode } });
  }

  play(): CommandAdmission {
    return this.#send({ name: "simulation.play", payload: {} });
  }

  pause(): CommandAdmission {
    return this.#send({ name: "simulation.pause", payload: {} });
  }

  step(): CommandAdmission {
    return this.#send({ name: "simulation.step", payload: {} });
  }

  setRate(rate: 0.5 | 1 | 2 | 4): CommandAdmission {
    return this.#send({ name: "simulation.set_rate", payload: { rate } });
  }

  reset(): CommandAdmission {
    return this.#send({ name: "simulation.reset", payload: {} });
  }

  view(): SessionControlView {
    const notice = this.#notice();
    return {
      connectionStatus: this.#connectionStatus,
      sessionStatus: this.#sessionStatus,
      simulationStatus: this.#simulationStatus,
      controlsDisabled: notice !== null,
      notice,
      sentBusinessCommandCount: this.#sentBusinessCommandCount,
    };
  }
}


export function applySessionControlView(view: SessionControlView, dom: SessionControlDom): void {
  for (const button of dom.buttons) {
    button.disabled = view.controlsDisabled;
  }
  dom.notice.hidden = view.notice === null;
  dom.notice.textContent = view.notice?.message ?? "";
  if (view.notice === null) {
    delete dom.notice.dataset.code;
  } else {
    dom.notice.dataset.code = view.notice.code;
  }
}


export class InMemoryResumeCredential {
  #token: string | null = null;

  replace(token: string): void {
    this.#token = token;
  }

  reveal(): string | null {
    return this.#token;
  }

  clear(): void {
    this.#token = null;
  }

  toString(): string {
    return "[REDACTED]";
  }

  toJSON(): { redacted: true; present: boolean } {
    return { redacted: true, present: this.#token !== null };
  }
}
