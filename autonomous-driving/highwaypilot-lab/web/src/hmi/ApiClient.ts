import { InMemoryResumeCredential, type BusinessCommand } from "../features/session/sessionControls.js";
import type { HighwaySnapshot } from "./renderer/HighwayScene.js";
import type { StrategyEvaluationJob } from "../features/strategy/evaluationPresenter.js";


export type SessionCreated = {
  protocol_version: "highwaypilot-ws/v1";
  session_id: string;
  resume_token: string;
  connection_status: "connected";
  session_status: "active";
  simulation_status: "paused";
  attachment_epoch: number;
  simulation_generation: number;
  state_seq: number;
  snapshot: HighwaySnapshot;
  effective_config?: Record<string, unknown>;
  config_digest?: string;
};

export type HmiServerEvent = Record<string, unknown> & {
  type?: string;
  snapshot?: HighwaySnapshot;
  connection_status?: string;
  session_status?: string;
  simulation_status?: string;
  playback_rate?: number;
  attachment_epoch?: number;
  simulation_generation?: number;
  state_seq?: number;
  decision?: Record<string, unknown>;
};

export type EpisodeLibraryItem = {
  episode_id: string;
  name: string;
  canonical_bytes: number;
  created_at: string;
};

type Fetcher = typeof fetch;
type SocketFactory = (url: string) => WebSocket;

type PendingCommand = {
  command: BusinessCommand;
  retries: number;
};

export class ApiClient {
  readonly #origin: string;
  readonly #fetch: Fetcher;
  readonly #socketFactory: SocketFactory;
  readonly #credential = new InMemoryResumeCredential();
  #socket: WebSocket | null = null;
  #sessionId: string | null = null;
  #attachmentEpoch = 0;
  #simulationGeneration = 0;
  #stateSeq = 0;
  #pending = new Map<string, PendingCommand>();
  #resumeTimer: number | null = null;
  #intentionalClose = false;
  #eventHandler: (event: HmiServerEvent) => void = () => {};
  #connectedHandler: () => void = () => {};

  constructor(
    origin = globalThis.location?.origin,
    fetcher: Fetcher = globalThis.fetch.bind(globalThis),
    socketFactory: SocketFactory = (url) => new WebSocket(url),
  ) {
    if (!/^http:\/\/127\.0\.0\.1:[1-9][0-9]{0,4}$/.test(origin)) {
      throw new Error("HMI API origin must be the exact IPv4-loopback service origin");
    }
    this.#origin = origin;
    this.#fetch = fetcher;
    this.#socketFactory = socketFactory;
  }

  onEvent(handler: (event: HmiServerEvent) => void): void {
    this.#eventHandler = handler;
  }

  onConnected(handler: () => void): void {
    this.#connectedHandler = handler;
  }

  async loadPreset(presetId: string): Promise<Record<string, unknown>> {
    const response = await this.#fetch(`${this.#origin}/api/presets/${encodeURIComponent(presetId)}`);
    if (!response.ok) throw new Error("PRESET_NOT_FOUND");
    return response.json() as Promise<Record<string, unknown>>;
  }

  async createSession(config: Record<string, unknown>): Promise<SessionCreated> {
    const response = await this.#fetch(`${this.#origin}/api/sessions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ config }),
      credentials: "omit",
      cache: "no-store",
    });
    if (!response.ok) {
      const failure = await response.json() as { error?: { code?: string; message?: string } };
      throw new Error(failure.error?.message ?? failure.error?.code ?? "SESSION_CREATE_FAILED");
    }
    const created = await response.json() as SessionCreated;
    this.#sessionId = created.session_id;
    this.#attachmentEpoch = created.attachment_epoch;
    this.#simulationGeneration = created.simulation_generation;
    this.#stateSeq = created.state_seq;
    this.#credential.replace(created.resume_token);
    delete (created as Partial<SessionCreated>).resume_token;
    return { ...created, resume_token: "[IN_MEMORY_ONLY]" };
  }

  async validateConfig(config: Record<string, unknown>): Promise<Record<string, unknown>> {
    const response = await this.#fetch(`${this.#origin}/api/config/validate`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(config), credentials: "omit",
    });
    const body = await response.json() as { effective_config?: Record<string, unknown>; error?: { message?: string } };
    if (!response.ok || !body.effective_config) throw new Error(body.error?.message ?? "INVALID_CONFIG");
    return body.effective_config;
  }

  async getEpisode(episodeId: string): Promise<Record<string, unknown>> {
    const response = await this.#fetch(`${this.#origin}/api/episodes/${encodeURIComponent(episodeId)}`, { credentials: "omit", cache: "no-store" });
    if (!response.ok) throw new Error("EPISODE_LOAD_FAILED");
    return response.json() as Promise<Record<string, unknown>>;
  }

  async compareStrategies(config: Record<string, unknown>, maxSteps = 500): Promise<Record<string, unknown>> {
    const response = await this.#fetch(`${this.#origin}/api/strategy-comparisons`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ config, manual_actions: Array.from({ length: maxSteps }, () => "IDLE"), max_steps: maxSteps }),
      credentials: "omit",
    });
    const body = await response.json() as Record<string, unknown>;
    if (!response.ok) throw new Error(String((body.error as { message?: unknown } | undefined)?.message ?? "COMPARISON_FAILED"));
    return body;
  }

  async startStrategyEvaluation(
    config: Record<string, unknown>,
    episodesPerStrategy: number,
    seedStart: number,
  ): Promise<StrategyEvaluationJob> {
    const response = await this.#fetch(`${this.#origin}/api/strategy-evaluations`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        config,
        episodes_per_strategy: episodesPerStrategy,
        seed_start: seedStart,
        strategies: ["random", "qualified_rule", "construction_dqn_onnx"],
        max_steps: 500,
      }),
      credentials: "omit",
    });
    const body = await response.json() as StrategyEvaluationJob & { error?: { message?: string } };
    if (!response.ok) throw new Error(body.error?.message ?? "EVALUATION_FAILED");
    return body;
  }

  async getStrategyEvaluation(evaluationId: string): Promise<StrategyEvaluationJob> {
    const response = await this.#fetch(`${this.#origin}/api/strategy-evaluations/${encodeURIComponent(evaluationId)}`, {
      credentials: "omit",
      cache: "no-store",
    });
    const body = await response.json() as StrategyEvaluationJob & { error?: { message?: string } };
    if (!response.ok) throw new Error(body.error?.message ?? "EVALUATION_LOAD_FAILED");
    return body;
  }

  async cancelStrategyEvaluation(evaluationId: string): Promise<StrategyEvaluationJob> {
    const response = await this.#fetch(`${this.#origin}/api/strategy-evaluations/${encodeURIComponent(evaluationId)}`, {
      method: "DELETE",
      credentials: "omit",
    });
    const body = await response.json() as StrategyEvaluationJob & { error?: { message?: string } };
    if (!response.ok) throw new Error(body.error?.message ?? "EVALUATION_CANCEL_FAILED");
    return body;
  }

  async getEvaluationReplay(evaluationId: string, episodeId: string): Promise<Record<string, unknown>> {
    const response = await this.#fetch(
      `${this.#origin}/api/strategy-evaluations/${encodeURIComponent(evaluationId)}/episodes/${encodeURIComponent(episodeId)}/replay`,
      { credentials: "omit", cache: "no-store" },
    );
    const body = await response.json() as Record<string, unknown> & { error?: { message?: string } };
    if (!response.ok) throw new Error(body.error?.message ?? "EVALUATION_REPLAY_FAILED");
    return body;
  }

  async saveEpisode(replay: Record<string, unknown>, name?: string): Promise<EpisodeLibraryItem> {
    const response = await this.#fetch(`${this.#origin}/api/episodes`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ replay, ...(name ? { name } : {}) }),
      credentials: "omit",
    });
    const body = await response.json() as EpisodeLibraryItem & { error?: { message?: string } };
    if (!response.ok) throw new Error(body.error?.message ?? "EPISODE_SAVE_FAILED");
    return body;
  }

  async listEpisodes(): Promise<{ items: EpisodeLibraryItem[]; quota: Record<string, number> }> {
    const response = await this.#fetch(`${this.#origin}/api/episodes`, { credentials: "omit", cache: "no-store" });
    if (!response.ok) throw new Error("EPISODE_LIST_FAILED");
    return response.json() as Promise<{ items: EpisodeLibraryItem[]; quota: Record<string, number> }>;
  }

  async saveSessionEpisode(name?: string): Promise<EpisodeLibraryItem> {
    if (this.#sessionId === null) throw new Error("NO_ACTIVE_SESSION");
    const response = await this.#fetch(`${this.#origin}/api/sessions/${encodeURIComponent(this.#sessionId)}/episodes/save`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(name ? { name } : {}), credentials: "omit",
    });
    if (!response.ok) throw new Error("EPISODE_SAVE_FAILED");
    return response.json() as Promise<EpisodeLibraryItem>;
  }

  async exportEpisode(episodeId: string, gzip = false): Promise<Uint8Array> {
    const response = await this.#fetch(`${this.#origin}/api/episodes/${encodeURIComponent(episodeId)}/export?gzip_transport=${gzip ? "true" : "false"}`, { credentials: "omit" });
    if (!response.ok) throw new Error("EPISODE_EXPORT_FAILED");
    return new Uint8Array(await response.arrayBuffer());
  }

  async deleteEpisode(episodeId: string): Promise<void> {
    const response = await this.#fetch(`${this.#origin}/api/episodes/${encodeURIComponent(episodeId)}?confirm=true`, { method: "DELETE", credentials: "omit" });
    if (!response.ok) throw new Error("EPISODE_DELETE_FAILED");
  }

  connect(): void {
    if (this.#sessionId === null) throw new Error("NO_ACTIVE_SESSION");
    this.#intentionalClose = false;
    this.#openSocket(false);
  }

  #openSocket(resume: boolean): void {
    if (this.#sessionId === null) return;
    const url = new URL(`/ws/sessions/${encodeURIComponent(this.#sessionId)}`, this.#origin);
    url.protocol = "ws:";
    this.#socket = this.#socketFactory(url.toString());
    this.#socket.onopen = () => {
      if (resume) {
        const token = this.#credential.reveal();
        if (!token) return;
        const attempt = this.#resumeAttempt();
        this.#socket?.send(JSON.stringify({ protocol_version: "highwaypilot-ws/v1", type: "resume.offer", session_id: this.#sessionId, resume_token: token, resume_attempt_id: attempt }));
      } else {
        this.#connectedHandler();
      }
    };
    this.#socket.onmessage = (message) => {
      const event = JSON.parse(String(message.data)) as HmiServerEvent;
      this.#attachmentEpoch = this.#integer(event.attachment_epoch, this.#attachmentEpoch);
      this.#simulationGeneration = this.#integer(event.simulation_generation, this.#simulationGeneration);
      this.#stateSeq = this.#integer(event.state_seq, this.#stateSeq);

      if (event.type === "resume.offer") {
        const token = typeof event.new_resume_token === "string" ? event.new_resume_token : null;
        const attempt = typeof event.resume_attempt_id === "string" ? event.resume_attempt_id : null;
        const offer = typeof event.offer_id === "string" ? event.offer_id : null;
        if (token && attempt && offer) {
          this.#credential.replace(token);
          this.#socket?.send(JSON.stringify({ protocol_version: "highwaypilot-ws/v1", type: "resume.commit", session_id: this.#sessionId, resume_attempt_id: attempt, offer_id: offer }));
        }
      }

      const commandId = typeof event.command_id === "string" ? event.command_id : null;
      if (commandId !== null && event.type === "command.error") {
        const pending = this.#pending.get(commandId);
        const error = event.error as { code?: unknown } | undefined;
        if (pending && error?.code === "STALE_STATE" && pending.retries < 2) {
          this.#pending.delete(commandId);
          this.#sendPending(pending.command, pending.retries + 1);
          return;
        }
      }
      if (commandId !== null && (event.type === "command.result" || event.type === "command.error")) {
        this.#pending.delete(commandId);
      }
      this.#eventHandler(event);
    };
    this.#socket.onclose = () => {
      this.#socket = null;
      if (this.#intentionalClose || this.#resumeTimer !== null) return;
      this.#eventHandler({ type: "resume.pending", connection_status: "disconnected", session_status: "resume_pending" });
      this.#resumeTimer = globalThis.window.setTimeout(() => {
        this.#resumeTimer = null;
        if (this.#credential.reveal() && this.#sessionId) this.#openSocket(true);
      }, 250);
    };
  }

  send(command: BusinessCommand): void {
    if (this.#socket?.readyState !== WebSocket.OPEN || this.#sessionId === null) {
      throw new Error("NO_ACTIVE_CONNECTION");
    }
    this.#sendPending(command, 0);
  }

  #sendPending(command: BusinessCommand, retries: number): void {
    if (this.#socket?.readyState !== WebSocket.OPEN || this.#sessionId === null) {
      this.#eventHandler({
        type: "command.error",
        error: { code: "NO_ACTIVE_CONNECTION", message: "连接尚未建立，控制命令未发送。" },
      });
      return;
    }
    const commandId = globalThis.crypto.randomUUID();
    this.#pending.set(commandId, { command, retries });
    this.#socket.send(JSON.stringify({
      protocol_version: "highwaypilot-ws/v1",
      type: "command",
      session_id: this.#sessionId,
      command_id: commandId,
      attachment_epoch: this.#attachmentEpoch,
      simulation_generation: this.#simulationGeneration,
      expected_state_seq: this.#stateSeq,
      name: command.name === "manual.action" ? "control.action" : command.name,
      payload: command.payload,
    }));
  }

  credentialSummary(): { redacted: true; present: boolean } {
    return this.#credential.toJSON();
  }

  close(): void {
    this.#intentionalClose = true;
    if (this.#resumeTimer !== null) { globalThis.clearTimeout(this.#resumeTimer); this.#resumeTimer = null; }
    this.#socket?.close();
    this.#socket = null;
    this.#pending.clear();
    this.#credential.clear();
  }

  #integer(value: unknown, fallback: number): number {
    return typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : fallback;
  }

  #resumeAttempt(): string {
    const bytes = new Uint8Array(16);
    globalThis.crypto.getRandomValues(bytes);
    let binary = "";
    bytes.forEach((value) => { binary += String.fromCharCode(value); });
    return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
  }
}
