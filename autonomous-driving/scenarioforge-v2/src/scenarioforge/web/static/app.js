import * as THREE from "./vendor/three.module.min.js";
import {
  applyReplayDataset,
  createFollowCameraState,
  interpolatePose,
  projectReplayScene,
  resolveTimelineInput,
  renderReplayFailure,
  timelineTickForTime,
} from "./replay_scene.js";
import {
  applyCameraInput as applyP1CameraInput,
  bindReplayCameraInputs,
  createCameraState as createP1CameraState,
  followCameraQuality,
} from "./p1_replay.js";

// ScenarioForge Sedan v1 is an original project asset, released under CC0-1.0.
// Its controlled source/digest/dimensions are pinned by assets/p1/replay/vehicle-model-manifest.json.
const finitePositive = (value) => (
  typeof value === "number" && Number.isFinite(value) && value > 0
);
const freezeDimensions = (length, width, height) => Object.freeze({length, width, height});
const CANONICAL_VEHICLE_DIMENSIONS = Object.freeze({
  "competitive_lane_change:challenger": freezeDimensions(4.7, 1.9, 1.6),
  "competitive_lane_change:ego": freezeDimensions(4.8, 1.9, 1.6),
  "competitive_lane_change:traffic": freezeDimensions(4.5, 1.8, 1.5),
  "cross_traffic_red_light_violation:ego": freezeDimensions(4.8, 1.9, 1.6),
  "cross_traffic_red_light_violation:traffic": freezeDimensions(4.5, 1.8, 1.5),
  "cross_traffic_red_light_violation:violator": freezeDimensions(4.7, 1.9, 1.6),
  "highway_merge:ego": freezeDimensions(4.8, 1.9, 1.6),
  "highway_merge:front": freezeDimensions(4.6, 1.8, 1.5),
  "highway_merge:rear": freezeDimensions(4.6, 1.8, 1.5),
  "highway_merge:traffic": freezeDimensions(4.5, 1.8, 1.5),
  "pedestrian_red_light_crossing:ego": freezeDimensions(4.8, 1.9, 1.6),
  "pedestrian_red_light_crossing:traffic": freezeDimensions(4.5, 1.8, 1.5),
  "unprotected_left_turn:ego": freezeDimensions(4.8, 1.9, 1.6),
  "unprotected_left_turn:oncoming": freezeDimensions(4.7, 1.9, 1.6),
  "unprotected_left_turn:traffic": freezeDimensions(4.5, 1.8, 1.5),
});
const ROLE_VEHICLE_DIMENSIONS = Object.freeze({
  ego: freezeDimensions(4.8, 1.9, 1.6),
  controlled: freezeDimensions(4.7, 1.9, 1.6),
  controlled_agent: freezeDimensions(4.7, 1.9, 1.6),
  social: freezeDimensions(4.6, 1.8, 1.5),
  social_vehicle: freezeDimensions(4.6, 1.8, 1.5),
});
const VEHICLE_MODEL_CONTRACT = Object.freeze({
  schemaVersion: "scenarioforge.vehicle-model/v1",
  assetId: "scenarioforge.original-sedan",
  version: "1.0.0",
  coordinateSystem: "right-handed-x-forward-y-up",
  localForwardAxis: "+x",
  boundingBoxM: freezeDimensions(4.8, 1.9, 1.6),
  features: Object.freeze([
    "front", "rear", "body", "windows", "wheels", "headlights", "brake_lights",
  ]),
});

function vehicleDimensionsFor(scenarioId, participantId, role) {
  const dimensions = CANONICAL_VEHICLE_DIMENSIONS[`${scenarioId}:${participantId}`]
    ?? ROLE_VEHICLE_DIMENSIONS[role];
  if (dimensions === undefined) {
    throw new TypeError("vehicle dimensions are unavailable");
  }
  return {...dimensions};
}

function vehicleHullGeometry() {
  const sections = [
    [-2.40, 0.28, 0.50, 0.76], [-2.16, 0.24, 0.82, 0.88],
    [-1.26, 0.24, 0.94, 0.92], [-0.72, 0.24, 1.42, 0.72],
    [0.72, 0.24, 1.46, 0.72], [1.34, 0.24, 0.90, 0.90],
    [2.16, 0.26, 0.74, 0.84], [2.40, 0.30, 0.48, 0.74],
  ];
  const positions = [];
  sections.forEach(([x, bottom, top, halfWidth]) => positions.push(
    x, bottom, halfWidth, x, bottom, -halfWidth,
    x, top, halfWidth, x, top, -halfWidth,
  ));
  const indices = [];
  for (let index = 0; index < sections.length - 1; index += 1) {
    const left = index * 4;
    const right = left + 4;
    indices.push(
      left, right, left + 2, left + 2, right, right + 2,
      left + 1, left + 3, right + 1, left + 3, right + 3, right + 1,
      left + 2, right + 2, left + 3, left + 3, right + 2, right + 3,
      left, left + 1, right, left + 1, right + 1, right,
    );
  }
  const last = (sections.length - 1) * 4;
  indices.push(0, 2, 1, 1, 2, 3, last, last + 1, last + 2, last + 1, last + 3, last + 2);
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  geometry.setIndex(indices);
  geometry.computeVertexNormals();
  return geometry;
}

function featureGroup(feature) {
  const group = new THREE.Group();
  group.userData.feature = feature;
  return group;
}

function createVehicleModel(_three, {color, dimensions}) {
  if (
    _three?.Group === undefined
    || typeof color !== "number"
    || dimensions === null
    || ![dimensions.length, dimensions.width, dimensions.height].every(finitePositive)
  ) {
    throw new TypeError("vehicle model input is invalid");
  }
  const vehicle = new THREE.Group();
  const body = new THREE.Mesh(
    vehicleHullGeometry(),
    new THREE.MeshPhysicalMaterial({
      color, metalness: 0.34, roughness: 0.34, clearcoat: 0.7, clearcoatRoughness: 0.25,
    }),
  );
  body.castShadow = true;
  body.receiveShadow = true;
  body.userData.feature = "vehicle-body";
  vehicle.add(body);

  const windows = featureGroup("vehicle-window");
  const windowMaterial = new THREE.MeshPhysicalMaterial({
    color: 0x102b38, metalness: 0.05, roughness: 0.18, transparent: true, opacity: 0.84,
  });
  for (const side of [-1, 1]) {
    for (const [x, width] of [[-0.28, 0.82], [0.58, 0.72]]) {
      const window = new THREE.Mesh(new THREE.PlaneGeometry(width, 0.48), windowMaterial);
      window.position.set(x, 1.14, side * 0.735);
      window.rotation.y = side > 0 ? 0 : Math.PI;
      windows.add(window);
    }
  }
  for (const [x, rotation, width] of [[1.04, Math.PI / 2, 1.22], [-0.98, -Math.PI / 2, 1.18]]) {
    const window = new THREE.Mesh(new THREE.PlaneGeometry(width, 0.52), windowMaterial);
    window.position.set(x, 1.16, 0);
    window.rotation.y = rotation;
    windows.add(window);
  }
  vehicle.add(windows);

  const wheels = featureGroup("vehicle-wheel");
  const tireMaterial = new THREE.MeshStandardMaterial({color: 0x111416, roughness: 0.88});
  const hubMaterial = new THREE.MeshStandardMaterial({color: 0x9ba5a8, metalness: 0.72, roughness: 0.26});
  for (const x of [-1.48, 1.48]) {
    for (const z of [-0.88, 0.88]) {
      const wheel = new THREE.Mesh(new THREE.CylinderGeometry(0.34, 0.34, 0.20, 24), tireMaterial);
      wheel.rotation.x = Math.PI / 2;
      wheel.position.set(x, 0.36, z);
      wheel.userData.feature = "vehicle-wheel";
      const hub = new THREE.Mesh(new THREE.CylinderGeometry(0.18, 0.18, 0.205, 18), hubMaterial);
      hub.rotation.x = Math.PI / 2;
      wheel.add(hub);
      wheels.add(wheel);
    }
  }
  vehicle.add(wheels);

  const front = featureGroup("vehicle-front");
  const rear = featureGroup("vehicle-rear");
  const brakeLights = featureGroup("vehicle-brake-lights");
  const headlightMaterial = new THREE.MeshStandardMaterial({
    color: 0xfff1bd, emissive: 0xffd77a, emissiveIntensity: 1.7,
  });
  const rearMaterial = new THREE.MeshStandardMaterial({color: 0x541719, roughness: 0.42});
  const brakeMaterial = new THREE.MeshStandardMaterial({
    color: 0xff2828, emissive: 0xff0000, emissiveIntensity: 2.4,
  });
  for (const z of [-0.55, 0.55]) {
    const headlight = new THREE.Mesh(new THREE.SphereGeometry(0.13, 12, 8), headlightMaterial);
    headlight.scale.set(0.48, 0.72, 1);
    headlight.position.set(2.34, 0.58, z);
    front.add(headlight);
    const rearLight = new THREE.Mesh(new THREE.SphereGeometry(0.14, 12, 8), rearMaterial);
    rearLight.scale.set(0.42, 0.78, 1);
    rearLight.position.set(-2.34, 0.58, z);
    rear.add(rearLight);
    const brakeLight = new THREE.Mesh(new THREE.SphereGeometry(0.105, 12, 8), brakeMaterial);
    brakeLight.scale.set(0.44, 0.72, 1);
    brakeLight.position.set(-2.365, 0.58, z);
    brakeLights.add(brakeLight);
  }
  brakeLights.visible = false;
  rear.add(brakeLights);
  vehicle.add(front, rear);
  vehicle.userData.brakeLights = brakeLights;
  vehicle.scale.set(
    dimensions.length / VEHICLE_MODEL_CONTRACT.boundingBoxM.length,
    dimensions.height / VEHICLE_MODEL_CONTRACT.boundingBoxM.height,
    dimensions.width / VEHICLE_MODEL_CONTRACT.boundingBoxM.width,
  );
  vehicle.userData.assetId = VEHICLE_MODEL_CONTRACT.assetId;
  vehicle.userData.assetVersion = VEHICLE_MODEL_CONTRACT.version;
  vehicle.userData.features = [...VEHICLE_MODEL_CONTRACT.features];
  vehicle.userData.declaredDimensionsM = {...dimensions};
  vehicle.userData.renderDimensionsM = {...dimensions};
  vehicle.userData.modelScaleRelativeError = 0;
  vehicle.userData.groundOffsetM = 0;
  return vehicle;
}

document.querySelectorAll("[data-authoring-button]").forEach((placeholder) => {
  const button = document.createElement("button");
  button.type = "button";
  button.disabled = true;
  button.textContent = placeholder.textContent;
  button.setAttribute("data-authoring-id", placeholder.getAttribute("data-authoring-id"));
  placeholder.replaceWith(button);
});
document.querySelectorAll("[data-authoring-id]").forEach((element) => {
  element.id = element.getAttribute("data-authoring-id");
  element.removeAttribute("data-authoring-id");
});

const ENDPOINTS = Object.freeze({
  authoringDrafts: "/api/authoring/drafts",
  authoringImport: "/api/authoring/import",
  authoringPresets: "/api/authoring/presets",
  authoringScenarios: "/api/authoring/scenarios",
  catalog: "/api/scenarios",
  p1Catalog: "/api/p1/scenarios",
  p1Runs: "/api/p1/runs",
  session: "/api/session",
  runs: "/api/runs",
});
const ACTIVE_RUN_KEY = "scenarioforge.active-run.v1";
const POLL_INTERVAL_MS = 350;
const EVENT_PREROLL_TICKS = 10;
const MAX_REPLAY_FRAME_DELTA_MS = 100;

const appStatus = document.querySelector("#app-status");
const runScenario = document.querySelector("#run-scenario");
const runP1Scenario = document.querySelector("#run-p1-scenario");
const p1ScenarioSelect = document.querySelector("#p1-scenario-select");
const p1ScenarioName = document.querySelector("#p1-scenario-name");
const p1ScenarioDescription = document.querySelector("#p1-scenario-description");
const studioSourceButtons = [...document.querySelectorAll("[data-studio-source]")];
const studioSourcePanels = [...document.querySelectorAll("[data-studio-panel]")];
const studioDocumentPanel = document.querySelector("#studio-document-panel");
const studioTemplateSelect = document.querySelector("#studio-template-select");
const studioTemplateName = document.querySelector("#studio-template-name");
const studioTemplateDescription = document.querySelector("#studio-template-description");
const studioTemplateBackend = document.querySelector("#studio-template-backend");
const studioTemplateParticipants = document.querySelector("#studio-template-participants");
const studioRun = document.querySelector("#studio-run");
const studioRunTitle = document.querySelector("#studio-run-title");
const studioRunSummary = document.querySelector("#studio-run-summary");
const catalogPanel = document.querySelector("#catalog-panel");
const scenarioName = document.querySelector("#scenario-name");
const scenarioDescription = document.querySelector("#scenario-description");
const livePanel = document.querySelector("#live-panel");
const liveState = document.querySelector("#live-state");
const liveRunId = document.querySelector("#live-run-id");
const terminalPanel = document.querySelector("#terminal-panel");
const playbackPanel = document.querySelector("#playback-panel");
const nonPlayable = document.querySelector("#non-playable");
const evidenceList = document.querySelector("#evidence-list");
const terminalEvents = document.querySelector("#terminal-events");
const replayCanvas = document.querySelector("#replay-canvas");
const participantLegend = document.querySelector("#participant-legend");
const roadLegend = document.querySelector("#road-legend");
const replayToggle = document.querySelector("#replay-toggle");
const replayTimeline = document.querySelector("#replay-timeline");
const replaySpeed = document.querySelector("#replay-speed");
const currentTick = document.querySelector("#current-tick");
const eventPositions = document.querySelector("#event-positions");
const replayOutcome = document.querySelector("#replay-outcome");
const activeEvents = document.querySelector("#active-events");
const authoringContent = document.querySelector("#authoring-content");
const authoringDraftSelect = document.querySelector("#authoring-draft");
const authoringPreset = document.querySelector("#authoring-preset");
const authoringDiagnostics = document.querySelector("#authoring-diagnostics");
const revisionHistory = document.querySelector("#revision-history");
const createDraftButton = document.querySelector("#create-draft");
const updateDraftButton = document.querySelector("#update-draft");
const validateDraftButton = document.querySelector("#validate-draft");
const saveRevisionButton = document.querySelector("#save-revision");
const cloneDraftButton = document.querySelector("#clone-draft");
const archiveDraftButton = document.querySelector("#archive-draft");
const forkPresetButton = document.querySelector("#fork-preset");
const importDraftButton = document.querySelector("#import-draft");
const exportDraftButton = document.querySelector("#export-draft");
const preflightRevisionButton = document.querySelector("#preflight-revision");
const saveAndRunRevisionButton = document.querySelector("#save-and-run-revision");
const importFormat = document.querySelector("#import-format");
const exportFormat = document.querySelector("#export-format");

const TERMINAL_FIELDS = Object.freeze([
  ["scenario-id", (terminal) => terminal.scenario_id],
  ["run-id", (terminal) => terminal.run_id],
  ["terminal-status", (terminal) => terminal.execution_status ?? terminal.status],
  ["terminal-reason", (terminal) => terminal.termination_reason ?? terminal.reason],
  ["failure-stage", (terminal) => terminal.failure_stage ?? "—"],
  ["seed", (terminal) => terminal.seed],
  ["policy-id", (terminal) => `${terminal.policy.id}@${terminal.policy.version}`],
  ["manifest-digest", (terminal) => terminal.digests.run_manifest],
  ["artifact-index-digest", (terminal) => terminal.digests.artifact_index],
  ["evidence-ref", (terminal) => terminal.logical_ref],
  ["collision", (terminal) => formatBoolean(terminal.metrics.collision)],
  ["collision-participants", (terminal) => terminal.metrics.collision_participants.join(", ") || "None"],
  ["min-ttc", (terminal) => formatMetric(terminal.metrics.min_ttc_s, "s")],
  ["completion-time", (terminal) => formatMetric(terminal.metrics.completion_time_s, "s")],
  ["terminal-tick", (terminal) => terminal.metrics.terminal_tick ?? "—"],
]);

let selectedScenario = null;
let scenarioCatalog = [];
let selectedP1Scenario = null;
let p1ScenarioCatalog = [];
let session = null;
let pollingRunId = null;
let activeDraft = null;
let activeRevision = null;
let authoringPresets = [];
let studioSourceMode = "template";
let selectedStudioTemplate = null;

const ui = {
  scenarioSelect: null,
  scenarioTargetOutcome: null,
  scenarioParticipants: null,
  scenarioRoutes: null,
  scenarioDanger: null,
  scenarioReaction: null,
  scenarioSuccess: null,
  scenarioFailure: null,
  scenarioOutcome: null,
  metricProjections: null,
  recordedEvidenceBadge: null,
  previousEvent: null,
  nextEvent: null,
  replayRestart: null,
  simulationTime: null,
  cameraMode: null,
};

const state = {
  scene: null,
  camera: null,
  cameraFrame: null,
  renderer: null,
  meshes: new Map(),
  frames: new Map(),
  terminalTick: 0,
  sampleIntervalMs: 100,
  currentTick: 0,
  speed: 1,
  playing: false,
  lastFrameAt: 0,
  tickRemainder: 0,
  eventSeekTicks: [],
  cameraMode: "ego-follow",
  conflictFrame: null,
  playbackEvents: [],
  participantReadouts: new Map(),
  scenarioOutcome: null,
  replayScene: null,
  tracks: new Map(),
  currentTimeS: 0,
  terminalTimeS: 0,
  followCameraState: null,
  lastCameraUpdateAt: 0,
  currentEgoPose: null,
  freeCameraState: null,
  signalHeads: new Map(),
};

function runStatus(runId) {
  return `/api/runs/${encodeURIComponent(runId)}`;
}

function scopedRunStatus(runId, runsEndpoint = ENDPOINTS.runs) {
  return runsEndpoint === ENDPOINTS.runs
    ? runStatus(runId)
    : `${runsEndpoint}/${encodeURIComponent(runId)}`;
}

function runTrajectory(runId) {
  return `${runStatus(runId)}/artifacts/trajectory`;
}

function scopedRunTrajectory(runId, runsEndpoint = ENDPOINTS.runs) {
  return runsEndpoint === ENDPOINTS.runs
    ? runTrajectory(runId)
    : `${scopedRunStatus(runId, runsEndpoint)}/artifacts/trajectory`;
}

function setApplicationStatus(message, tone = "ready") {
  appStatus.textContent = message;
  appStatus.dataset.tone = tone;
}

function formatBoolean(value) {
  if (value === null || value === undefined) {
    return "Unknown";
  }
  return value ? "Yes" : "No";
}

function formatMetric(value, unit) {
  if (value === null || value === undefined) {
    return "—";
  }
  return `${Number(value).toFixed(3)} ${unit}`;
}

function formatToken(value) {
  return String(value ?? "—").replaceAll(/[_-]/g, " ");
}

function formatThreshold(threshold, unit) {
  if (threshold === null) {
    return "Threshold: not configured";
  }
  const operators = {lt: "<", lte: "≤", gt: ">", gte: "≥", eq: "="};
  return `Threshold: ${operators[threshold.operator] ?? threshold.operator} ${threshold.value} ${unit}`;
}

function setText(id, value) {
  const target = document.getElementById(id);
  target.textContent = String(value ?? "—");
}

function createElement(tagName, id, className = "") {
  const element = document.createElement(tagName);
  element.id = id;
  element.className = className;
  return element;
}

function appendLabeledText(parent, label, id) {
  const wrapper = document.createElement("div");
  const heading = document.createElement("h3");
  heading.textContent = label;
  const content = document.createElement("p");
  content.id = id;
  wrapper.append(heading, content);
  parent.append(wrapper);
  return content;
}

function buildProductExtensions() {
  const selectorLabel = document.createElement("label");
  selectorLabel.className = "scenario-selector";
  const selectorCaption = document.createElement("span");
  selectorCaption.textContent = "Registered preset";
  ui.scenarioSelect = createElement("select", "scenario-select");
  ui.scenarioSelect.setAttribute("aria-label", "Registered scenario preset");
  selectorLabel.append(selectorCaption, ui.scenarioSelect);

  const comprehension = createElement("div", "scenario-comprehension", "scenario-comprehension");
  const outcomeBlock = document.createElement("div");
  const outcomeHeading = document.createElement("h3");
  outcomeHeading.textContent = "Target outcome";
  ui.scenarioTargetOutcome = createElement("p", "scenario-target-outcome", "outcome-token");
  outcomeBlock.append(outcomeHeading, ui.scenarioTargetOutcome);

  const participantBlock = document.createElement("div");
  const participantHeading = document.createElement("h3");
  participantHeading.textContent = "Participants";
  ui.scenarioParticipants = createElement("ul", "scenario-participants", "comprehension-list");
  participantBlock.append(participantHeading, ui.scenarioParticipants);

  const routeBlock = document.createElement("div");
  const routeHeading = document.createElement("h3");
  routeHeading.textContent = "Routes";
  ui.scenarioRoutes = createElement("ul", "scenario-routes", "comprehension-list");
  routeBlock.append(routeHeading, ui.scenarioRoutes);

  comprehension.append(outcomeBlock, participantBlock, routeBlock);
  ui.scenarioDanger = appendLabeledText(comprehension, "Danger location and time", "scenario-danger");
  ui.scenarioReaction = appendLabeledText(comprehension, "Expected reaction", "scenario-reaction");
  ui.scenarioSuccess = appendLabeledText(comprehension, "What success means", "scenario-success");
  ui.scenarioFailure = appendLabeledText(comprehension, "What failure means", "scenario-failure");

  const catalogFooter = catalogPanel.querySelector(".catalog-footer");
  catalogPanel.insertBefore(selectorLabel, catalogFooter);
  catalogPanel.insertBefore(comprehension, catalogFooter);

  const terminalColumns = terminalPanel.querySelector(".terminal-columns");
  const outcomePanel = createElement("div", "terminal-outcome", "terminal-outcome");
  const outcomeLabel = document.createElement("h3");
  outcomeLabel.textContent = "Scenario outcome";
  ui.scenarioOutcome = createElement("p", "scenario-outcome", "outcome-token");
  outcomePanel.append(outcomeLabel, ui.scenarioOutcome);
  ui.metricProjections = createElement("div", "metric-projections", "metric-projections");
  terminalPanel.insertBefore(outcomePanel, terminalColumns);
  terminalPanel.insertBefore(ui.metricProjections, terminalColumns);

  const playbackHeading = playbackPanel.querySelector(".panel-heading");
  ui.recordedEvidenceBadge = createElement("p", "recorded-evidence-badge", "metadata-chip recorded-badge");
  ui.recordedEvidenceBadge.textContent = "Recorded immutable evidence";
  playbackHeading.append(ui.recordedEvidenceBadge);

  const localControls = createElement("div", "local-replay-controls", "local-replay-controls");
  ui.replayRestart = createElement("button", "replay-restart", "secondary-action");
  ui.replayRestart.type = "button";
  ui.replayRestart.textContent = "Replay from start";
  ui.previousEvent = createElement("button", "previous-event", "secondary-action");
  ui.previousEvent.type = "button";
  ui.previousEvent.textContent = "Previous event";
  ui.nextEvent = createElement("button", "next-event", "secondary-action");
  ui.nextEvent.type = "button";
  ui.nextEvent.textContent = "Next event";
  const cameraLabel = document.createElement("label");
  const cameraCaption = document.createElement("span");
  cameraCaption.textContent = "Camera";
  ui.cameraMode = createElement("select", "camera-mode");
  for (const [value, label] of [["ego-follow", "Ego follow"], ["overview", "Overview"]]) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    ui.cameraMode.append(option);
  }
  cameraLabel.append(cameraCaption, ui.cameraMode);
  ui.simulationTime = createElement("output", "simulation-time", "simulation-time");
  ui.simulationTime.textContent = "0.00 s";
  localControls.append(ui.replayRestart, ui.previousEvent, ui.nextEvent, cameraLabel, ui.simulationTime);
  playbackPanel.insertBefore(localControls, playbackPanel.querySelector(".event-track"));

  replaySpeed.replaceChildren();
  let option = document.createElement("option");
  option.value = "0.25";
  option.textContent = "0.25×";
  replaySpeed.append(option);
  option = document.createElement("option");
  option.value = "0.5";
  option.textContent = "0.5×";
  replaySpeed.append(option);
  option = document.createElement("option");
  option.value = "1";
  option.textContent = "1×";
  option.selected = true;
  replaySpeed.append(option);
  option = document.createElement("option");
  option.value = "2";
  option.textContent = "2×";
  replaySpeed.append(option);
  option = document.createElement("option");
  option.value = "4";
  option.textContent = "4×";
  replaySpeed.append(option);

  ui.scenarioSelect.addEventListener("change", () => selectScenario(ui.scenarioSelect.value));
  ui.replayRestart.addEventListener("click", restartReplay);
  ui.previousEvent.addEventListener("click", () => seekRelativeEvent(-1));
  ui.nextEvent.addEventListener("click", () => seekRelativeEvent(1));
  ui.cameraMode.addEventListener("change", () => applyCameraMode(ui.cameraMode.value));
}

async function requestJSON(url, options = {}) {
  const response = await fetch(url, {
    credentials: "same-origin",
    ...options,
  });
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.startsWith("application/json")) {
    throw new Error("Server returned an unexpected content type");
  }
  const payload = await response.json();
  if (!response.ok) {
    const message = typeof payload.detail === "string" ? payload.detail : `Request failed (${response.status})`;
    throw new Error(message);
  }
  return payload;
}

function authoringScenarioPath(scenarioId, suffix = "") {
  return `/api/authoring/scenarios/${encodeURIComponent(scenarioId)}${suffix}`;
}

function authoringDraftPath(scenarioId, suffix = "") {
  return `${ENDPOINTS.authoringDrafts}/${encodeURIComponent(scenarioId)}${suffix}`;
}

function authoringRevisionPath(revisionId, suffix = "") {
  return `/api/authoring/revisions/${encodeURIComponent(revisionId)}${suffix}`;
}

async function authoringWrite(url, payload, {idempotencyKey = null} = {}) {
  if (session === null) {
    throw new Error("Authoring session is unavailable");
  }
  const headers = {
    "Content-Type": "application/json",
    "X-CSRF-Token": session.csrfToken,
  };
  if (idempotencyKey !== null) {
    headers["Idempotency-Key"] = idempotencyKey;
  }
  return requestJSON(url, {
    method: "POST",
    headers,
    body: JSON.stringify(payload),
  });
}

function editorDocument() {
  let value;
  try {
    value = JSON.parse(authoringContent.value);
  } catch (_error) {
    throw new Error("The editor does not contain valid strict JSON");
  }
  if (value === null || Array.isArray(value) || typeof value !== "object") {
    throw new Error("The editor must contain one JSON object");
  }
  return value;
}

function setAuthoringControls() {
  const ready = session !== null;
  const hasDraft = activeDraft !== null;
  const hasRevision = activeRevision !== null;
  createDraftButton.disabled = !ready;
  importDraftButton.disabled = !ready;
  forkPresetButton.disabled = !ready || authoringPresets.length === 0;
  updateDraftButton.disabled = !ready || !hasDraft;
  validateDraftButton.disabled = !ready || !hasDraft;
  saveRevisionButton.disabled = !ready || !hasDraft;
  cloneDraftButton.disabled = !ready || !hasDraft;
  archiveDraftButton.disabled = !ready || !hasDraft;
  exportDraftButton.disabled = !hasDraft;
  preflightRevisionButton.disabled = !ready || !hasRevision;
  saveAndRunRevisionButton.disabled = !ready || !hasDraft;
}

function renderAuthoringDiagnostics(report) {
  authoringDiagnostics.replaceChildren();
  const diagnostics = report?.diagnostics ?? [];
  if (diagnostics.length === 0) {
    const item = document.createElement("li");
    item.textContent = report?.valid === true
      ? "Exact authoring validation passed."
      : "No field diagnostics yet.";
    authoringDiagnostics.append(item);
    return;
  }
  diagnostics.forEach((diagnostic) => {
    const item = document.createElement("li");
    item.dataset.status = diagnostic.status;
    item.textContent = `${diagnostic.path} · ${diagnostic.code} · ${diagnostic.reason} Fix: ${diagnostic.suggestion}`;
    authoringDiagnostics.append(item);
  });
}

function selectAuthoringRevision(revision) {
  activeRevision = revision;
  setText("active-revision-id", revision?.revision_id ?? "—");
  setText("preflight-status", "Not run");
  setAuthoringControls();
}

async function renderRevisionHistory(scenarioId) {
  const history = await requestJSON(authoringScenarioPath(scenarioId, "/history"));
  revisionHistory.replaceChildren();
  history.revisions.forEach((revision) => {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = `r${revision.revision_number} · ${revision.revision_id} · sha256:${revision.canonical_digest}`;
    button.addEventListener("click", () => selectAuthoringRevision(revision));
    item.append(button);
    revisionHistory.append(item);
  });
  if (history.revisions.length === 0) {
    const item = document.createElement("li");
    item.textContent = "No immutable revisions saved.";
    revisionHistory.append(item);
  }
}

async function setActiveDraft(draft, {replaceEditor = true} = {}) {
  activeDraft = draft;
  if (replaceEditor) {
    authoringContent.value = JSON.stringify(draft.content, null, 2);
  }
  authoringDraftSelect.value = draft.scenario_id;
  setText("authoring-draft-id", draft.scenario_id);
  setText("draft-generation", draft.generation);
  selectAuthoringRevision(
    draft.latest_revision_id === null
      ? null
      : {revision_id: draft.latest_revision_id},
  );
  await renderRevisionHistory(draft.scenario_id);
  setAuthoringControls();
}

async function loadAuthoringDraft(scenarioId) {
  const draft = await requestJSON(authoringDraftPath(scenarioId));
  await setActiveDraft(draft);
}

async function loadAuthoringScenarios({selectScenarioId = null} = {}) {
  const catalog = await requestJSON(ENDPOINTS.authoringScenarios);
  authoringDraftSelect.replaceChildren();
  catalog.scenarios.forEach((scenario) => {
    const option = document.createElement("option");
    option.value = scenario.scenario_id;
    option.textContent = `${scenario.scenario_id} · generation ${scenario.draft_generation}`;
    authoringDraftSelect.append(option);
  });
  const selected = selectScenarioId
    ?? activeDraft?.scenario_id
    ?? catalog.scenarios[0]?.scenario_id
    ?? null;
  if (selected !== null && catalog.scenarios.some((item) => item.scenario_id === selected)) {
    await loadAuthoringDraft(selected);
  } else if (catalog.scenarios.length === 0) {
    activeDraft = null;
    selectAuthoringRevision(null);
    setText("authoring-draft-id", "—");
    setText("draft-generation", "—");
    revisionHistory.replaceChildren();
  }
  setAuthoringControls();
}

function previewAuthoringPreset() {
  const preset = authoringPresets.find((item) => item.template_id === authoringPreset.value);
  if (preset !== undefined) {
    authoringContent.value = JSON.stringify(preset.content, null, 2);
  }
}

async function loadAuthoringPresets() {
  const catalog = await requestJSON(ENDPOINTS.authoringPresets);
  authoringPresets = catalog.templates;
  authoringPreset.replaceChildren();
  authoringPresets.forEach((preset) => {
    const option = document.createElement("option");
    option.value = preset.template_id;
    option.textContent = preset.template_id;
    authoringPreset.append(option);
  });
  if (activeDraft === null) {
    previewAuthoringPreset();
  }
  setAuthoringControls();
}

async function createAuthoringDraft() {
  const draft = await authoringWrite(ENDPOINTS.authoringDrafts, {
    content: editorDocument(),
  });
  await loadAuthoringScenarios({selectScenarioId: draft.scenario_id});
  setApplicationStatus("Draft created");
}

async function persistAuthoringEditor() {
  if (activeDraft === null) {
    throw new Error("Select or create a draft first");
  }
  const content = editorDocument();
  if (JSON.stringify(content) === JSON.stringify(activeDraft.content)) {
    return activeDraft;
  }
  const updated = await requestJSON(authoringDraftPath(activeDraft.scenario_id), {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": session.csrfToken,
    },
    body: JSON.stringify({
      content,
      expected_generation: activeDraft.generation,
    }),
  });
  await setActiveDraft(updated, {replaceEditor: false});
  selectAuthoringRevision(null);
  return updated;
}

async function updateAuthoringDraft() {
  await persistAuthoringEditor();
  setApplicationStatus("Draft updated");
}

async function validateAuthoringDraft() {
  const draft = await persistAuthoringEditor();
  const report = await requestJSON(authoringDraftPath(draft.scenario_id, "/validation"));
  renderAuthoringDiagnostics(report);
  setApplicationStatus(report.valid ? "Field validation passed" : "Field validation found issues", report.valid ? "ready" : "error");
  return report;
}

async function saveImmutableRevision() {
  const draft = await persistAuthoringEditor();
  const revision = await authoringWrite(authoringDraftPath(draft.scenario_id, "/revisions"), {
    expected_generation: draft.generation,
  });
  activeDraft.latest_revision_id = revision.revision_id;
  selectAuthoringRevision(revision);
  await renderRevisionHistory(draft.scenario_id);
  setApplicationStatus("Immutable revision saved");
  return revision;
}

async function preflightAuthoringRevision(revision = activeRevision) {
  if (revision === null) {
    throw new Error("Save or select an immutable revision first");
  }
  const result = await authoringWrite(
    authoringRevisionPath(revision.revision_id, "/preflight"),
    {},
  );
  setText("preflight-status", `${result.status} · ${result.executable ? "executable" : "blocked"}`);
  setApplicationStatus(`Preflight ${result.status}`, result.executable ? "ready" : "error");
  return result;
}

async function runAuthoringRevision(revisionId) {
  return authoringWrite(
    authoringRevisionPath(revisionId, "/runs"),
    {},
    {idempotencyKey: crypto.randomUUID()},
  );
}

async function saveAndRunAuthoringRevision() {
  const revision = await saveImmutableRevision();
  const preflight = await preflightAuthoringRevision(revision);
  if (!preflight.executable) {
    throw new Error(`Preflight ${preflight.status} blocks execution`);
  }
  saveAndRunRevisionButton.disabled = true;
  setApplicationStatus("Running immutable revision…");
  const reference = await runAuthoringRevision(revision.revision_id);
  sessionStorage.setItem(ACTIVE_RUN_KEY, reference.run_id);
  await pollRun(reference.run_id);
  setAuthoringControls();
}

async function cloneAuthoringDraft() {
  if (activeDraft === null) {
    return;
  }
  const clone = await authoringWrite(
    authoringScenarioPath(activeDraft.scenario_id, "/clone"),
    {},
  );
  await loadAuthoringScenarios({selectScenarioId: clone.scenario_id});
  setApplicationStatus("Draft cloned");
}

async function archiveAuthoringDraft() {
  if (activeDraft === null) {
    return;
  }
  await authoringWrite(
    authoringScenarioPath(activeDraft.scenario_id, "/archive"),
    {},
  );
  activeDraft = null;
  selectAuthoringRevision(null);
  await loadAuthoringScenarios();
  setApplicationStatus("Draft archived");
}

async function forkAuthoringPreset() {
  const revision = await authoringWrite(
    `${ENDPOINTS.authoringPresets}/${encodeURIComponent(authoringPreset.value)}/fork`,
    {content: editorDocument()},
  );
  await loadAuthoringScenarios({selectScenarioId: revision.scenario_id});
  selectAuthoringRevision(revision);
  setApplicationStatus("Read-only preset forked");
}

async function importAuthoringDraft() {
  const imported = await authoringWrite(ENDPOINTS.authoringImport, {
    format: importFormat.value,
    content: authoringContent.value,
  });
  renderAuthoringDiagnostics(imported.validation);
  await loadAuthoringScenarios({selectScenarioId: imported.draft.scenario_id});
  setApplicationStatus(`${imported.source_format.toUpperCase()} imported`);
}

async function exportAuthoringDraft() {
  if (activeDraft === null) {
    return;
  }
  const exported = await requestJSON(
    `${authoringDraftPath(activeDraft.scenario_id, "/export")}?format=${encodeURIComponent(exportFormat.value)}`,
  );
  authoringContent.value = exported.content;
  setApplicationStatus(`${exported.format.toUpperCase()} exported inline`);
}

function authoringAction(action) {
  return async () => {
    try {
      await action();
    } catch (error) {
      showError(error);
      setAuthoringControls();
    }
  };
}

async function loadBootstrapSession() {
  const payload = await requestJSON(ENDPOINTS.session);
  if (typeof payload.csrf_token !== "string" || payload.csrf_token.length < 32) {
    throw new Error("Server session did not provide a valid request token");
  }
  session = { csrfToken: payload.csrf_token };
}

function renderScenarioComprehension(scenario) {
  scenarioName.textContent = scenario.display_name;
  scenarioDescription.textContent = scenario.description;
  ui.scenarioTargetOutcome.textContent = formatToken(scenario.target_outcome ?? "safe pass");
  ui.scenarioParticipants.replaceChildren();
  (scenario.participants ?? []).forEach((participant) => {
    const item = document.createElement("li");
    item.textContent = `${participant.label} · ${participant.id} (${participant.role})`;
    ui.scenarioParticipants.append(item);
  });
  ui.scenarioRoutes.replaceChildren();
  (scenario.routes ?? []).forEach((route) => {
    const item = document.createElement("li");
    item.textContent = `${route.participant_id}: ${route.summary}`;
    ui.scenarioRoutes.append(item);
  });
  ui.scenarioDanger.textContent = scenario.danger ?? scenario.description;
  ui.scenarioReaction.textContent = scenario.expected_reaction ?? "Follow the registered policy.";
  ui.scenarioSuccess.textContent = scenario.success_meaning ?? "The run completes successfully.";
  ui.scenarioFailure.textContent = scenario.failure_meaning ?? "The run terminates without verified success.";
}

function selectScenario(scenarioId) {
  const scenario = scenarioCatalog.find((item) => item.scenario_id === scenarioId);
  if (scenario === undefined) {
    throw new Error("Registered scenario catalog is unavailable");
  }
  selectedScenario = scenario;
  ui.scenarioSelect.value = scenario.scenario_id;
  renderScenarioComprehension(scenario);
}

async function loadCatalog() {
  const catalog = await requestJSON(ENDPOINTS.catalog);
  const validV1 = catalog.schema_version === "scenarioforge.scenario-catalog/v1" && catalog.scenarios?.length === 1;
  const validV2 = catalog.schema_version === "scenarioforge.scenario-catalog/v2" && catalog.scenarios?.length === 5;
  if (!Array.isArray(catalog.scenarios) || (!validV1 && !validV2)) {
    throw new Error("Registered scenario catalog is unavailable");
  }
  scenarioCatalog = catalog.scenarios;
  ui.scenarioSelect.replaceChildren();
  scenarioCatalog.forEach((scenario) => {
    const option = document.createElement("option");
    option.value = scenario.scenario_id;
    option.textContent = scenario.display_name;
    ui.scenarioSelect.append(option);
  });
  selectScenario(catalog.default_scenario_id ?? scenarioCatalog[0].scenario_id);
  runScenario.disabled = false;
  rebuildStudioTemplates();
}

function selectP1Scenario(scenarioId) {
  const scenario = p1ScenarioCatalog.find((item) => item.scenario_id === scenarioId);
  if (scenario === undefined) {
    throw new Error("Canonical P1 SMARTS catalog is unavailable");
  }
  selectedP1Scenario = scenario;
  p1ScenarioSelect.value = scenario.scenario_id;
  p1ScenarioName.textContent = scenario.display_name;
  p1ScenarioDescription.textContent = scenario.description;
}

async function loadP1Catalog() {
  const catalog = await requestJSON(ENDPOINTS.p1Catalog);
  if (
    catalog.schema_version !== "scenarioforge.p1-scenario-catalog/v1"
    || !Array.isArray(catalog.scenarios)
    || catalog.scenarios.length !== 5
  ) {
    throw new Error("Canonical P1 SMARTS catalog is unavailable");
  }
  p1ScenarioCatalog = catalog.scenarios;
  p1ScenarioSelect.replaceChildren();
  p1ScenarioCatalog.forEach((scenario) => {
    const option = document.createElement("option");
    option.value = scenario.scenario_id;
    option.textContent = scenario.display_name;
    p1ScenarioSelect.append(option);
  });
  selectP1Scenario(catalog.default_scenario_id);
  p1ScenarioSelect.disabled = false;
  runP1Scenario.disabled = false;
  rebuildStudioTemplates();
}

function studioTemplateKey(backend, scenarioId) {
  return `${backend}:${scenarioId}`;
}

function rebuildStudioTemplates() {
  const previous = studioTemplateSelect.value;
  studioTemplateSelect.replaceChildren();
  const groups = [
    {
      label: "MetaDrive scenarios",
      backend: "metadrive",
      scenarios: scenarioCatalog,
    },
    {
      label: "SMARTS scenarios",
      backend: "smarts",
      scenarios: p1ScenarioCatalog,
    },
  ];
  groups.forEach((group) => {
    if (group.scenarios.length === 0) {
      return;
    }
    const optgroup = document.createElement("optgroup");
    optgroup.label = group.label;
    group.scenarios.forEach((scenario) => {
      const option = document.createElement("option");
      option.value = studioTemplateKey(group.backend, scenario.scenario_id);
      option.textContent = scenario.display_name.replace(/^Canonical\s+/, "");
      optgroup.append(option);
    });
    studioTemplateSelect.append(optgroup);
  });
  const available = [...studioTemplateSelect.options].map((item) => item.value);
  const preferred = available.includes(previous)
    ? previous
    : available.includes("smarts:highway_merge")
      ? "smarts:highway_merge"
      : available[0];
  if (preferred !== undefined) {
    studioTemplateSelect.value = preferred;
    selectStudioTemplate(preferred);
  }
  studioTemplateSelect.disabled = available.length === 0;
  updateStudioControls();
}

function selectStudioTemplate(value) {
  const separator = value.indexOf(":");
  if (separator < 1) {
    return;
  }
  const backend = value.slice(0, separator);
  const scenarioId = value.slice(separator + 1);
  const catalog = backend === "smarts" ? p1ScenarioCatalog : scenarioCatalog;
  const scenario = catalog.find((item) => item.scenario_id === scenarioId);
  if (scenario === undefined) {
    throw new Error("The selected scenario is unavailable");
  }
  selectedStudioTemplate = {backend, scenario};
  if (backend === "smarts") {
    selectP1Scenario(scenarioId);
    studioTemplateBackend.textContent = "SMARTS 2.0.1 · local";
  } else {
    selectScenario(scenarioId);
    studioTemplateBackend.textContent = "MetaDrive 0.4.3 · local";
  }
  studioTemplateName.textContent = scenario.display_name.replace(/^Canonical\s+/, "");
  studioTemplateDescription.textContent = scenario.description;
  studioTemplateParticipants.replaceChildren();
  (scenario.participants ?? []).forEach((participant) => {
    const item = document.createElement("li");
    item.textContent = `${participant.label ?? participant.id} · ${formatToken(participant.role)}`;
    studioTemplateParticipants.append(item);
  });
  updateStudioControls();
}

function selectStudioSource(mode) {
  if (!new Set(["natural", "json", "template"]).has(mode)) {
    throw new Error("Unknown scenario source");
  }
  studioSourceMode = mode;
  studioSourceButtons.forEach((button) => {
    button.setAttribute("aria-selected", String(button.dataset.studioSource === mode));
  });
  studioSourcePanels.forEach((panel) => {
    panel.hidden = panel.dataset.studioPanel !== mode;
  });
  studioDocumentPanel.hidden = mode === "template";
  updateStudioControls();
  if (mode !== "template") {
    authoringContent.focus();
  }
}

function updateStudioControls() {
  if (studioSourceMode === "template") {
    studioRun.textContent = "Run selected scenario";
    studioRunTitle.textContent = selectedStudioTemplate === null
      ? "Loading the scenario library"
      : `Ready to run ${selectedStudioTemplate.scenario.display_name.replace(/^Canonical\s+/, "")}`;
    studioRunSummary.textContent = "The selected backend will publish immutable evidence and a trajectory replay.";
    studioRun.disabled = session === null || selectedStudioTemplate === null;
    return;
  }
  if (studioSourceMode === "natural") {
    studioRun.textContent = "Generate, validate & run";
    studioRunTitle.textContent = "Generate one draft and run it";
    studioRunSummary.textContent = "One click creates an immutable revision, validates it, and starts MetaDrive.";
    studioRun.disabled = session === null;
    return;
  }
  studioRun.textContent = "Validate JSON & run";
  studioRunTitle.textContent = "Run the JSON shown above";
  studioRunSummary.textContent = "The exact JSON is saved as an immutable revision before execution.";
  studioRun.disabled = session === null;
}

async function naturalLanguageDocument() {
  const prompt = document.querySelector("#p1-intent").value.trim();
  if (!prompt) {
    throw new Error("Describe the scenario before running it");
  }
  const requestedSeed = Number(document.querySelector("#p1-form-seed").value || 42);
  const requestedDuration = Number(document.querySelector("#p1-form-duration").value || 12);
  const generated = await authoringWrite("/api/authoring/provider-drafts", {
    provider_id: "scenarioforge.offline-reference",
    prompt,
  });
  const providerStatus = document.querySelector("#p1-provider-status");

  const preset = authoringPresets.find(
    (item) => item.template_id === generated.intent_id,
  );
  if (preset !== undefined) {
    const content = structuredClone(preset.content);
    if (Object.hasOwn(content, "seed") && Number.isInteger(requestedSeed)) {
      content.seed = requestedSeed;
    }
    authoringContent.value = JSON.stringify(content, null, 2);
    document.querySelector("#p1-form-title").value = generated.normalized_spec.content.title ?? "";
    providerStatus.textContent = `${generated.intent_id} · matched to an executable canonical scenario`;
    providerStatus.dataset.state = "exact";
    return {content, runTemplate: null};
  }

  const p1ScenarioId = generated.intent_id === "cross_traffic_red_light"
    ? "cross_traffic_red_light_violation"
    : generated.intent_id;
  const p1Scenario = p1ScenarioCatalog.find(
    (item) => item.scenario_id === p1ScenarioId,
  );
  const content = structuredClone(generated.normalized_spec.content);
  content.seed = Number.isInteger(requestedSeed) ? requestedSeed : 42;
  content.constraints ??= {};
  content.constraints.duration_s = Number.isFinite(requestedDuration) && requestedDuration > 0
    ? requestedDuration
    : 12;
  const normalized = await authoringWrite("/api/authoring/normalize", {content});
  authoringContent.value = JSON.stringify(normalized.content, null, 2);
  document.querySelector("#p1-form-title").value = normalized.content.title ?? "";
  document.querySelector("#p1-form-seed").value = String(normalized.content.seed);
  document.querySelector("#p1-form-duration").value = String(normalized.content.constraints.duration_s);
  if (normalized.missing_fields.length > 0) {
    providerStatus.textContent = `Missing required fields: ${normalized.missing_fields.join(", ")}`;
    providerStatus.dataset.state = "error";
    throw new Error(`Generated draft is incomplete: ${normalized.missing_fields.join(", ")}`);
  }
  if (p1Scenario === undefined) {
    throw new Error("The generated intent has no executable local scenario");
  }
  providerStatus.textContent = `${generated.intent_id} · matched to ${p1Scenario.display_name.replace(/^Canonical\s+/, "")}`;
  providerStatus.dataset.state = "exact";
  return {
    content: normalized.content,
    runTemplate: {backend: "smarts", scenario: p1Scenario},
  };
}

async function runStudioDocument(content) {
  const draft = await authoringWrite(ENDPOINTS.authoringDrafts, {content});
  await loadAuthoringScenarios({selectScenarioId: draft.scenario_id});
  if (content.schema_version === "scenarioforge.authoring/v1") {
    const validation = await validateAuthoringDraft();
    if (!validation.valid) {
      throw new Error("Scenario validation found fields that must be corrected");
    }
  }
  const revision = await saveImmutableRevision();
  const preflight = await preflightAuthoringRevision(revision);
  if (!preflight.executable) {
    throw new Error(`Preflight ${preflight.status} blocks execution`);
  }
  setApplicationStatus("Running immutable scenario…");
  const reference = await runAuthoringRevision(revision.revision_id);
  sessionStorage.setItem(ACTIVE_RUN_KEY, reference.run_id);
  await pollRun(reference.run_id);
}

async function startStudioRun() {
  studioRun.disabled = true;
  try {
    if (studioSourceMode === "template") {
      if (selectedStudioTemplate === null) {
        throw new Error("Choose a built-in scenario first");
      }
      if (selectedStudioTemplate.backend === "smarts") {
        await startP1Run();
      } else {
        await startRun();
      }
      return;
    }
    if (studioSourceMode === "natural") {
      const generated = await naturalLanguageDocument();
      if (generated.runTemplate !== null) {
        selectedStudioTemplate = generated.runTemplate;
        selectP1Scenario(generated.runTemplate.scenario.scenario_id);
        await startP1Run();
      } else {
        await runStudioDocument(generated.content);
      }
      return;
    }
    await runStudioDocument(editorDocument());
  } catch (error) {
    showError(error);
  } finally {
    updateStudioControls();
  }
}

async function startRun() {
  if (selectedScenario === null || session === null) {
    return;
  }
  resetReplay();
  playbackPanel.hidden = true;
  runScenario.disabled = true;
  setApplicationStatus("Starting run…");
  const idempotencyKey = crypto.randomUUID();
  try {
    const reference = await requestJSON(ENDPOINTS.runs, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": session.csrfToken,
        "Idempotency-Key": idempotencyKey,
      },
      body: JSON.stringify({ scenario_id: selectedScenario.scenario_id }),
    });
    sessionStorage.setItem(ACTIVE_RUN_KEY, reference.run_id);
    await pollRun(reference.run_id);
  } catch (error) {
    showError(error);
    runScenario.disabled = false;
  }
}

async function startP1Run() {
  if (selectedP1Scenario === null || session === null) {
    return;
  }
  selectedScenario = selectedP1Scenario;
  resetReplay();
  playbackPanel.hidden = true;
  runP1Scenario.disabled = true;
  runScenario.disabled = true;
  setApplicationStatus("Starting real SMARTS run…");
  try {
    const reference = await requestJSON(ENDPOINTS.p1Runs, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": session.csrfToken,
        "Idempotency-Key": crypto.randomUUID(),
      },
      body: JSON.stringify({scenario_id: selectedP1Scenario.scenario_id}),
    });
    await pollRun(reference.run_id, ENDPOINTS.p1Runs);
  } catch (error) {
    showError(error);
    runP1Scenario.disabled = false;
    runScenario.disabled = false;
  }
}

function renderLive(active) {
  terminalPanel.hidden = true;
  playbackPanel.hidden = true;
  livePanel.hidden = false;
  liveState.textContent = active.state;
  liveRunId.textContent = active.run_id;
  setApplicationStatus(`Run ${active.state}…`);
}

function appendEvidence(terminal) {
  evidenceList.replaceChildren();
  terminal.evidence.forEach((entry) => {
    const item = document.createElement("li");
    item.textContent = `${entry.ref} · ${entry.status}/${entry.validation} · sha256:${entry.digest}`;
    evidenceList.append(item);
  });
}

function appendTerminalEvents(terminal) {
  terminalEvents.replaceChildren();
  terminal.events.forEach((event) => {
    const item = document.createElement("li");
    const duration = event.duration_ticks === undefined ? "" : ` · ${event.duration_ticks} tick effect`;
    item.textContent = `tick ${event.trigger_tick} → ${event.effect_state_tick} · ${event.event_id} · ${event.participant_id}${duration}`;
    terminalEvents.append(item);
  });
  if (terminal.events.length === 0) {
    const item = document.createElement("li");
    item.textContent = "No fully verified key events were published.";
    terminalEvents.append(item);
  }
}

function metricValue(projection) {
  if (projection.value === null) {
    return `Not observed · ${projection.null_semantics}`;
  }
  if (typeof projection.value === "boolean") {
    return projection.value ? "Yes" : "No";
  }
  return `${projection.value} ${projection.unit}`;
}

function renderMetricProjections(terminal) {
  ui.metricProjections.replaceChildren();
  (terminal.metric_projections ?? []).forEach((projection) => {
    const card = document.createElement("article");
    card.className = "metric-projection";
    card.dataset.metric = projection.metric;
    const title = document.createElement("h3");
    title.textContent = formatToken(projection.metric);
    const value = document.createElement("strong");
    value.textContent = metricValue(projection);
    const definition = document.createElement("p");
    definition.textContent = `${projection.definition_id} · unit ${projection.unit}`;
    const participants = document.createElement("p");
    participants.textContent = `Participants: ${projection.participant_ids.join(", ")}`;
    const explanation = document.createElement("p");
    explanation.textContent = projection.explanation;
    const threshold = document.createElement("p");
    threshold.textContent = `${formatThreshold(projection.threshold, projection.unit)} · met ${formatBoolean(projection.threshold_met)}`;
    const raw = document.createElement("p");
    raw.className = "raw-evidence";
    raw.textContent = `Raw evidence (${projection.evidence_field}): ${String(projection.raw_evidence_value)}`;
    card.append(title, value, definition, participants, explanation, threshold, raw);
    ui.metricProjections.append(card);
  });
}

async function renderTerminal(terminal, runsEndpoint = ENDPOINTS.runs) {
  livePanel.hidden = true;
  terminalPanel.hidden = false;
  sessionStorage.removeItem(ACTIVE_RUN_KEY);
  TERMINAL_FIELDS.forEach(([id, project]) => setText(id, project(terminal)));
  appendEvidence(terminal);
  appendTerminalEvents(terminal);
  renderMetricProjections(terminal);
  const status = terminal.execution_status ?? terminal.status;
  const reason = terminal.termination_reason ?? terminal.reason;
  ui.scenarioOutcome.textContent = formatToken(terminal.scenario_outcome ?? status);
  ui.recordedEvidenceBadge.textContent = terminal.scenario_outcome === "collision_failure"
    ? "Recorded collision evidence"
    : "Recorded immutable evidence";
  setApplicationStatus(`Terminal · ${status}`);

  const legacyTerminalBlocked = terminal.schema_version === "scenarioforge.terminal-evidence/v1"
    && (terminal.status !== "success" || terminal.playable !== true);
  const v2TerminalBlocked = terminal.schema_version === "scenarioforge.terminal-evidence/v2"
    && terminal.playable !== true;
  if (legacyTerminalBlocked || v2TerminalBlocked) {
    resetReplay();
    playbackPanel.hidden = true;
    nonPlayable.hidden = false;
    nonPlayable.textContent = `Playback unavailable: ${terminal.playback_reason ?? "terminal evidence is not a fully verified success"}. State ${status}; reason ${reason}; stage ${terminal.failure_stage ?? "not applicable"}.`;
    return;
  }

  nonPlayable.hidden = true;
  await loadPlayback(terminal.run_id, runsEndpoint);
}

async function pollRun(runId, runsEndpoint = ENDPOINTS.runs) {
  pollingRunId = runId;
  while (pollingRunId === runId) {
    const status = await requestJSON(scopedRunStatus(runId, runsEndpoint));
    if (status.terminal === true) {
      pollingRunId = null;
      await renderTerminal(status, runsEndpoint);
      runScenario.disabled = false;
      runP1Scenario.disabled = false;
      return;
    }
    renderLive(status);
    await new Promise((resolve) => window.setTimeout(resolve, POLL_INTERVAL_MS));
  }
}

function addRoadSurface(width, depth, centerX, centerZ) {
  const geometry = new THREE.PlaneGeometry(width, depth);
  const material = new THREE.MeshStandardMaterial({ color: 0x26312e, roughness: 0.92 });
  const surface = new THREE.Mesh(geometry, material);
  surface.rotation.x = -Math.PI / 2;
  surface.position.set(centerX, -0.05, centerZ);
  state.scene.add(surface);
}

function addRoadStrip(left, right, {color, opacity = 1, elevation = 0, userData = {}}) {
  const positions = [];
  const indices = [];
  left.forEach((point, index) => {
    positions.push(point[0], elevation, -point[1]);
    positions.push(right[index][0], elevation, -right[index][1]);
    if (index < left.length - 1) {
      const offset = index * 2;
      indices.push(offset, offset + 1, offset + 2, offset + 1, offset + 3, offset + 2);
    }
  });
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  geometry.setIndex(indices);
  geometry.computeVertexNormals();
  const material = new THREE.MeshStandardMaterial({
    color,
    opacity,
    transparent: opacity < 1,
    roughness: 0.9,
    side: THREE.DoubleSide,
  });
  const strip = new THREE.Mesh(geometry, material);
  Object.assign(strip.userData, userData);
  state.scene.add(strip);
}

function addRoadLine(points, color, {dashed = false, userData = {}} = {}) {
  const geometry = new THREE.BufferGeometry().setFromPoints(
    points.map((point) => new THREE.Vector3(point[0], 0.025, -point[1])),
  );
  const material = dashed
    ? new THREE.LineDashedMaterial({color, dashSize: 2.2, gapSize: 1.8})
    : new THREE.LineBasicMaterial({color});
  const line = new THREE.Line(geometry, material);
  Object.assign(line.userData, userData);
  if (dashed) {
    line.computeLineDistances();
  }
  state.scene.add(line);
}

function addRoadsideBlocks(
  points,
  {width, height, elevation, color, userData = {}},
) {
  for (let index = 0; index < points.length - 1; index += 1) {
    const [startX, startY] = points[index];
    const [endX, endY] = points[index + 1];
    const startZ = -startY;
    const endZ = -endY;
    const deltaX = endX - startX;
    const deltaZ = endZ - startZ;
    const length = Math.hypot(deltaX, deltaZ);
    if (length <= 1e-6) {
      continue;
    }
    const block = new THREE.Mesh(
      new THREE.BoxGeometry(length, height, width),
      new THREE.MeshStandardMaterial({color, roughness: 0.82}),
    );
    block.position.set(
      (startX + endX) / 2,
      elevation + height / 2,
      (startZ + endZ) / 2,
    );
    block.rotation.y = -Math.atan2(deltaZ, deltaX);
    Object.assign(block.userData, userData);
    block.receiveShadow = true;
    state.scene.add(block);
  }
}

function boundaryKey(points) {
  const forward = JSON.stringify(points.map((point) => point.map((value) => Number(value.toFixed(3)))));
  const reverse = JSON.stringify([...points].reverse().map((point) => point.map((value) => Number(value.toFixed(3)))));
  return forward < reverse ? forward : reverse;
}

function renderCurbs(playback) {
  const boundaries = new Map();
  playback.road.geometry.lanes.forEach((lane) => {
    for (const points of [lane.left_boundary_m, lane.right_boundary_m]) {
      const key = boundaryKey(points);
      const record = boundaries.get(key) ?? {count: 0, points};
      record.count += 1;
      boundaries.set(key, record);
    }
  });
  let curbCount = 0;
  boundaries.forEach(({count, points}) => {
    if (count !== 1) {
      return;
    }
    addRoadsideBlocks(points, {
      width: 0.20,
      height: 0.13,
      elevation: 0,
      color: 0xb4bab5,
      userData: {roadElement: "curb"},
    });
    curbCount += Math.max(0, points.length - 1);
  });
  replayCanvas.dataset.curbSegmentCount = String(curbCount);
}

function conflictCentre(playback) {
  const points = playback.road.geometry.conflict_zones.flatMap((zone) => (
    zone.lane_regions.flatMap((region) => [
      ...region.left_boundary_m,
      ...region.right_boundary_m,
    ])
  ));
  if (points.length === 0) {
    return null;
  }
  return [
    points.reduce((total, point) => total + point[0], 0) / points.length,
    points.reduce((total, point) => total + point[1], 0) / points.length,
  ];
}

function renderStopLines(playback) {
  const centre = conflictCentre(playback);
  if (centre === null) {
    replayCanvas.dataset.stopLineCount = "0";
    return;
  }
  let stopLineCount = 0;
  playback.road.geometry.lanes.forEach((lane) => {
    if (lane.kind === "turn" || lane.left_boundary_m.length !== lane.right_boundary_m.length) {
      return;
    }
    const centers = lane.left_boundary_m.map((left, index) => {
      const right = lane.right_boundary_m[index];
      return [(left[0] + right[0]) / 2, (left[1] + right[1]) / 2];
    });
    const nearestIndex = centers.reduce((best, point, index) => (
      Math.hypot(point[0] - centre[0], point[1] - centre[1])
        < Math.hypot(centers[best][0] - centre[0], centers[best][1] - centre[1])
        ? index
        : best
    ), 0);
    addRoadsideBlocks(
      [lane.left_boundary_m[nearestIndex], lane.right_boundary_m[nearestIndex]],
      {
        width: 0.38,
        height: 0.025,
        elevation: 0.025,
        color: 0xf7fbf6,
        userData: {roadElement: "stop-line", laneId: lane.lane_id},
      },
    );
    stopLineCount += 1;
  });
  replayCanvas.dataset.stopLineCount = String(stopLineCount);
}

function signalStates(playback) {
  const states = new Map();
  playback.trajectory.forEach((sample) => {
    (sample.signals ?? []).forEach((signal) => {
      if (!states.has(signal.signal_id)) {
        states.set(signal.signal_id, signal.state);
      }
    });
  });
  return states;
}

function renderTrafficSignals(playback) {
  state.signalHeads.clear();
  const signals = signalStates(playback);
  const centre = conflictCentre(playback);
  if (signals.size === 0 || centre === null) {
    replayCanvas.dataset.trafficSignalCount = "0";
    return;
  }
  [...signals.entries()].forEach(([signalId, signalState], index) => {
    const angle = index * (Math.PI * 2 / signals.size) + Math.PI / 4;
    const signal = new THREE.Group();
    const pole = new THREE.Mesh(
      new THREE.CylinderGeometry(0.08, 0.1, 3.5, 12),
      new THREE.MeshStandardMaterial({color: 0x65716d, metalness: 0.42, roughness: 0.5}),
    );
    pole.position.y = 1.75;
    const housing = new THREE.Mesh(
      new THREE.BoxGeometry(0.55, 1.45, 0.38),
      new THREE.MeshStandardMaterial({color: 0x18211f, roughness: 0.7}),
    );
    housing.position.y = 3.45;
    signal.add(pole, housing);
    const bulbs = {};
    [["red", 3.88], ["yellow", 3.45], ["green", 3.02]].forEach(([name, y]) => {
      const material = new THREE.MeshStandardMaterial({
        color: {red: 0x5a1717, yellow: 0x594d19, green: 0x174d2a}[name],
        emissive: {red: 0xff2d2d, yellow: 0xffcb35, green: 0x35e47a}[name],
        emissiveIntensity: name === signalState ? 2.6 : 0.08,
      });
      const bulb = new THREE.Mesh(new THREE.SphereGeometry(0.16, 16, 10), material);
      bulb.position.set(0, y, -0.21);
      signal.add(bulb);
      bulbs[name] = bulb;
    });
    signal.position.set(
      centre[0] + Math.cos(angle) * 6,
      0,
      -(centre[1] + Math.sin(angle) * 6),
    );
    signal.lookAt(centre[0], 2.2, -centre[1]);
    signal.userData.signalId = signalId;
    signal.userData.roadElement = "traffic-signal";
    state.signalHeads.set(signalId, {bulbs, state: signalState});
    state.scene.add(signal);
  });
  replayCanvas.dataset.trafficSignalCount = String(signals.size);
}

function updateTrafficSignals(tick) {
  const samples = state.frames.get(tick);
  if (samples === undefined) {
    return;
  }
  const observed = new Map();
  samples.forEach((sample) => {
    (sample.signals ?? []).forEach((signal) => observed.set(signal.signal_id, signal.state));
  });
  state.signalHeads.forEach((head, signalId) => {
    const signalState = observed.get(signalId) ?? head.state;
    Object.entries(head.bulbs).forEach(([name, bulb]) => {
      bulb.material.emissiveIntensity = name === signalState ? 2.6 : 0.08;
    });
    head.state = signalState;
  });
}

function renderConflictZones(playback) {
  const geometry = playback.road.geometry;
  geometry.conflict_zones.forEach((zone) => {
    zone.lane_regions.forEach((region) => {
      addRoadStrip(region.left_boundary_m, region.right_boundary_m, {
        color: 0xff7d71,
        opacity: 0.42,
        elevation: 0.04,
        userData: {conflictZoneId: zone.zone_id, laneId: region.lane_id},
      });
    });
  });
}

function isDetailedPlayback(playback) {
  return ["scenarioforge.playback/v2", "scenarioforge.p1-playback/v1"].includes(
    playback.schema_version,
  );
}

function renderRoad(playback) {
  if (playback.schema_version === "scenarioforge.playback/v1") {
    const road = playback.road;
    const roadWidth = road.lane_count * road.lane_width_m;
    addRoadSurface(road.length_m, roadWidth, road.length_m / 2, 0);
    for (let lane = 1; lane < road.lane_count; lane += 1) {
      const markerGeometry = new THREE.BoxGeometry(road.length_m, 0.015, 0.045);
      const markerMaterial = new THREE.MeshBasicMaterial({ color: 0x829088 });
      const laneMarker = new THREE.Mesh(markerGeometry, markerMaterial);
      laneMarker.position.set(road.length_m / 2, 0.01, roadWidth / 2 - lane * road.lane_width_m);
      state.scene.add(laneMarker);
    }
    return;
  }
  const geometry = playback.road.geometry;
  const colors = {
    closed: 0x70483f,
    closing: 0x62594a,
    ramp: 0x3e625c,
    turn: 0x4a5d58,
  };
  geometry.lanes.forEach((lane) => {
    addRoadStrip(lane.left_boundary_m, lane.right_boundary_m, {
      color: colors[lane.kind] ?? 0x45625a,
      elevation: -0.02,
      userData: {laneId: lane.lane_id, laneKind: lane.kind},
    });
    addRoadLine(lane.left_boundary_m, lane.kind === "closed" ? 0xff8b67 : 0xffd34e, {
      userData: {roadElement: "centre-divider", laneId: lane.lane_id},
    });
    addRoadLine(lane.right_boundary_m, 0xf3f7f2, {
      dashed: lane.kind !== "closed",
      userData: {roadElement: "lane-boundary", laneId: lane.lane_id},
    });
  });
  renderConflictZones(playback);
  renderCurbs(playback);
  renderStopLines(playback);
  renderTrafficSignals(playback);
  replayCanvas.dataset.topologyKind = playback.road.topology_kind;
  replayCanvas.dataset.geometrySource = geometry.source;
  replayCanvas.dataset.laneCount = String(geometry.lanes.length);
  replayCanvas.dataset.conflictZoneCount = String(geometry.conflict_zones.length);
  replayCanvas.dataset.roadElements = [
    "road-surface",
    "curbs",
    "lane-lines",
    "stop-lines",
    "traffic-signals",
    "intersection",
    "conflict-zones",
  ].join(",");
  roadLegend.replaceChildren();
  const title = document.createElement("strong");
  title.textContent = `${formatToken(playback.road.topology_kind)} · ${geometry.lanes.length} verified lane${geometry.lanes.length === 1 ? "" : "s"}`;
  const source = document.createElement("span");
  source.textContent = geometry.source === "metadrive-road-network"
    ? "Road edges and centre lines: recorded MetaDrive geometry"
    : `Road edges and centre lines: ${geometry.source}`;
  roadLegend.append(title, source);
  const cues = document.createElement("span");
  cues.textContent = "Visible cues: asphalt, raised curbs, yellow divider, white lane edges, stop lines, signal heads, intersections and recorded conflict zones.";
  roadLegend.append(cues);
  geometry.conflict_zones.forEach((zone) => {
    const explanation = document.createElement("span");
    explanation.textContent = `Red hatch: ${formatToken(zone.zone_id)} (${zone.start_m}–${zone.end_m} m on ${zone.lane_regions.map((region) => region.lane_id).join(", ")})`;
    roadLegend.append(explanation);
  });
  state.replayScene.visualContext.elements
    .filter((element) => element.status === "not-applicable")
    .forEach((element) => {
      const explanation = document.createElement("span");
      explanation.textContent = `${element.label}: not applicable (not declared by evidence)`;
      roadLegend.append(explanation);
    });
}

function participantColor(participant, index) {
  if (participant.id === "ego") {
    return 0x6de4d1;
  }
  if (participant.id === "lead") {
    return 0xffb95c;
  }
  if (participant.role === "controlled") {
    return 0x8ea7ff;
  }
  if (participant.role === "pedestrian") {
    return 0xf88bc4;
  }
  return [0xffb95c, 0x9ca8ff, 0xf69dc7, 0xc6f36a][index % 4];
}

function renderParticipants(playback) {
  participantLegend.replaceChildren();
  state.meshes.clear();
  state.participantReadouts.clear();
  playback.participants.forEach((participant, index) => {
    const color = participantColor(participant, index);
    let vehicle;
    if (participant.role === "pedestrian") {
      vehicle = new THREE.Group();
      const body = new THREE.Mesh(
        new THREE.CapsuleGeometry(0.38, 1.05, 6, 12),
        new THREE.MeshStandardMaterial({color, roughness: 0.5}),
      );
      body.position.y = 0.35;
      vehicle.add(body);
      vehicle.userData.brakeLights = new THREE.Group();
      vehicle.userData.groundOffsetM = 0.72;
    } else {
      vehicle = createVehicleModel(THREE, {
        color,
        dimensions: vehicleDimensionsFor(
          playback.scenario_id,
          participant.id,
          participant.role,
        ),
      });
    }
    vehicle.userData.participantId = participant.id;
    state.scene.add(vehicle);
    state.meshes.set(participant.id, vehicle);
    const point = state.frames.get(participant.id)?.get(0);
    const mesh = vehicle;
    if (point !== undefined) {
      mesh.rotation.y = THREE.MathUtils.degToRad(point.heading_deg);
    }

    const legendItem = document.createElement("li");
    legendItem.dataset.participantId = participant.id;
    legendItem.dataset.brakeState = "off";
    const swatch = document.createElement("span");
    swatch.className = `participant-swatch participant-swatch--${participant.id}`;
    swatch.style.backgroundColor = `#${color.toString(16).padStart(6, "0")}`;
    swatch.setAttribute("aria-hidden", "true");
    const label = document.createElement("span");
    const catalogScenario = playback.schema_version === "scenarioforge.p1-playback/v1"
      ? selectedP1Scenario
      : selectedScenario;
    const metadata = catalogScenario?.participants?.find((item) => item.id === participant.id);
    label.textContent = `${metadata?.label ?? participant.id} · ${participant.id} (${participant.role})`;
    const readout = document.createElement("span");
    readout.className = "participant-state";
    readout.textContent = "0.0 m/s · coasting";
    const text = document.createElement("span");
    text.append(label, document.createElement("br"), readout);
    legendItem.append(swatch, text);
    participantLegend.append(legendItem);
    state.participantReadouts.set(participant.id, readout);
  });
  const vehicleModels = [...state.meshes.values()].filter((mesh) => mesh.userData.assetId);
  replayCanvas.dataset.vehicleModelAsset = VEHICLE_MODEL_CONTRACT.assetId;
  replayCanvas.dataset.vehicleModelVersion = VEHICLE_MODEL_CONTRACT.version;
  replayCanvas.dataset.vehicleModelFeatures = VEHICLE_MODEL_CONTRACT.features.join(",");
  replayCanvas.dataset.vehicleModelCount = String(vehicleModels.length);
  replayCanvas.dataset.modelScaleErrorMax = String(Math.max(
    0,
    ...vehicleModels.map((mesh) => mesh.userData.modelScaleRelativeError),
  ));
}

function renderKeyEvents(events) {
  eventPositions.replaceChildren();
  state.eventSeekTicks = [...new Set(events.map((event) => {
    const preroll = Math.max(0, event.trigger_tick - EVENT_PREROLL_TICKS);
    return preroll === 0 && event.trigger_tick > 0 ? event.trigger_tick : preroll;
  }))].sort((a, b) => a - b);
  events.forEach((event) => {
    const item = document.createElement("li");
    const marker = document.createElement("button");
    marker.type = "button";
    marker.className = "event-marker";
    marker.dataset.tick = String(event.trigger_tick);
    marker.textContent = `tick ${event.trigger_tick} · ${event.event_id}`;
    marker.addEventListener("click", () => setReplayTick(event.trigger_tick));
    item.append(marker);
    eventPositions.append(item);
  });
}

function activeParticipantEvents(participantId, tick) {
  return state.playbackEvents.filter((event) => (
    event.participant_id === participantId
    && tick >= event.trigger_tick
    && tick < event.trigger_tick + (event.duration_ticks ?? 1)
  ));
}

function indexTrajectory(trajectory) {
  state.frames.clear();
  trajectory.forEach((point) => {
    if (!state.frames.has(point.tick)) {
      state.frames.set(point.tick, new Map());
    }
    state.frames.get(point.tick).set(point.participant_id, point);
  });
}

function indexReplayTracks(scene) {
  state.tracks = new Map(
    scene.tracks.map((track) => [track.participantId, track]),
  );
}

function calculateReplayFrame(playback) {
  let minX = Number.POSITIVE_INFINITY;
  let maxX = Number.NEGATIVE_INFINITY;
  let minZ = Number.POSITIVE_INFINITY;
  let maxZ = Number.NEGATIVE_INFINITY;
  playback.trajectory.forEach((point) => {
    const x = point.position_m[0];
    const z = -point.position_m[1];
    minX = Math.min(minX, x);
    maxX = Math.max(maxX, x);
    minZ = Math.min(minZ, z);
    maxZ = Math.max(maxZ, z);
  });
  if (isDetailedPlayback(playback)) {
    playback.road.geometry.lanes.forEach((lane) => {
      [...lane.left_boundary_m, ...lane.right_boundary_m].forEach((point) => {
        minX = Math.min(minX, point[0]);
        maxX = Math.max(maxX, point[0]);
        minZ = Math.min(minZ, -point[1]);
        maxZ = Math.max(maxZ, -point[1]);
      });
    });
  }
  if (!Number.isFinite(minX)) {
    return { centerX: 0, centerZ: 0, halfWidth: 20, halfDepth: 12 };
  }
  let roadHalfWidth = 0;
  if (playback.schema_version === "scenarioforge.playback/v1") {
    roadHalfWidth = (playback.road.lane_count * playback.road.lane_width_m) / 2;
    minZ = Math.min(minZ, -roadHalfWidth);
    maxZ = Math.max(maxZ, roadHalfWidth);
  } else {
    roadHalfWidth = Math.max(4, (maxZ - minZ) / 2);
  }
  return {
    centerX: (minX + maxX) / 2,
    centerZ: (minZ + maxZ) / 2,
    halfWidth: Math.max((maxX - minX) / 2 + 6, 10),
    halfDepth: Math.max((maxZ - minZ) / 2 + 4, roadHalfWidth + 4),
  };
}

function calculateConflictFrame(playback) {
  if (!isDetailedPlayback(playback)) {
    return null;
  }
  const points = playback.road.geometry.conflict_zones.flatMap((zone) => (
    zone.lane_regions.flatMap((region) => [
      ...region.left_boundary_m,
      ...region.right_boundary_m,
    ])
  ));
  if (points.length === 0) {
    return null;
  }
  const xs = points.map((point) => point[0]);
  const zs = points.map((point) => -point[1]);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minZ = Math.min(...zs);
  const maxZ = Math.max(...zs);
  return {
    centerX: (minX + maxX) / 2,
    centerZ: (minZ + maxZ) / 2,
    halfWidth: Math.max((maxX - minX) / 2 + 8, 10),
    halfDepth: Math.max((maxZ - minZ) / 2 + 8, 10),
  };
}

function updateSimulationTime() {
  ui.simulationTime.value = `${state.currentTimeS.toFixed(2)} s`;
  ui.simulationTime.dataset.timeS = String(state.currentTimeS);
}

function updateFollowCamera(egoPose, elapsedMs = 0) {
  if (state.cameraMode !== "ego-follow" || state.camera === null || egoPose === null) {
    return;
  }
  state.followCameraState = createFollowCameraState(
    {positionM: egoPose.positionM, headingDeg: egoPose.headingDeg},
    elapsedMs > 0 ? state.followCameraState : null,
    elapsedMs,
  );
  const cameraState = state.followCameraState;
  resizeRendererSurface();
  state.camera.position.set(...cameraState.cameraPosition);
  state.camera.up.set(...cameraState.stableHorizon);
  state.camera.lookAt(...cameraState.lookAt);
  const quality = followCameraQuality(cameraState);
  replayCanvas.dataset.followErrorM = String(quality.followErrorM);
  replayCanvas.dataset.lookDirectionErrorDeg = String(quality.viewDirectionErrorDeg);
  replayCanvas.dataset.cameraWithinTolerance = String(quality.withinTolerance);
  replayCanvas.dataset.followPose = JSON.stringify({
    source_tick: egoPose.lowerTick,
    position_m: egoPose.positionM,
    heading_deg: egoPose.headingDeg,
    camera_position: cameraState.cameraPosition,
    look_at: cameraState.lookAt,
  });
}

function resizeRendererSurface() {
  if (state.renderer === null || state.camera === null) {
    return false;
  }
  const width = replayCanvas.clientWidth;
  if (width <= 0) {
    return false;
  }
  const height = Math.max(360, Math.round(width * 0.48));
  state.renderer.setSize(width, height, false);
  state.camera.aspect = width / height;
  state.camera.updateProjectionMatrix();
  return true;
}

function renderReplayFrame() {
  if (state.renderer !== null && state.scene !== null && state.camera !== null) {
    state.renderer.render(state.scene, state.camera);
  }
}

function setReplayTime(requestedTimeS, elapsedMs = 0) {
  const timeS = Math.max(0, Math.min(state.terminalTimeS, Number(requestedTimeS)));
  if (!Number.isFinite(timeS)) {
    return;
  }
  let egoPose = null;
  state.tracks.forEach((track, participantId) => {
    const pose = interpolatePose(track.samples, timeS);
    const mesh = state.meshes.get(participantId);
    if (mesh === undefined) {
      return;
    }
    mesh.position.set(
      pose.renderPositionM[0],
      mesh.userData.groundOffsetM ?? 0,
      pose.renderPositionM[2],
    );
    mesh.rotation.y = pose.renderYawRad;
    const tick = pose.lowerTick;
    const participantEvents = activeParticipantEvents(participantId, tick);
    const braking = participantEvents.some((event) => event.action?.throttle_brake < 0);
    mesh.userData.brakeLights.visible = braking;
    const readout = state.participantReadouts.get(participantId);
    if (readout !== undefined) {
      const conditions = [braking ? "BRAKING" : "coasting"];
      if (pose.collision) {
        conditions.push("COLLISION");
      }
      readout.textContent = `${Number(pose.speedMps).toFixed(1)} m/s · ${conditions.join(" · ")}`;
      readout.closest("li").dataset.brakeState = braking ? "on" : "off";
    }
    if (participantId === state.replayScene.camera.egoParticipantId) {
      egoPose = pose;
      state.currentEgoPose = {
        position_m: pose.positionM,
        heading_deg: pose.headingDeg,
      };
      replayCanvas.dataset.interpolationSourceTicks = pose.sourceTicks.join(",");
    }
  });
  const tick = Math.min(
    state.terminalTick,
    Math.max(0, Math.floor(timeS / (state.sampleIntervalMs / 1000) + 1e-9)),
  );
  const active = state.playbackEvents.filter((event) => (
    tick >= event.trigger_tick
    && tick < event.trigger_tick + (event.duration_ticks ?? 1)
  ));
  activeEvents.textContent = active.length === 0
    ? "No active key event"
    : active.map((event) => `${formatToken(event.event_id)} · ${event.participant_id}`).join(" | ");
  replayOutcome.textContent = `Recorded result: ${formatToken(state.scenarioOutcome)}`;
  state.currentTick = tick;
  state.currentTimeS = timeS;
  replayTimeline.value = String(timelineTickForTime(
    timeS,
    state.sampleIntervalMs / 1000,
    state.terminalTick,
  ));
  currentTick.value = String(tick);
  updateSimulationTime();
  updateFollowCamera(egoPose, elapsedMs);
  updateTrafficSignals(tick);
  renderReplayFrame();
}

function setReplayTick(requestedTick) {
  setReplayTime(Number(requestedTick) * (state.sampleIntervalMs / 1000));
}

function seekRelativeEvent(direction) {
  const ordered = state.eventSeekTicks;
  const requested = direction > 0
    ? ordered.find((tick) => tick > state.currentTick)
    : ordered.findLast((tick) => tick < state.currentTick);
  if (requested !== undefined) {
    state.playing = false;
    replayToggle.textContent = "Play replay";
    setReplayTick(requested);
  }
}

function restartReplay() {
  state.playing = false;
  replayToggle.textContent = "Play replay";
  setReplayTick(0);
}

function applyCameraMode(mode) {
  const normalizedMode = mode === "conflict" ? "conflict-focus" : mode;
  state.cameraMode = ["ego-follow", "overview", "conflict-focus", "fixed", "free"].includes(normalizedMode)
    ? normalizedMode
    : "ego-follow";
  replayCanvas.dataset.cameraMode = state.cameraMode;
  replayCanvas.dataset.cameraScope = state.cameraMode === "conflict-focus" && state.conflictFrame !== null
    ? "verified-conflict-geometry"
    : state.cameraMode === "ego-follow"
      ? "evidence-bound-ego"
      : "complete-road-and-trajectory";
  if (state.cameraMode === "ego-follow") {
    state.followCameraState = null;
    setReplayTime(state.currentTimeS);
    return;
  }
  if (["fixed", "free"].includes(state.cameraMode)) {
    const frame = state.cameraFrame;
    const targetPose = state.currentEgoPose ?? {
      position_m: [frame.centerX, -frame.centerZ],
      heading_deg: 0,
    };
    state.freeCameraState = createP1CameraState(state.cameraMode, {
      targetPose,
      bounds: {
        center_m: [frame.centerX, -frame.centerZ],
        half_extents_m: [frame.halfWidth, frame.halfDepth],
      },
    });
    applyP1CameraState(state.freeCameraState);
    return;
  }
  resizeRenderer();
}

function applyP1CameraState(cameraState) {
  if (state.camera === null) {
    return;
  }
  resizeRendererSurface();
  state.camera.position.set(...cameraState.position);
  state.camera.up.set(0, 1, 0);
  state.camera.lookAt(...cameraState.lookAt);
  renderReplayFrame();
}

function resizeRenderer() {
  if (state.renderer === null || state.camera === null || state.cameraFrame === null) {
    return;
  }
  if (!resizeRendererSurface()) {
    return;
  }
  const width = state.renderer.domElement.width / state.renderer.getPixelRatio();
  const height = state.renderer.domElement.height / state.renderer.getPixelRatio();
  const verticalFov = THREE.MathUtils.degToRad(state.camera.fov);
  const horizontalFov = 2 * Math.atan(Math.tan(verticalFov / 2) * state.camera.aspect);
  const frame = state.cameraMode === "conflict-focus" && state.conflictFrame !== null
    ? state.conflictFrame
    : state.cameraFrame;
  const fitDistance = Math.max(
    frame.halfWidth / Math.tan(horizontalFov / 2),
    frame.halfDepth / Math.tan(verticalFov / 2),
    18,
  ) * 1.15;
  const elevation = THREE.MathUtils.degToRad(state.cameraMode === "conflict-focus" ? 68 : 55);
  state.camera.position.set(
    frame.centerX,
    fitDistance * Math.sin(elevation),
    frame.centerZ + fitDistance * Math.cos(elevation),
  );
  state.camera.near = Math.max(0.1, fitDistance / 100);
  state.camera.far = Math.max(500, fitDistance * 6);
  state.camera.lookAt(frame.centerX, 0, frame.centerZ);
  renderReplayFrame();
}

function resetReplay() {
  state.playing = false;
  state.lastFrameAt = 0;
  state.tickRemainder = 0;
  state.eventSeekTicks = [];
  replayToggle.textContent = "Play replay";
  replayToggle.disabled = true;
  replayTimeline.disabled = true;
  replaySpeed.disabled = true;
  ui.previousEvent.disabled = true;
  ui.nextEvent.disabled = true;
  ui.replayRestart.disabled = true;
  ui.cameraMode.disabled = true;
  if (state.renderer !== null) {
    state.renderer.dispose();
  }
  replayCanvas.replaceChildren();
  participantLegend.replaceChildren();
  eventPositions.replaceChildren();
  state.scene = null;
  state.camera = null;
  state.cameraFrame = null;
  state.conflictFrame = null;
  state.renderer = null;
  state.meshes.clear();
  state.frames.clear();
  state.playbackEvents = [];
  state.participantReadouts.clear();
  state.replayScene = null;
  state.tracks.clear();
  state.currentTimeS = 0;
  state.terminalTimeS = 0;
  state.followCameraState = null;
  state.currentEgoPose = null;
  state.freeCameraState = null;
  state.signalHeads.clear();
  roadLegend.replaceChildren();
  updateSimulationTime();
}

function replayProjectionInput(playback) {
  if (playback.schema_version !== "scenarioforge.p1-playback/v1") {
    return playback;
  }
  return {
    ...playback,
    schema_version: "scenarioforge.playback/v2",
    participants: playback.participants.map((participant) => ({
      ...participant,
      role: participant.role === "ego" ? "ego" : "social",
    })),
  };
}

function initializeReplay(playback) {
  resetReplay();
  try {
    state.replayScene = projectReplayScene(replayProjectionInput(playback));
  } catch (_error) {
    renderReplayFailure(
      replayCanvas,
      [replayToggle, replayTimeline, replaySpeed, ui.previousEvent, ui.nextEvent, ui.replayRestart, ui.cameraMode],
      "invalid_evidence",
    );
    playbackPanel.hidden = false;
    return;
  }
  state.scene = new THREE.Scene();
  state.scene.background = new THREE.Color(0x090d0c);
  state.camera = new THREE.PerspectiveCamera(50, 1, 0.1, 500);
  try {
    state.renderer = new THREE.WebGLRenderer({
      antialias: true,
      powerPreference: "high-performance",
      preserveDrawingBuffer: true,
    });
  } catch (_error) {
    state.renderer = null;
    renderReplayFailure(
      replayCanvas,
      [replayToggle, replayTimeline, replaySpeed, ui.previousEvent, ui.nextEvent, ui.replayRestart, ui.cameraMode],
      "webgl_initialization_failed",
    );
    playbackPanel.hidden = false;
    return;
  }
  state.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  replayCanvas.append(state.renderer.domElement);
  state.renderer.domElement.addEventListener("webglcontextlost", (event) => {
    event.preventDefault();
    state.playing = false;
    state.renderer?.dispose();
    state.renderer = null;
    renderReplayFailure(
      replayCanvas,
      [replayToggle, replayTimeline, replaySpeed, ui.previousEvent, ui.nextEvent, ui.replayRestart, ui.cameraMode],
      "webgl_context_lost",
    );
  });

  const ambient = new THREE.HemisphereLight(0xdfffee, 0x18231f, 2.3);
  const key = new THREE.DirectionalLight(0xffffff, 2.7);
  key.position.set(16, 30, 18);
  state.scene.add(ambient, key);

  state.terminalTick = playback.terminal_tick;
  state.sampleIntervalMs = playback.sample_interval_s * 1000;
  state.terminalTimeS = state.replayScene.timeline.endTimeS;
  indexTrajectory(playback.trajectory);
  indexReplayTracks(state.replayScene);
  state.cameraFrame = calculateReplayFrame(playback);
  state.conflictFrame = calculateConflictFrame(playback);
  state.playbackEvents = playback.events;
  state.scenarioOutcome = playback.scenario_outcome ?? playback.execution_status ?? "success";
  renderRoad(playback);
  renderParticipants(playback);
  renderKeyEvents(playback.events);
  replayTimeline.min = "0";
  replayTimeline.max = String(playback.terminal_tick);
  replayTimeline.step = "any";
  replayTimeline.dataset.timeUnit = "seconds";
  replayTimeline.disabled = false;
  replaySpeed.disabled = false;
  replayToggle.disabled = false;
  ui.previousEvent.disabled = false;
  ui.nextEvent.disabled = false;
  ui.replayRestart.disabled = false;
  ui.cameraMode.disabled = false;
  playbackPanel.hidden = false;
  ui.cameraMode.replaceChildren();
  const cameraModes = playback.camera?.available_modes
    ?? state.replayScene.camera.availableModes;
  cameraModes.forEach((mode) => {
    const option = document.createElement("option");
    option.value = mode;
    option.textContent = formatToken(mode);
    ui.cameraMode.append(option);
    if (mode === "conflict-focus") {
      const compatibilityOption = document.createElement("option");
      compatibilityOption.value = "conflict";
      compatibilityOption.textContent = "Conflict (compatibility alias)";
      ui.cameraMode.append(compatibilityOption);
    }
  });
  applyReplayDataset(replayCanvas, state.replayScene, {
    followErrorM: 0,
    lookDirectionErrorDeg: 0,
  });
  if (playback.schema_version === "scenarioforge.p1-playback/v1") {
    replayCanvas.dataset.evidenceBackend = "scenarioforge.smarts";
    replayCanvas.dataset.trafficRule = playback.traffic_rule;
  }
  applyCameraMode(playback.camera?.default_mode ?? state.replayScene.camera.defaultMode);
  setReplayTime(0);
}

async function loadPlayback(runId, runsEndpoint = ENDPOINTS.runs) {
  const playback = await requestJSON(scopedRunTrajectory(runId, runsEndpoint));
  initializeReplay(playback);
}

function toggleReplay() {
  if (state.currentTimeS >= state.terminalTimeS) {
    setReplayTime(0);
  }
  state.playing = !state.playing;
  state.lastFrameAt = 0;
  replayToggle.textContent = state.playing ? "Pause replay" : "Play replay";
}

function animateReplay(timestamp) {
  requestAnimationFrame(animateReplay);
  if (!state.playing || state.tracks.size === 0) {
    return;
  }
  if (state.lastFrameAt === 0) {
    state.lastFrameAt = timestamp;
    return;
  }
  const elapsed = Math.min(
    timestamp - state.lastFrameAt,
    MAX_REPLAY_FRAME_DELTA_MS,
  );
  state.lastFrameAt = timestamp;
  const nextTimeS = Math.min(
    state.terminalTimeS,
    state.currentTimeS + (elapsed / 1000) * state.speed,
  );
  setReplayTime(nextTimeS, elapsed);
  if (nextTimeS >= state.terminalTimeS) {
    state.playing = false;
    replayToggle.textContent = "Play replay";
  }
}

function showError(error) {
  const message = error instanceof Error ? error.message : "Unexpected application error";
  setApplicationStatus(message, "error");
}

async function resumeActiveRun(runId) {
  if (runId === null) {
    return;
  }
  try {
    await pollRun(runId);
  } catch (error) {
    sessionStorage.removeItem(ACTIVE_RUN_KEY);
    showError(error);
  }
}

async function bootstrap() {
  const activeRunId = sessionStorage.getItem(ACTIVE_RUN_KEY);
  try {
    await loadBootstrapSession();
    await Promise.all([
      loadCatalog(),
      loadP1Catalog(),
      loadAuthoringPresets(),
      loadAuthoringScenarios(),
    ]);
    renderAuthoringDiagnostics(null);
    setAuthoringControls();
    updateStudioControls();
    setApplicationStatus("Ready", "ready");
    await resumeActiveRun(activeRunId);
  } catch (error) {
    showError(error);
  }
}

buildProductExtensions();
studioSourceButtons.forEach((button) => {
  button.addEventListener("click", () => selectStudioSource(button.dataset.studioSource));
});
studioTemplateSelect.addEventListener("change", () => {
  selectStudioTemplate(studioTemplateSelect.value);
});
studioRun.addEventListener("click", startStudioRun);
p1ScenarioSelect.addEventListener("change", () => {
  selectP1Scenario(p1ScenarioSelect.value);
});
bindReplayCameraInputs(replayCanvas, (input) => {
  if (state.cameraMode !== "free" || state.freeCameraState === null) {
    return;
  }
  state.freeCameraState = applyP1CameraInput(state.freeCameraState, input);
  applyP1CameraState(state.freeCameraState);
});
authoringDraftSelect.addEventListener("change", authoringAction(
  () => loadAuthoringDraft(authoringDraftSelect.value),
));
authoringPreset.addEventListener("change", previewAuthoringPreset);
createDraftButton.addEventListener("click", authoringAction(createAuthoringDraft));
updateDraftButton.addEventListener("click", authoringAction(updateAuthoringDraft));
validateDraftButton.addEventListener("click", authoringAction(validateAuthoringDraft));
saveRevisionButton.addEventListener("click", authoringAction(saveImmutableRevision));
cloneDraftButton.addEventListener("click", authoringAction(cloneAuthoringDraft));
archiveDraftButton.addEventListener("click", authoringAction(archiveAuthoringDraft));
forkPresetButton.addEventListener("click", authoringAction(forkAuthoringPreset));
importDraftButton.addEventListener("click", authoringAction(importAuthoringDraft));
exportDraftButton.addEventListener("click", authoringAction(exportAuthoringDraft));
preflightRevisionButton.addEventListener("click", authoringAction(
  () => preflightAuthoringRevision(),
));
saveAndRunRevisionButton.addEventListener("click", authoringAction(
  saveAndRunAuthoringRevision,
));
runScenario.addEventListener("click", startRun);
runP1Scenario.addEventListener("click", startP1Run);
replayToggle.addEventListener("click", toggleReplay);
replayTimeline.addEventListener("input", (event) => {
  state.playing = false;
  replayToggle.textContent = "Play replay";
  const request = resolveTimelineInput(
    Number(replayTimeline.value),
    state.sampleIntervalMs / 1000,
    state.terminalTick,
    event.isTrusted,
  );
  if (request.unit === "seconds") {
    setReplayTime(request.value);
  } else {
    setReplayTick(request.value);
  }
});
replaySpeed.addEventListener("change", () => {
  state.speed = Number.parseFloat(replaySpeed.value);
});
window.addEventListener("resize", resizeRenderer);
requestAnimationFrame(animateReplay);
bootstrap();
