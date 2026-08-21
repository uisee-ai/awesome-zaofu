const expectedMetricNames = ["dataset_open_ms", "first_render_ms", "frame_switch_ms", "interaction_ms"];
const expectedStatistics = ["minimum", "maximum", "mean", "median", "p95"];
const expectedEnvironmentFields = [
  "cpu",
  "memory_bytes",
  "os",
  "chrome",
  "storage",
  "fixture_sha256",
  "cold_warm_state",
  "repeat_count",
  "tool",
];

function invariant(condition, message) {
  if (!condition) throw new TypeError(message);
}

export function validatePerformanceFixture(fixture) {
  invariant(fixture?.schema_version === "performance-golden.v1", "unsupported performance fixture schema");
  invariant(Number.isInteger(fixture.workload?.point_count) && fixture.workload.point_count > 0, "point_count must be positive");
  invariant(Number.isInteger(fixture.workload?.repeat_count) && fixture.workload.repeat_count >= 3, "repeat_count must be >= 3");
  invariant(
    Number.isInteger(fixture.workload?.warm_repetitions_per_session) && fixture.workload.warm_repetitions_per_session >= 1,
    "warm_repetitions_per_session must be positive",
  );
  invariant(fixture.browser?.engine === "chromium", "browser engine must be chromium");
  invariant(fixture.browser?.channel === "chrome", "browser channel must be branded chrome");
  invariant(fixture.browser?.distribution === "Google Chrome", "browser distribution must be Google Chrome");
  invariant(fixture.browser?.headless === false, "headless must remain false for the desktop Chrome spike");
  invariant(fixture.browser?.tool === "@playwright/test", "tool must be @playwright/test");
  invariant(fixture.browser?.tool_version === "1.62.1", "tool version must match the frozen lockfile");
  invariant(
    JSON.stringify(fixture.metrics?.map((metric) => metric.name)) === JSON.stringify(expectedMetricNames),
    "performance metrics list drifted",
  );
  invariant(
    fixture.candidate_thresholds?.policy === "informational_only_unverified",
    "candidate thresholds must remain informational only",
  );
  invariant(Array.isArray(fixture.network_policy?.allowed_origins) && fixture.network_policy.allowed_origins.length === 0, "network must have no allowed origins");
  invariant(fixture.network_policy?.external_requests === "fail", "external requests must fail the spike");
  invariant(fixture.output?.raw_samples === true, "raw samples must be retained");
  invariant(JSON.stringify(fixture.output?.statistics) === JSON.stringify(expectedStatistics), "statistics list drifted");
  invariant(
    JSON.stringify(fixture.output?.environment_fields) === JSON.stringify(expectedEnvironmentFields),
    "environment fields list drifted",
  );
  return true;
}

export function summarizeSamples(samples) {
  invariant(Array.isArray(samples) && samples.length > 0, "samples must be a non-empty array");
  invariant(samples.every((sample) => Number.isFinite(sample) && sample >= 0), "samples must be finite non-negative numbers");
  const sorted = [...samples].sort((left, right) => left - right);
  const middle = Math.floor(sorted.length / 2);
  const median =
    sorted.length % 2 === 0 ? (sorted[middle - 1] + sorted[middle]) / 2 : sorted[middle];
  return {
    minimum: sorted[0],
    maximum: sorted.at(-1),
    mean: sorted.reduce((sum, sample) => sum + sample, 0) / sorted.length,
    median,
    p95: sorted[Math.ceil(sorted.length * 0.95) - 1],
  };
}

export function roundMilliseconds(value) {
  invariant(Number.isFinite(value) && value >= 0, "millisecond value must be finite and non-negative");
  return Math.round(value * 1000) / 1000;
}

export function buildPerformanceStatistics(rawSamples) {
  const coldMetrics = Object.fromEntries(
    expectedMetricNames.map((name) => [name, rawSamples.map((sample) => sample.cold[name])]),
  );
  const warmMetrics = Object.fromEntries(
    ["frame_switch_ms", "interaction_ms"].map((name) => [
      name,
      rawSamples.flatMap((sample) => sample.warm.map((warm) => warm[name])),
    ]),
  );
  return {
    cold: Object.fromEntries(Object.entries(coldMetrics).map(([name, samples]) => [name, summarizeSamples(samples)])),
    warm: Object.fromEntries(Object.entries(warmMetrics).map(([name, samples]) => [name, summarizeSamples(samples)])),
  };
}
