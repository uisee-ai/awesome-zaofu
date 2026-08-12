export type GatewayProvider = "litellm" | "kserve";

export interface GatewayRequest {
  model?: string;
  messages: unknown[];
  maxTokens?: number;
  temperature?: number;
}

export interface GatewayResponse {
  upstream: GatewayProvider;
  response: unknown;
}

export interface GatewayFetchResponse {
  status: number;
  json(): Promise<unknown>;
}

export interface GatewayRequestInit {
  method?: string;
  headers?: Record<string, string>;
  body?: string;
}

export type GatewayFetch = (url: string, init?: GatewayRequestInit) => Promise<GatewayFetchResponse>;

export interface UpstreamConfig {
  baseUrl: string;
  model: string;
  apiKey?: string;
}

export interface GatewayConfig {
  litellm: UpstreamConfig;
  kserve: UpstreamConfig;
}

interface ResolvedUpstream {
  provider: GatewayProvider;
  config: UpstreamConfig;
  readinessPath: string;
}

export class GatewayUnavailableError extends Error {
  constructor() {
    super("No model upstream is ready; the request was not enqueued.");
    this.name = "GatewayUnavailableError";
  }
}

function internalServiceUrl(value: string): string {
  const url = new URL(value);
  if (
    (url.protocol !== "http:" && url.protocol !== "https:")
    || !url.hostname.endsWith(".svc.cluster.local")
    || url.username !== ""
    || url.password !== ""
  ) {
    throw new Error("Gateway upstreams must use a cluster-internal Service DNS URL.");
  }
  return url.toString().replace(/\/$/, "");
}

function isSuccessful(response: GatewayFetchResponse): boolean {
  return response.status >= 200 && response.status < 300;
}

export class AlpamayoGateway {
  private readonly upstreams: readonly ResolvedUpstream[];

  constructor(config: GatewayConfig, private readonly fetch: GatewayFetch) {
    this.upstreams = [
      {
        provider: "litellm",
        config: { ...config.litellm, baseUrl: internalServiceUrl(config.litellm.baseUrl) },
        readinessPath: "/health/readiness",
      },
      {
        provider: "kserve",
        config: { ...config.kserve, baseUrl: internalServiceUrl(config.kserve.baseUrl) },
        readinessPath: "/ready",
      },
    ];
  }

  async readyProvider(): Promise<GatewayProvider | null> {
    for (const upstream of this.upstreams) {
      if (await this.isReady(upstream)) return upstream.provider;
    }
    return null;
  }

  async enqueue(request: GatewayRequest): Promise<GatewayResponse> {
    for (const upstream of this.upstreams) {
      if (!await this.isReady(upstream)) continue;
      const result = await this.infer(upstream, request);
      if (result !== null) return result;
    }
    throw new GatewayUnavailableError();
  }

  private async isReady(upstream: ResolvedUpstream): Promise<boolean> {
    try {
      return isSuccessful(await this.fetch(`${upstream.config.baseUrl}${upstream.readinessPath}`));
    } catch {
      return false;
    }
  }

  private async infer(upstream: ResolvedUpstream, request: GatewayRequest): Promise<GatewayResponse | null> {
    const headers: Record<string, string> = { "content-type": "application/json" };
    if (upstream.config.apiKey?.trim()) {
      headers.authorization = `Bearer ${upstream.config.apiKey}`;
    }

    try {
      const response = await this.fetch(`${upstream.config.baseUrl}/v1/chat/completions`, {
        method: "POST",
        headers,
        body: JSON.stringify({
          model: request.model ?? upstream.config.model,
          messages: request.messages,
          max_tokens: request.maxTokens,
          temperature: request.temperature,
        }),
      });
      if (!isSuccessful(response)) return null;
      return { upstream: upstream.provider, response: await response.json() };
    } catch {
      return null;
    }
  }
}
