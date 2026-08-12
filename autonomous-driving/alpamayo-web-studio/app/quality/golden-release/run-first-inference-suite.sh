#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $0 --base-url URL --max-first-run-seconds SECONDS --minimum-success-rate RATE --evidence PATH" >&2
}

base_url=""
max_seconds=""
minimum_success_rate=""
evidence_path=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --base-url) base_url="$2"; shift 2 ;;
    --max-first-run-seconds) max_seconds="$2"; shift 2 ;;
    --minimum-success-rate) minimum_success_rate="$2"; shift 2 ;;
    --evidence) evidence_path="$2"; shift 2 ;;
    *) usage; exit 64 ;;
  esac
done

if [[ -z "$base_url" || -z "$max_seconds" || -z "$minimum_success_rate" || -z "$evidence_path" ]]; then
  usage
  exit 64
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fixture_path="$script_dir/../../fixtures/golden-release/authorized-first-inference.json"

node --input-type=module - "$base_url" "$max_seconds" "$minimum_success_rate" "$evidence_path" "$fixture_path" <<'NODE'
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";

const [baseUrl, maxSecondsValue, minimumSuccessRateValue, evidencePath, fixturePath] = process.argv.slice(2);
const maxSeconds = Number(maxSecondsValue);
const minimumSuccessRate = Number(minimumSuccessRateValue);
const suite = JSON.parse(readFileSync(fixturePath, "utf8"));
const policy = suite.measurementPolicy;

function fail(message) {
  throw new Error(message);
}

function assertEligible(sample) {
  const scene = sample?.scene;
  const cameraIds = scene?.cameras?.map((camera) => camera.cameraId);
  const hasFourFrames = scene?.cameras?.every((camera) => Array.isArray(camera.frames) && camera.frames.length === 4);
  const history = scene?.history;
  if (
    sample?.authorization?.status !== "approved" ||
    JSON.stringify(cameraIds) !== JSON.stringify([0, 1, 2, 6]) ||
    !hasFourFrames ||
    history?.positions?.length !== 16 ||
    history?.rotations?.length !== 16 ||
    !scene?.navigationInstruction?.trim()
  ) {
    fail(`Golden release fixture contains an illegal input: ${sample?.sampleId ?? "unknown"}`);
  }
}

if (!Number.isFinite(maxSeconds) || maxSeconds <= 0 || maxSeconds > policy.maxFirstInferenceSeconds) {
  fail(`--max-first-run-seconds must be within 1..${policy.maxFirstInferenceSeconds}`);
}
if (!Number.isFinite(minimumSuccessRate) || minimumSuccessRate < policy.minimumSuccessRate || minimumSuccessRate > 1) {
  fail(`--minimum-success-rate must be within ${policy.minimumSuccessRate}..1`);
}
if (policy.timingStart !== "immediately-before-first-user-submission" || policy.successRateDenominator !== "all-eligible-samples" || policy.illegalInputHandling !== "excluded-before-submission") {
  fail("Golden release measurement policy is not the approved policy");
}

const samples = suite.eligibleSamples;
if (!Array.isArray(samples) || samples.length === 0) fail("Golden release suite has no eligible samples");
samples.forEach(assertEligible);

const endpoint = new URL(suite.submission.path, baseUrl).toString();
const results = [];
const terminalSuccess = new Set(["success", "succeeded", "completed"]);
const terminalFailure = new Set(["failed", "cancelled", "canceled", "rejected"]);
const delay = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));
for (const sample of samples) {
  // The timing start is immediately-before-first-user-submission, never page load or runner startup.
  const startedAt = new Date().toISOString();
  const started = performance.now();
  let response;
  let responseStatus = "request-error";
  try {
    response = await fetch(endpoint, {
      method: suite.submission.method,
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ goldenReleaseSampleId: sample.sampleId, scene: sample.scene }),
    });
    let body = await response.json().catch(() => ({}));
    responseStatus = String(body.status ?? body.state ?? (response.ok ? "accepted" : "rejected")).toLowerCase();
    const runId = body.runId ?? body.id;
    while (response.ok && runId && !terminalSuccess.has(responseStatus) && !terminalFailure.has(responseStatus) && performance.now() - started < maxSeconds * 1000) {
      await delay(250);
      response = await fetch(`${endpoint}/${encodeURIComponent(String(runId))}`);
      body = await response.json().catch(() => ({}));
      responseStatus = String(body.status ?? body.state ?? (response.ok ? "accepted" : "rejected")).toLowerCase();
    }
  } catch {
    responseStatus = "request-error";
  }
  const elapsedSeconds = Number(((performance.now() - started) / 1000).toFixed(3));
  const succeeded = response?.ok === true && terminalSuccess.has(responseStatus) && elapsedSeconds <= maxSeconds;
  results.push({ sampleId: sample.sampleId, startedAt, elapsedSeconds, outcome: succeeded ? "success" : "failure", responseStatus });
}

const successCount = results.filter((result) => result.outcome === "success").length;
const successRate = successCount / samples.length;
const evidence = {
  schemaVersion: "first-run-evidence.v1",
  suiteId: suite.suiteId,
  measurementPolicy: {
    timingStart: "immediately-before-first-user-submission",
    successRateDenominator: "all-eligible-samples",
    illegalInputHandling: "excluded-before-submission",
    maxFirstInferenceSeconds: maxSeconds,
    minimumSuccessRate,
  },
  denominator: samples.length,
  successCount,
  successRate,
  results,
};

mkdirSync(path.dirname(evidencePath), { recursive: true });
writeFileSync(evidencePath, `${JSON.stringify(evidence, null, 2)}\n`, "utf8");
if (successRate < minimumSuccessRate || results.some((result) => result.elapsedSeconds > maxSeconds)) process.exitCode = 1;
NODE
