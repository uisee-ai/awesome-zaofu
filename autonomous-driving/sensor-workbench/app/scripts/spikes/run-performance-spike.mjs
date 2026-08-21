import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { cpus, freemem, platform, release, totalmem, type as osType, arch } from "node:os";
import { resolve } from "node:path";

import { chromium } from "@playwright/test";

import {
  buildPerformanceStatistics,
  roundMilliseconds,
  validatePerformanceFixture,
} from "../../src/spikes/performance.mjs";

const appRoot = resolve(import.meta.dirname, "../..");
const fixturePath = resolve(appRoot, "tests/fixtures/golden/performance-fixture.v1.json");
const digestPath = resolve(appRoot, "tests/fixtures/golden/performance-fixture.v1.sha256");
const reportPath = resolve(appRoot, "artifacts/spikes/performance-report.json");
const fixtureBytes = readFileSync(fixturePath);
const fixtureDigest = createHash("sha256").update(fixtureBytes).digest("hex");
const expectedDigestLine = `${fixtureDigest}  performance-fixture.v1.json\n`;
if (readFileSync(digestPath, "utf8") !== expectedDigestLine) throw new Error("performance fixture digest sidecar mismatch");

const fixture = JSON.parse(fixtureBytes.toString("utf8"));
validatePerformanceFixture(fixture);

const benchmarkHtml = `<!doctype html>
<html><body><canvas id="view" width="1280" height="720"></canvas><script>
(() => {
  const state = { points: null, projected: null, checksum: 0 };
  function generator(seed) {
    let value = seed >>> 0;
    return () => {
      value = (Math.imul(value, 1664525) + 1013904223) >>> 0;
      return value / 4294967296;
    };
  }
  function openDataset(pointCount, seed) {
    const start = performance.now();
    const random = generator(seed);
    const points = new Float64Array(pointCount * 3);
    let checksum = 0;
    for (let index = 0; index < pointCount; index += 1) {
      const offset = index * 3;
      points[offset] = (random() - 0.5) * 24;
      points[offset + 1] = (random() - 0.5) * 8;
      points[offset + 2] = 5 + random() * 115;
      checksum += points[offset] * 3 + points[offset + 1] * 5 + points[offset + 2] * 7;
    }
    state.points = points;
    state.checksum = checksum;
    return { elapsed: performance.now() - start, checksum };
  }
  function project(frameOffset, draw) {
    const start = performance.now();
    const points = state.points;
    const projected = new Float32Array((points.length / 3) * 2);
    const cosine = Math.cos(frameOffset);
    const sine = Math.sin(frameOffset);
    let visible = 0;
    for (let offset = 0; offset < points.length; offset += 3) {
      const x = points[offset] * cosine - points[offset + 1] * sine + frameOffset;
      const y = points[offset] * sine + points[offset + 1] * cosine;
      const z = points[offset + 2];
      const target = (offset / 3) * 2;
      projected[target] = 900 * x / z + 640;
      projected[target + 1] = 900 * y / z + 360;
      if (projected[target] >= 0 && projected[target] < 1280 && projected[target + 1] >= 0 && projected[target + 1] < 720) visible += 1;
    }
    state.projected = projected;
    if (draw) {
      const context = document.getElementById('view').getContext('2d');
      context.clearRect(0, 0, 1280, 720);
      context.fillStyle = '#5eead4';
      for (let index = 0; index < projected.length; index += 400) context.fillRect(projected[index], projected[index + 1], 1, 1);
    }
    return { elapsed: performance.now() - start, visible };
  }
  function interact() {
    const start = performance.now();
    let nearestIndex = -1;
    let nearestDistance = Number.POSITIVE_INFINITY;
    for (let index = 0; index < state.projected.length; index += 2) {
      const dx = state.projected[index] - 640;
      const dy = state.projected[index + 1] - 360;
      const distance = dx * dx + dy * dy;
      if (distance < nearestDistance) {
        nearestDistance = distance;
        nearestIndex = index / 2;
      }
    }
    return { elapsed: performance.now() - start, nearestIndex, nearestDistance };
  }
  window.__swbBenchmark = {
    async runCold(workload) {
      const opened = openDataset(workload.point_count, workload.seed);
      const rendered = project(0, true);
      await new Promise((resolve) => requestAnimationFrame(() => resolve()));
      const switched = project(0.015, false);
      const interaction = interact();
      return {
        dataset_open_ms: opened.elapsed,
        first_render_ms: rendered.elapsed,
        frame_switch_ms: switched.elapsed,
        interaction_ms: interaction.elapsed,
        checksum: opened.checksum,
        visible_points: rendered.visible,
        nearest_index: interaction.nearestIndex
      };
    },
    runWarm(iteration) {
      const switched = project(0.015 + iteration * 0.001, false);
      const interaction = interact();
      return {
        frame_switch_ms: switched.elapsed,
        interaction_ms: interaction.elapsed,
        checksum: state.checksum,
        visible_points: switched.visible,
        nearest_index: interaction.nearestIndex
      };
    }
  };
})();
</script></body></html>`;

function roundedMetrics(metrics) {
  return Object.fromEntries(
    Object.entries(metrics).map(([name, value]) => [name, name.endsWith("_ms") ? roundMilliseconds(value) : value]),
  );
}

function storageEnvironment() {
  try {
    const output = execFileSync("lsblk", ["-d", "-J", "-o", "NAME,ROTA,TYPE,SIZE,MODEL"], { encoding: "utf8" });
    return JSON.parse(output).blockdevices.filter((device) => device.type === "disk");
  } catch (error) {
    return [{ status: "unavailable", reason: error instanceof Error ? error.message : String(error) }];
  }
}

function validateDurableReport(candidate, expectedFixture, expectedDigest) {
  if (candidate?.schema_version !== "performance-spike-report.v1") throw new Error("durable report schema mismatch");
  if (candidate.fixture_sha256 !== expectedDigest || candidate.fixture_id !== expectedFixture.fixture_id) {
    throw new Error("durable report fixture binding mismatch");
  }
  if (candidate.capture_mode !== "initial_capture") throw new Error("durable report must preserve the initial capture");
  if (JSON.stringify(candidate.method) !== JSON.stringify({
    workload: expectedFixture.workload,
    browser: expectedFixture.browser,
    states: expectedFixture.states,
    metrics: expectedFixture.metrics,
    network_policy: expectedFixture.network_policy,
  })) {
    throw new Error("durable report method drifted from the fixture");
  }
  if (!Array.isArray(candidate.raw_samples) || candidate.raw_samples.length !== expectedFixture.workload.repeat_count) {
    throw new Error("durable report cold-session list is incomplete");
  }
  for (const [index, sample] of candidate.raw_samples.entries()) {
    if (sample.session !== index + 1 || !Array.isArray(sample.warm) || sample.warm.length !== expectedFixture.workload.warm_repetitions_per_session) {
      throw new Error(`durable report session ${index + 1} has incomplete warm repetitions`);
    }
    for (const metric of ["dataset_open_ms", "first_render_ms", "frame_switch_ms", "interaction_ms"]) {
      if (!Number.isFinite(sample.cold?.[metric])) throw new Error(`durable report session ${index + 1} is missing ${metric}`);
    }
  }
  if (candidate.environment?.chrome?.headless !== false || candidate.environment?.chrome?.channel !== "chrome") {
    throw new Error("durable report did not record headed branded Chrome");
  }
  if (candidate.environment?.fixture_sha256 !== expectedDigest || candidate.environment?.repeat_count !== expectedFixture.workload.repeat_count) {
    throw new Error("durable report environment binding is incomplete");
  }
  if (candidate.candidate_evaluation?.policy !== "record_only_not_a_pass_gate" || candidate.candidate_evaluation?.verdict !== "not_evaluated_as_gate") {
    throw new Error("durable report promoted candidate values into gates");
  }
  if (!Array.isArray(candidate.network?.external_requests) || candidate.network.external_requests.length !== 0) {
    throw new Error("durable report contains external browser requests");
  }
}

const startedAt = new Date().toISOString();
const rawSamples = [];
let observedChromeVersion = "";
const externalRequests = [];

for (let session = 0; session < fixture.workload.repeat_count; session += 1) {
  const sessionStartedAt = new Date().toISOString();
  const launchStart = performance.now();
  const browser = await chromium.launch({ channel: fixture.browser.channel, headless: fixture.browser.headless });
  const launchMs = roundMilliseconds(performance.now() - launchStart);
  observedChromeVersion = browser.version();
  const context = await browser.newContext({ viewport: fixture.workload.viewport });
  const page = await context.newPage();
  page.on("request", (request) => {
    const url = request.url();
    if (!url.startsWith("about:") && !url.startsWith("data:") && !url.startsWith("blob:")) externalRequests.push(url);
  });
  const setupStart = performance.now();
  await page.setContent(benchmarkHtml, { waitUntil: "load" });
  const pageSetupMs = roundMilliseconds(performance.now() - setupStart);
  const cold = roundedMetrics(await page.evaluate((workload) => window.__swbBenchmark.runCold(workload), fixture.workload));
  const warm = [];
  for (let iteration = 0; iteration < fixture.workload.warm_repetitions_per_session; iteration += 1) {
    warm.push(roundedMetrics(await page.evaluate((index) => window.__swbBenchmark.runWarm(index), iteration)));
  }
  await browser.close();
  rawSamples.push({
    session: session + 1,
    state: { cold: fixture.states.cold, warm: fixture.states.warm },
    started_at: sessionStartedAt,
    browser_launch_ms: launchMs,
    page_setup_ms: pageSetupMs,
    cold,
    warm,
  });
}

if (externalRequests.length > 0) throw new Error(`performance spike made external requests: ${externalRequests.join(", ")}`);
const installedChromeOutput = execFileSync("/usr/bin/google-chrome", ["--version"], { encoding: "utf8" }).trim();
const installedChromeVersion = installedChromeOutput.match(/^Google Chrome (\S+)$/)?.[1];
if (!installedChromeVersion || installedChromeVersion !== observedChromeVersion) {
  throw new Error(`Playwright did not launch the installed branded Chrome: installed=${installedChromeOutput}, observed=${observedChromeVersion}`);
}

const cpuList = cpus();
const report = {
  schema_version: "performance-spike-report.v1",
  fixture_id: fixture.fixture_id,
  fixture_sha256: fixtureDigest,
  capture_mode: existsSync(reportPath) ? "revalidation_without_overwrite" : "initial_capture",
  started_at: startedAt,
  finished_at: new Date().toISOString(),
  method: {
    workload: fixture.workload,
    browser: fixture.browser,
    states: fixture.states,
    metrics: fixture.metrics,
    network_policy: fixture.network_policy,
  },
  environment: {
    cpu: { model: cpuList[0]?.model ?? "unknown", logical_processors: cpuList.length },
    memory_bytes: { total: totalmem(), free_at_capture: freemem() },
    os: { type: osType(), platform: platform(), release: release(), architecture: arch() },
    chrome: {
      distribution: fixture.browser.distribution,
      channel: fixture.browser.channel,
      version: observedChromeVersion,
      headless: fixture.browser.headless,
      executable_path: "/usr/bin/google-chrome",
    },
    storage: storageEnvironment(),
    fixture_sha256: fixtureDigest,
    cold_warm_state: fixture.states,
    repeat_count: fixture.workload.repeat_count,
    tool: { name: fixture.browser.tool, version: fixture.browser.tool_version },
  },
  raw_samples: rawSamples,
  statistics: buildPerformanceStatistics(rawSamples),
  candidate_evaluation: {
    policy: "record_only_not_a_pass_gate",
    candidates: fixture.candidate_thresholds,
    verdict: "not_evaluated_as_gate",
  },
  network: { external_requests: externalRequests },
};

if (!existsSync(reportPath)) {
  validateDurableReport(report, fixture, fixtureDigest);
  mkdirSync(resolve(appRoot, "artifacts/spikes"), { recursive: true });
  writeFileSync(reportPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
  console.log(`spike:performance captured durable report: ${reportPath}`);
} else {
  const durableReport = JSON.parse(readFileSync(reportPath, "utf8"));
  validateDurableReport(durableReport, fixture, fixtureDigest);
  console.log(`spike:performance revalidated real Chrome without overwriting durable report: ${reportPath}`);
}
console.log(`Google Chrome ${observedChromeVersion}, headed=${fixture.browser.headless === false}, cold sessions=${rawSamples.length}`);
console.log(`warm repetitions=${rawSamples.reduce((sum, sample) => sum + sample.warm.length, 0)}, external requests=0`);
console.log("60s/3s/500ms/200ms remain UNVERIFIED candidates; no performance value was used as a pass/fail gate");
