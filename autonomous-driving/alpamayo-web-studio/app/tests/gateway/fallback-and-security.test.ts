import assert from "node:assert/strict";
import test from "node:test";

import {
  AlpamayoGateway,
  GatewayUnavailableError,
  type GatewayFetch,
} from "../../backend/studio/gateway/alpamayo-gateway.js";
import { modelStatus } from "../../backend/studio/api/model/status.js";

function response(status: number, body: unknown = {}): { status: number; json(): Promise<unknown> } {
  return { status, async json() { return body; } };
}

function gateway(fetch: GatewayFetch): AlpamayoGateway {
  return new AlpamayoGateway(
    {
      litellm: {
        baseUrl: "http://litellm-service.loshu-workspace.svc.cluster.local",
        model: "alpamayo-vqa",
        apiKey: "secret-must-not-leak",
      },
      kserve: {
        baseUrl: "http://alpamayo-1-5-predictor.loshu.svc.cluster.local",
        model: "alpamayo-vqa",
      },
    },
    fetch,
  );
}

test("gateway prefers a ready LiteLLM upstream for inference", async () => {
  const requests: Array<{ url: string; headers?: Record<string, string> }> = [];
  const fetch: GatewayFetch = async (url, init = {}) => {
    requests.push({ url, headers: init.headers });
    return response(200, { choices: [{ message: { content: "safe response" } }] });
  };

  const result = await gateway(fetch).enqueue({ messages: [{ role: "user", content: "describe scene" }] });

  assert.equal(result.upstream, "litellm");
  assert.deepEqual(result.response, { choices: [{ message: { content: "safe response" } }] });
  assert.deepEqual(requests.map(({ url }) => url), [
    "http://litellm-service.loshu-workspace.svc.cluster.local/health/readiness",
    "http://litellm-service.loshu-workspace.svc.cluster.local/v1/chat/completions",
  ]);
  assert.equal(requests[1]?.headers?.authorization, "Bearer secret-must-not-leak");
});

test("gateway falls back to KServe when LiteLLM readiness fails", async () => {
  const requests: string[] = [];
  const fetch: GatewayFetch = async (url) => {
    requests.push(url);
    if (url.includes("litellm")) return response(503);
    return response(200, { prediction: "fallback response" });
  };

  const result = await gateway(fetch).enqueue({ messages: [{ role: "user", content: "describe scene" }] });

  assert.equal(result.upstream, "kserve");
  assert.deepEqual(result.response, { prediction: "fallback response" });
  assert.deepEqual(requests, [
    "http://litellm-service.loshu-workspace.svc.cluster.local/health/readiness",
    "http://alpamayo-1-5-predictor.loshu.svc.cluster.local/ready",
    "http://alpamayo-1-5-predictor.loshu.svc.cluster.local/v1/chat/completions",
  ]);
});

test("gateway refuses to enqueue when neither upstream is healthy", async () => {
  const requests: string[] = [];
  const fetch: GatewayFetch = async (url) => {
    requests.push(url);
    return response(503);
  };

  await assert.rejects(
    gateway(fetch).enqueue({ messages: [{ role: "user", content: "describe scene" }] }),
    GatewayUnavailableError,
  );
  assert.deepEqual(requests, [
    "http://litellm-service.loshu-workspace.svc.cluster.local/health/readiness",
    "http://alpamayo-1-5-predictor.loshu.svc.cluster.local/ready",
  ]);
});

test("public model status excludes upstream addresses and authorization data", async () => {
  const status = await modelStatus(gateway(async () => response(200)));
  const serialized = JSON.stringify(status);

  assert.deepEqual(status, { ready: true, provider: "litellm" });
  assert.doesNotMatch(serialized, /svc\.cluster\.local|secret-must-not-leak|authorization/i);
});
