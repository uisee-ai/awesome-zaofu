const finite = (value) => typeof value === "number" && Number.isFinite(value);
const read = (value, snake, camel = snake) => value?.[snake] ?? value?.[camel];
const assert = (condition, message) => {
  if (!condition) {
    throw new TypeError(message);
  }
};
const clone = (value) => JSON.parse(JSON.stringify(value));

export const P1_CAMERA_MODES = Object.freeze(["follow", "overview", "fixed", "free"]);
const FOLLOW_ERROR_M_MAX = 2;
const VIEW_DIRECTION_ERROR_DEG_MAX = 5;

const ROLE_ALIASES = Object.freeze({
  ego: "ego",
  controlled: "controlled_agent",
  controlled_agent: "controlled_agent",
  other_controllable_agent: "controlled_agent",
  social: "social_vehicle",
  social_vehicle: "social_vehicle",
  pedestrian: "pedestrian",
  vulnerable_road_user: "pedestrian",
});

export const P1_PARTICIPANT_APPEARANCE = Object.freeze({
  ego: Object.freeze({color: "#32d6c5", shape: "vehicle", visualPattern: "solid"}),
  controlled_agent: Object.freeze({color: "#8ea7ff", shape: "vehicle", visualPattern: "striped"}),
  social_vehicle: Object.freeze({color: "#ffb454", shape: "vehicle", visualPattern: "outline"}),
  pedestrian: Object.freeze({color: "#f88bc4", shape: "pedestrian", visualPattern: "upright"}),
});

const safeId = (value) => (
  typeof value === "string" && /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(value)
);

const normalizedRole = (role) => {
  const normalized = ROLE_ALIASES[role];
  assert(normalized !== undefined, "participant role is invalid");
  return normalized;
};

export function buildParticipantLegend(participants, samples, events, tick) {
  assert(Array.isArray(participants) && participants.length > 0, "participants are invalid");
  assert(Array.isArray(samples) && Array.isArray(events), "participant samples are invalid");
  assert(Number.isInteger(tick) && tick >= 0, "legend tick is invalid");
  const normalized = participants.map((participant) => {
    const participantId = read(participant, "id", "participantId");
    assert(safeId(participantId), "participant id is invalid");
    return {participantId, role: normalizedRole(read(participant, "role"))};
  });
  assert(new Set(normalized.map((item) => item.participantId)).size === normalized.length, "participants are invalid");
  const samplesByParticipant = new Map(normalized.map((item) => [item.participantId, []]));
  const seenSamples = new Set();
  samples.forEach((sample) => {
    const participantId = read(sample, "participant_id", "participantId");
    const sampleTick = read(sample, "tick");
    const speedMps = Number(read(sample, "speed_mps", "speedMps"));
    const brake = Number(read(sample, "brake"));
    const key = `${participantId}:${sampleTick}`;
    assert(
      samplesByParticipant.has(participantId)
        && Number.isInteger(sampleTick)
        && sampleTick >= 0
        && finite(speedMps)
        && speedMps >= 0
        && finite(brake)
        && brake >= 0
        && brake <= 1
        && !seenSamples.has(key),
      "participant sample is invalid",
    );
    seenSamples.add(key);
    samplesByParticipant.get(participantId).push({tick: sampleTick, speedMps, brake});
  });
  samplesByParticipant.forEach((participantSamples) => participantSamples.sort((left, right) => left.tick - right.tick));
  const activeEvents = new Map(normalized.map((item) => [item.participantId, []]));
  const eventIds = new Set();
  events.forEach((event) => {
    const eventId = read(event, "event_id", "eventId");
    const participantId = read(event, "participant_id", "participantId");
    const triggerTick = read(event, "trigger_tick", "triggerTick");
    const durationTicks = read(event, "duration_ticks", "durationTicks") ?? 1;
    const explicitEnd = read(event, "end_tick", "endTick");
    const endTick = explicitEnd ?? triggerTick + durationTicks - 1;
    assert(
      safeId(eventId)
        && !eventIds.has(eventId)
        && activeEvents.has(participantId)
        && Number.isInteger(triggerTick)
        && Number.isInteger(durationTicks)
        && durationTicks >= 1
        && Number.isInteger(endTick)
        && endTick >= triggerTick,
      "participant event is invalid",
    );
    eventIds.add(eventId);
    if (triggerTick <= tick && tick <= endTick) {
      activeEvents.get(participantId).push(eventId);
    }
  });
  return normalized.map(({participantId, role}) => {
    const available = samplesByParticipant.get(participantId).filter((sample) => sample.tick <= tick);
    assert(available.length > 0, "participant sample is missing");
    const sample = available.at(-1);
    const brakeState = role === "pedestrian" ? "not-applicable" : sample.brake > 0 ? "braking" : "coasting";
    const keyEventState = activeEvents.get(participantId).join(", ") || "none";
    const eventLabel = keyEventState === "none" ? "no key event" : `event ${keyEventState}`;
    const brakeLabel = brakeState === "not-applicable" ? "brake not applicable" : brakeState;
    return {
      participantId,
      role,
      ...P1_PARTICIPANT_APPEARANCE[role],
      speedMps: sample.speedMps,
      brakeState,
      keyEventState,
      accessibleLabel: `${participantId} · ${role.replaceAll("_", " ")} · ${sample.speedMps} m/s · ${brakeLabel} · ${eventLabel}`,
    };
  });
}

const pair = (value, message) => {
  assert(Array.isArray(value) && value.length === 2 && value.every(finite), message);
  return value.map(Number);
};

const vector = (value, message) => {
  assert(Array.isArray(value) && value.length === 3 && value.every(finite), message);
  return value.map(Number);
};

const targetProjection = (targetPose) => {
  const position = pair(read(targetPose, "position_m", "positionM"), "camera target is invalid");
  const headingDeg = Number(read(targetPose, "heading_deg", "headingDeg"));
  assert(finite(headingDeg), "camera target is invalid");
  return {target: [position[0], 0, -position[1]], headingDeg};
};

const boundsProjection = (bounds) => {
  const center = pair(read(bounds, "center_m", "centerM"), "camera bounds are invalid");
  const halfExtents = pair(read(bounds, "half_extents_m", "halfExtentsM"), "camera bounds are invalid");
  assert(halfExtents.every((value) => value > 0), "camera bounds are invalid");
  return {center: [center[0], 0, -center[1]], halfExtents};
};

const cameraState = (mode, position, lookAt) => {
  const projectedPosition = vector(position, "camera state is invalid");
  const projectedLookAt = vector(lookAt, "camera state is invalid");
  const offset = projectedPosition.map((value, index) => value - projectedLookAt[index]);
  const distanceM = Math.hypot(...offset);
  assert(distanceM > 0, "camera state is invalid");
  return {
    schemaVersion: "scenarioforge.replay-camera-state/v1",
    mode,
    position: projectedPosition,
    lookAt: projectedLookAt,
    yawDeg: Math.atan2(offset[0], offset[2]) * 180 / Math.PI,
    pitchDeg: Math.asin(Math.max(-1, Math.min(1, offset[1] / distanceM))) * 180 / Math.PI,
    distanceM,
    initialized: true,
  };
};

const orbitalState = (mode, lookAt, yawDeg, pitchDeg, distanceM) => {
  assert([yawDeg, pitchDeg, distanceM].every(finite) && distanceM > 0, "camera input is invalid");
  const pitch = Math.min(85, Math.max(-20, pitchDeg));
  const distance = Math.min(500, Math.max(2, distanceM));
  const yawRad = yawDeg * Math.PI / 180;
  const pitchRad = pitch * Math.PI / 180;
  const horizontal = Math.cos(pitchRad) * distance;
  return cameraState(mode, [
    lookAt[0] + Math.sin(yawRad) * horizontal,
    lookAt[1] + Math.sin(pitchRad) * distance,
    lookAt[2] + Math.cos(yawRad) * horizontal,
  ], lookAt);
};

const normalizedMode = (mode) => mode === "ego-follow" ? "follow" : mode;

export function createCameraState(mode, {targetPose, bounds}) {
  const selectedMode = normalizedMode(mode);
  assert(P1_CAMERA_MODES.includes(selectedMode), "camera mode is invalid");
  const {target, headingDeg} = targetProjection(targetPose);
  const {center, halfExtents} = boundsProjection(bounds);
  if (selectedMode === "follow") {
    const headingRad = headingDeg * Math.PI / 180;
    const forward = [Math.cos(headingRad), 0, -Math.sin(headingRad)];
    return cameraState(selectedMode, [
      target[0] - forward[0] * 8,
      4,
      target[2] - forward[2] * 8,
    ], [
      target[0] + forward[0] * 12,
      0,
      target[2] + forward[2] * 12,
    ]);
  }
  const extent = Math.max(...halfExtents);
  if (selectedMode === "overview") {
    return orbitalState(selectedMode, center, 0, 58, Math.max(24, extent * 1.8));
  }
  if (selectedMode === "fixed") {
    return cameraState(selectedMode, [-16, 14, 18], center);
  }
  return orbitalState(selectedMode, center, 25, 32, Math.max(20, extent * 1.2));
}

const validatedState = (state) => {
  assert(
    state?.schemaVersion === "scenarioforge.replay-camera-state/v1"
      && P1_CAMERA_MODES.includes(state.mode)
      && state.initialized === true
      && [state.yawDeg, state.pitchDeg, state.distanceM].every(finite),
    "camera state is invalid",
  );
  vector(state.position, "camera state is invalid");
  vector(state.lookAt, "camera state is invalid");
  return state;
};

export function switchCameraMode(state, mode, context) {
  validatedState(state);
  return createCameraState(mode, context);
}

export function applyCameraInput(state, cameraInput) {
  const current = validatedState(state);
  assert(typeof cameraInput?.kind === "string", "camera input is invalid");
  if (cameraInput.trusted !== true || current.mode !== "free") {
    return clone(current);
  }
  let yaw = current.yawDeg;
  let pitch = current.pitchDeg;
  let distance = current.distanceM;
  const lookAt = [...current.lookAt];
  if (cameraInput.kind === "pointer") {
    const deltaX = Number(read(cameraInput, "delta_x", "deltaX"));
    const deltaY = Number(read(cameraInput, "delta_y", "deltaY"));
    assert([deltaX, deltaY].every(finite) && ["rotate", "pan"].includes(cameraInput.action), "camera input is invalid");
    if (cameraInput.action === "rotate") {
      yaw -= deltaX * 0.25;
      pitch += deltaY * 0.25;
    } else {
      const scale = Math.max(0.01, distance * 0.0025);
      const yawRad = yaw * Math.PI / 180;
      lookAt[0] -= Math.cos(yawRad) * deltaX * scale;
      lookAt[2] += Math.sin(yawRad) * deltaX * scale;
      lookAt[1] += deltaY * scale;
    }
  } else if (cameraInput.kind === "wheel") {
    const deltaY = Number(read(cameraInput, "delta_y", "deltaY"));
    assert(finite(deltaY), "camera input is invalid");
    distance *= Math.exp(deltaY * 0.001);
  } else if (cameraInput.kind === "keyboard") {
    const {key} = cameraInput;
    assert(typeof key === "string", "camera input is invalid");
    const step = Math.max(0.5, distance * 0.04);
    const yawRad = yaw * Math.PI / 180;
    if (["w", "W", "s", "S"].includes(key)) {
      const sign = key.toLowerCase() === "w" ? 1 : -1;
      lookAt[0] -= Math.sin(yawRad) * step * sign;
      lookAt[2] -= Math.cos(yawRad) * step * sign;
    } else if (["a", "A", "d", "D"].includes(key)) {
      const sign = key.toLowerCase() === "a" ? -1 : 1;
      lookAt[0] += Math.cos(yawRad) * step * sign;
      lookAt[2] -= Math.sin(yawRad) * step * sign;
    } else if (["q", "Q", "e", "E"].includes(key)) {
      lookAt[1] += step * (key.toLowerCase() === "e" ? 1 : -1);
    } else if (key === "ArrowLeft") {
      yaw += 4;
    } else if (key === "ArrowRight") {
      yaw -= 4;
    } else if (key === "ArrowUp") {
      pitch += 4;
    } else if (key === "ArrowDown") {
      pitch -= 4;
    } else {
      return clone(current);
    }
  } else {
    throw new TypeError("camera input is invalid");
  }
  return orbitalState("free", lookAt, yaw, pitch, distance);
}

const angleBetweenDeg = (left, right) => {
  const leftLength = Math.hypot(...left);
  const rightLength = Math.hypot(...right);
  assert(leftLength > 0 && rightLength > 0, "follow camera state is invalid");
  const cosine = left.reduce(
    (total, value, index) => total + value * right[index],
    0,
  ) / (leftLength * rightLength);
  return Math.acos(Math.max(-1, Math.min(1, cosine))) * 180 / Math.PI;
};

export function followCameraQuality(state) {
  const cameraPosition = vector(state?.cameraPosition, "follow camera state is invalid");
  const lookAt = vector(state?.lookAt, "follow camera state is invalid");
  const desiredPosition = vector(state?.desiredPosition, "follow camera state is invalid");
  const desiredLookAt = vector(state?.desiredLookAt, "follow camera state is invalid");
  const followErrorM = Math.hypot(
    ...cameraPosition.map((value, index) => value - desiredPosition[index]),
  );
  const currentDirection = lookAt.map((value, index) => value - cameraPosition[index]);
  const desiredDirection = desiredLookAt.map((value, index) => value - desiredPosition[index]);
  const viewDirectionErrorDeg = angleBetweenDeg(currentDirection, desiredDirection);
  const normalizedFollowError = followErrorM < 1e-9 ? 0 : followErrorM;
  const normalizedViewError = viewDirectionErrorDeg < 1e-5 ? 0 : viewDirectionErrorDeg;
  return {
    followErrorM: Number(normalizedFollowError.toFixed(6)),
    viewDirectionErrorDeg: Number(normalizedViewError.toFixed(6)),
    withinTolerance: (
      normalizedFollowError <= FOLLOW_ERROR_M_MAX
      && normalizedViewError <= VIEW_DIRECTION_ERROR_DEG_MAX
    ),
  };
}

const headingDeltaDeg = (start, end) => ((end - start + 180) % 360 + 360) % 360 - 180;

const projectedSignals = (value) => {
  assert(Array.isArray(value) && value.length <= 64, "trajectory signals are invalid");
  const seen = new Set();
  return value.map((signal) => {
    const signalId = read(signal, "signal_id", "signalId");
    const state = read(signal, "state");
    assert(
      safeId(signalId)
        && !seen.has(signalId)
        && ["red", "yellow", "green", "off", "unknown"].includes(state),
      "trajectory signal is invalid",
    );
    seen.add(signalId);
    return {signalId, state};
  });
};

const projectedTrack = (track) => {
  const participantId = read(track, "participant_id", "participantId");
  const role = normalizedRole(read(track, "role"));
  const sourceSamples = read(track, "samples");
  assert(safeId(participantId) && Array.isArray(sourceSamples) && sourceSamples.length > 0, "replay track is invalid");
  const samples = sourceSamples.map((sample) => {
    const tick = read(sample, "tick");
    const positionM = pair(read(sample, "position_m", "positionM"), "trajectory sample is invalid");
    const headingDeg = Number(read(sample, "heading_deg", "headingDeg"));
    const speedMps = Number(read(sample, "speed_mps", "speedMps"));
    const brake = Number(read(sample, "brake"));
    assert(
      Number.isInteger(tick)
        && tick >= 0
        && finite(headingDeg)
        && finite(speedMps)
        && speedMps >= 0
        && finite(brake)
        && brake >= 0
        && brake <= 1,
      "trajectory sample is invalid",
    );
    return {
      tick,
      positionM,
      headingDeg,
      speedMps,
      brake,
      signals: projectedSignals(read(sample, "signals")),
      headingTangentErrorDeg: null,
    };
  });
  assert(
    samples.every((sample, index) => index === 0 || sample.tick > samples[index - 1].tick),
    "trajectory sample order is invalid",
  );
  if (samples.length > 1) {
    samples.forEach((sample, index) => {
      const adjacent = index < samples.length - 1 ? samples[index + 1] : samples[index - 1];
      const start = index < samples.length - 1 ? sample.positionM : adjacent.positionM;
      const end = index < samples.length - 1 ? adjacent.positionM : sample.positionM;
      const deltaX = end[0] - start[0];
      const deltaY = end[1] - start[1];
      if (Math.hypot(deltaX, deltaY) < 0.25) return;
      const tangentDeg = Math.atan2(deltaY, deltaX) * 180 / Math.PI;
      const error = Math.abs(headingDeltaDeg(tangentDeg, sample.headingDeg));
      assert(error <= 10 + 1e-9, "trajectory heading differs from recorded motion by more than 10 degrees");
      sample.headingTangentErrorDeg = error < 1e-9 ? 0 : error;
    });
  }
  return {participantId, role, samples};
};

export function createP1ReplayViewModel(scene, tick = 0) {
  assert(
    read(scene, "schema_version", "schemaVersion") === "scenarioforge.replay-scene/v1"
      && Number.isInteger(tick)
      && tick >= 0,
    "P1 replay scene is invalid",
  );
  const p1 = read(scene, "p1_replay", "p1Replay");
  assert(read(p1, "schema_version", "schemaVersion") === "scenarioforge.p1-replay/v1", "P1 replay scene is invalid");
  const tracks = read(scene, "tracks").map(projectedTrack);
  assert(new Set(tracks.map((track) => track.participantId)).size === tracks.length, "replay tracks are invalid");
  const cameraModes = read(read(scene, "camera"), "available_modes", "availableModes");
  assert(
    Array.isArray(cameraModes)
      && cameraModes.length === P1_CAMERA_MODES.length
      && cameraModes.every((mode, index) => mode === P1_CAMERA_MODES[index]),
    "P1 camera contract is invalid",
  );
  const events = read(scene, "events");
  assert(Array.isArray(events), "P1 replay events are invalid");
  const participants = tracks.map((track) => ({id: track.participantId, role: track.role}));
  const legendSamples = tracks.flatMap((track) => track.samples.map((sample) => ({
    tick: sample.tick,
    participantId: track.participantId,
    speedMps: sample.speedMps,
    brake: sample.brake,
  })));
  const roadLegend = read(p1, "road_legend", "roadLegend");
  const sourceSignalLegend = read(p1, "signal_legend", "signalLegend");
  assert(
    Array.isArray(roadLegend)
      && roadLegend.every((item) => typeof item === "string" && item.length > 0)
      && Array.isArray(sourceSignalLegend),
    "P1 replay legend is invalid",
  );
  const signalLegend = sourceSignalLegend.map((signal) => {
    const signalId = read(signal, "signal_id", "signalId");
    const state = read(signal, "state");
    const accessibleLabel = read(signal, "accessible_label", "accessibleLabel");
    assert(safeId(signalId) && typeof state === "string" && typeof accessibleLabel === "string", "P1 signal legend is invalid");
    return {signalId, state, accessibleLabel};
  });
  return {
    schemaVersion: "scenarioforge.p1-replay-view/v1",
    cameraModes: [...cameraModes],
    tracks,
    participantLegend: buildParticipantLegend(participants, legendSamples, events, tick),
    roadLegend: [...roadLegend],
    signalLegend,
    events: clone(events),
  };
}

export function bindReplayCameraInputs(element, onInput) {
  assert(element?.addEventListener instanceof Function && onInput instanceof Function, "camera binding is invalid");
  let pointerId = null;
  let pointerAction = "rotate";
  element.tabIndex = element.tabIndex < 0 ? 0 : element.tabIndex;
  const pointerdown = (event) => {
    pointerId = event.pointerId;
    pointerAction = event.button === 2 || event.shiftKey ? "pan" : "rotate";
    element.setPointerCapture?.(pointerId);
    element.focus?.();
  };
  const pointermove = (event) => {
    if (event.pointerId !== pointerId || event.buttons === 0) return;
    onInput({kind: "pointer", action: pointerAction, deltaX: event.movementX, deltaY: event.movementY, trusted: event.isTrusted});
  };
  const pointerup = (event) => {
    if (event.pointerId === pointerId) pointerId = null;
  };
  const keydown = (event) => {
    onInput({kind: "keyboard", key: event.key, trusted: event.isTrusted});
  };
  const wheel = (event) => {
    event.preventDefault();
    onInput({kind: "wheel", deltaY: event.deltaY, trusted: event.isTrusted});
  };
  element.addEventListener("pointerdown", pointerdown);
  element.addEventListener("pointermove", pointermove);
  element.addEventListener("pointerup", pointerup);
  element.addEventListener("keydown", keydown);
  element.addEventListener("wheel", wheel, {passive: false});
  return () => {
    element.removeEventListener("pointerdown", pointerdown);
    element.removeEventListener("pointermove", pointermove);
    element.removeEventListener("pointerup", pointerup);
    element.removeEventListener("keydown", keydown);
    element.removeEventListener("wheel", wheel);
  };
}
