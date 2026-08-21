const API = Object.freeze({
  experiments: "/api/experiments",
  session: "/api/session",
});

const LABELS = Object.freeze({
  queued: "Queued",
  running: "Running",
  paused: "Paused",
  completed: "Completed",
  failed: "Failed",
  timeout: "Timed out",
  cancelled: "Cancelled",
});

export function experimentStateLabel(state) {
  return LABELS[state] || "Unknown";
}

function commandId(operation) {
  const random = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
  return `command-${operation}-${random}`;
}

async function responseJson(response) {
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.detail || `Experiment request failed (${response.status})`);
  }
  return payload;
}

function releaseLimits() {
  return {
    active_experiments: 1,
    artifact_bytes: 10_485_760,
    concurrency: 2,
    cpu_max_period: 100_000,
    cpu_max_quota: 100_000,
    log_bytes: 1_048_576,
    max_jobs: 64,
    memory_mib: 4_096,
    pids: 32,
    timeout_seconds: 120,
  };
}

function template() {
  const section = document.createElement("section");
  section.id = "experiment-controls";
  section.setAttribute("aria-labelledby", "experiment-heading");
  section.innerHTML = `
    <h2 id="experiment-heading">Persistent experiment</h2>
    <p id="experiment-error" role="alert" hidden></p>
    <dl>
      <dt>Experiment</dt><dd id="experiment-id">Not created</dd>
      <dt>State</dt><dd id="experiment-state" data-state="none">Not created</dd>
    </dl>
    <div aria-label="Experiment controls">
      <button type="button" data-experiment-operation="create">Create experiment</button>
      <button type="button" data-experiment-operation="start">Start experiment</button>
      <button type="button" data-experiment-operation="pause">Pause experiment</button>
      <button type="button" data-experiment-operation="step">Step experiment</button>
      <button type="button" data-experiment-operation="resume">Resume experiment</button>
      <button type="button" data-experiment-operation="stop">Stop experiment</button>
      <button type="button" data-experiment-operation="reset">Reset experiment</button>
    </div>
    <ol id="experiment-jobs" aria-label="Experiment jobs"></ol>
  `;
  return section;
}

function render(section, experiment) {
  section.querySelector("#experiment-id").textContent = experiment?.experiment_id || "Not created";
  const state = experiment?.state || "none";
  const stateNode = section.querySelector("#experiment-state");
  stateNode.textContent = state === "none" ? "Not created" : experimentStateLabel(state);
  stateNode.dataset.state = state;
  const jobs = section.querySelector("#experiment-jobs");
  jobs.replaceChildren();
  for (const job of experiment?.jobs || []) {
    const item = document.createElement("li");
    item.dataset.jobId = job.job_id;
    item.dataset.state = job.state;
    item.textContent = `${job.job_id}: ${experimentStateLabel(job.state)}`;
    jobs.append(item);
  }
  const valid = {
    create: !experiment,
    start: state === "queued",
    pause: state === "running",
    step: state === "paused" && experiment?.cardinality === 1,
    resume: state === "paused",
    stop: ["queued", "running", "paused"].includes(state),
    reset: Boolean(experiment),
  };
  for (const button of section.querySelectorAll("[data-experiment-operation]")) {
    button.disabled = !valid[button.dataset.experimentOperation];
  }
}

export async function mountExperimentControls({pollIntervalMs = 250} = {}) {
  let section = document.querySelector("#experiment-controls");
  if (!section) {
    section = template();
    (document.querySelector("main") || document.body).append(section);
  }
  const session = await responseJson(await fetch(API.session, {credentials: "same-origin"}));
  let experiment = null;
  let polling = null;
  const errorNode = section.querySelector("#experiment-error");

  async function refresh() {
    const listing = await responseJson(await fetch(API.experiments, {credentials: "same-origin"}));
    experiment = listing.experiments.at(-1) || null;
    render(section, experiment);
    return experiment;
  }

  async function mutate(path, payload, idempotencyKey = null) {
    const headers = {
      "content-type": "application/json",
      "x-csrf-token": session.csrf_token,
    };
    if (idempotencyKey) headers["idempotency-key"] = idempotencyKey;
    experiment = await responseJson(await fetch(path, {
      method: "POST",
      credentials: "same-origin",
      headers,
      body: JSON.stringify(payload),
    }));
    render(section, experiment);
  }

  section.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-experiment-operation]");
    if (!button || button.disabled) return;
    const operation = button.dataset.experimentOperation;
    errorNode.hidden = true;
    try {
      if (operation === "create") {
        const key = commandId("submit");
        await mutate(API.experiments, {
          schema_version: "scenarioforge.experiment-definition/v1",
          matrix: {scenario_id: ["brake_lead"], seed: [7]},
          inputs: {formal_release: false},
          limits: releaseLimits(),
        }, key);
      } else {
        await mutate(
          `${API.experiments}/${encodeURIComponent(experiment.experiment_id)}/commands`,
          {operation, command_id: commandId(operation)},
        );
      }
    } catch (error) {
      errorNode.textContent = String(error.message || error);
      errorNode.hidden = false;
    }
  });

  await refresh();
  clearInterval(globalThis.__scenarioforgeExperimentPoll);
  polling = globalThis.setInterval(() => refresh().catch((error) => {
    errorNode.textContent = String(error.message || error);
    errorNode.hidden = false;
  }), pollIntervalMs);
  globalThis.__scenarioforgeExperimentPoll = polling;
  return {section, refresh, stop: () => clearInterval(polling)};
}
