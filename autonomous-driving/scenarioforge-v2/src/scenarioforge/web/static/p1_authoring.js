const intent = document.querySelector("#p1-intent");
const generate = document.querySelector("#p1-generate-draft");
const providerStatus = document.querySelector("#p1-provider-status");
const formTitle = document.querySelector("#p1-form-title");
const formSeed = document.querySelector("#p1-form-seed");
const formDuration = document.querySelector("#p1-form-duration");
const backend = document.querySelector("#p1-backend");
const applyForm = document.querySelector("#p1-apply-form");
const preflightButton = document.querySelector("#p1-preflight");
const confirmRun = document.querySelector("#p1-confirm-run");
const annotations = document.querySelector("#p1-source-annotations");
const editor = document.querySelector("#authoring-content");
const revisionLabel = document.querySelector("#active-revision-id");

let csrfToken = null;
let activePreflight = null;

async function responseJSON(url, options = {}) {
  const response = await fetch(url, {
    cache: "no-store",
    credentials: "same-origin",
    ...options,
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.detail ?? `Request failed (${response.status})`);
  }
  return payload;
}

async function token() {
  if (csrfToken === null) {
    const session = await responseJSON("/api/session");
    csrfToken = session.csrf_token;
  }
  return csrfToken;
}

async function controlledAction(url, payload) {
  return responseJSON(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": await token(),
    },
    body: JSON.stringify(payload),
  });
}

function editorValue() {
  const value = JSON.parse(editor.value);
  if (value === null || Array.isArray(value) || typeof value !== "object") {
    throw new Error("ScenarioSpec JSON must be one object");
  }
  return value;
}

function syncForm(value) {
  formTitle.value = typeof value?.title === "string" ? value.title : "";
  formSeed.value = Number.isInteger(value?.seed) ? String(value.seed) : "";
  const duration = value?.constraints?.duration_s;
  formDuration.value = typeof duration === "number" ? String(duration) : "";
}

function renderAnnotations(model) {
  annotations.replaceChildren();
  (model?.annotations ?? []).forEach((annotation) => {
    const item = document.createElement("li");
    item.dataset.status = annotation.source;
    item.textContent = `${annotation.path} · ${annotation.source}`;
    annotations.append(item);
  });
  if (annotations.childElementCount === 0) {
    const item = document.createElement("li");
    item.textContent = "Normalize or generate a draft to inspect value sources.";
    annotations.append(item);
  }
}

function appendPreflightDisclosures(report) {
  (report.disclosures ?? []).forEach((disclosure) => {
    const item = document.createElement("li");
    item.dataset.status = report.status;
    item.textContent = `${disclosure.path} · source: ${disclosure.source_semantics} · degraded: ${disclosure.degraded_semantics} · impact: ${disclosure.impact}`;
    annotations.append(item);
  });
  (report.diagnostics ?? []).forEach((diagnostic) => {
    if (report.disclosures?.some((item) => item.path === diagnostic.path)) {
      return;
    }
    const item = document.createElement("li");
    item.dataset.status = report.status;
    item.textContent = `${diagnostic.path ?? "$"} · ${diagnostic.reason ?? report.status}`;
    annotations.append(item);
  });
}

function showFailure(error) {
  providerStatus.textContent = error instanceof Error ? error.message : "P1 authoring action failed";
  providerStatus.dataset.state = "error";
  confirmRun.disabled = true;
}

generate.addEventListener("click", async () => {
  try {
    const draft = await controlledAction("/api/authoring/provider-drafts", {
      provider_id: "scenarioforge.offline-reference",
      prompt: intent.value,
    });
    editor.value = JSON.stringify(draft.normalized_spec.content, null, 2);
    syncForm(draft.normalized_spec.content);
    renderAnnotations(draft.normalized_spec);
    providerStatus.textContent = `${draft.intent_id} · ${draft.status} · correct missing fields before confirmation`;
    providerStatus.dataset.state = draft.status;
    activePreflight = null;
    confirmRun.disabled = true;
  } catch (error) {
    showFailure(error);
  }
});

applyForm.addEventListener("click", async () => {
  try {
    const value = editorValue();
    value.title = formTitle.value;
    value.seed = Number(formSeed.value);
    value.constraints ??= {};
    if (formDuration.value === "") {
      delete value.constraints.duration_s;
    } else {
      value.constraints.duration_s = Number(formDuration.value);
    }
    const normalized = await controlledAction("/api/authoring/normalize", {content: value});
    editor.value = JSON.stringify(normalized.content, null, 2);
    syncForm(normalized.content);
    renderAnnotations(normalized);
    providerStatus.textContent = normalized.missing_fields.length === 0
      ? "Form applied to the shared normalized ScenarioSpec. Save an immutable revision next."
      : `Still missing: ${normalized.missing_fields.join(", ")}`;
    activePreflight = null;
    confirmRun.disabled = true;
  } catch (error) {
    showFailure(error);
  }
});

editor.addEventListener("input", () => {
  try {
    syncForm(editorValue());
  } catch (_error) {
    // The JSON editor remains authoritative while the user is typing.
  }
  activePreflight = null;
  confirmRun.disabled = true;
});

preflightButton.addEventListener("click", async () => {
  try {
    const revisionId = revisionLabel.textContent.trim();
    if (!revisionId || revisionId === "—") {
      throw new Error("Save or select an immutable revision first");
    }
    activePreflight = await controlledAction(
      `/api/authoring/revisions/${encodeURIComponent(revisionId)}/p1-preflight`,
      {backend_id: backend.value},
    );
    renderAnnotations(activePreflight.normalized_spec);
    appendPreflightDisclosures(activePreflight);
    providerStatus.textContent = `P1 preflight ${activePreflight.status} · ${activePreflight.blocked ? "blocked" : "ready for user confirmation"}`;
    providerStatus.dataset.state = activePreflight.status;
    confirmRun.disabled = activePreflight.blocked;
  } catch (error) {
    showFailure(error);
  }
});

confirmRun.addEventListener("click", async () => {
  try {
    if (activePreflight === null) {
      throw new Error("Run P1 preflight before confirmation");
    }
    const root = `/api/authoring/p1-preflights/${encodeURIComponent(activePreflight.preflight_id)}`;
    const authorization = await controlledAction(`${root}/confirm`, {});
    const receipt = await controlledAction(`${root}/authorize-run`, {authorization});
    providerStatus.textContent = `${receipt.backend_id} run action authorized once · ${receipt.authorization_id}`;
    providerStatus.dataset.state = "authorized";
    activePreflight = null;
    confirmRun.disabled = true;
  } catch (error) {
    showFailure(error);
  }
});

renderAnnotations(null);
