import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const appRoot = new URL("../..", import.meta.url);

test("one FastAPI application owns every PRD section 16 public route", () => {
  const main = readFileSync(new URL("backend/studio/app/main.py", appRoot), "utf8");
  const provider = readFileSync(new URL("backend/studio/app/provider.py", appRoot), "utf8");

  assert.equal((main.match(/FastAPI\(/g) ?? []).length, 1);
  for (const route of [
    "/api/health", "/api/model/status", "/api/assets", "/api/scenes",
    "/api/scenes/{scene_id}", "/api/scenes/{scene_id}/runs", "/api/runs",
    "/api/runs/{run_id}", "/api/runs/{run_id}/cancel", "/api/runs/{run_id}/reviews",
    "/api/experiments", "/api/evaluation-sets", "/api/evaluation-runs",
  ]) {
    assert.match(main, new RegExp(route.replace(/[{}]/g, "\\$&").replaceAll("/", "\\/")));
  }
  assert.match(main, /def run_golden_scene/);
  assert.match(main, /def invoke_inference/);
  assert.match(provider, /LITELLM_BASE_URL/);
  assert.match(provider, /LITELLM_API_KEY/);
  assert.match(provider, /LITELLM_MODEL_NAME/);
  assert.match(provider, /\/v1\/chat\/completions/);
  assert.match(provider, /responseSha256/);
  assert.doesNotMatch(main, /"status": "completed",\n\s*"result": \{"summary": "Inference completed"/);
});

test("the public run result binds semantic output to a digest and protected raw-output ref", () => {
  const provider = readFileSync(new URL("backend/studio/app/provider.py", appRoot), "utf8");

  assert.match(provider, /sha256\(encoded_response\)/);
  assert.match(provider, /"responseSha256": digest/);
  assert.match(provider, /"rawOutputRef": raw_output_ref/);
  assert.match(provider, /os\.chmod\(temporary, 0o600\)/);
  assert.doesNotMatch(provider, /"rawProviderResponse"/);
});
