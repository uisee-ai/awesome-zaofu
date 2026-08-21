const deepFreeze = (value) => {
  if (value !== null && typeof value === "object" && !Object.isFrozen(value)) {
    Object.freeze(value);
    Object.values(value).forEach(deepFreeze);
  }
  return value;
};

export const VISUAL_REPLAY_TOLERANCE_V1 = deepFreeze({
  schemaVersion: "scenarioforge.visual-replay-tolerance/v1",
  followCamera: {
    rearOffsetM: 8,
    heightOffsetM: 4,
    lookAheadM: 12,
    dampingHalfLifeMs: 150,
    settleTimeS: 0.5,
    maxFollowErrorM: 2,
    maxLookDirectionErrorDeg: 5,
  },
  pose: {
    minimumTangentDisplacementMPerTick: 0.25,
    maxHeadingTangentErrorDeg: 10,
    headingInterpolation: "shortest-wrapped-arc",
    localForwardAxis: "+x",
  },
  performance: {maxFrameTimeP95Ms: 33},
});

const read = (value, snake, camel = snake) => value?.[snake] ?? value?.[camel];
const finite = (value) => typeof value === "number" && Number.isFinite(value);
const safeId = (value) => (
  typeof value === "string" && /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(value)
);

const assert = (condition, message) => {
  if (!condition) {
    throw new TypeError(message);
  }
};

export function normalizeHeadingDeg(value) {
  assert(finite(value), "heading is invalid");
  const normalized = ((value + 180) % 360 + 360) % 360 - 180;
  return Object.is(normalized, -0) ? 0 : normalized;
}

export function shortestHeadingDeltaDeg(start, end) {
  assert(finite(start) && finite(end), "heading is invalid");
  return normalizeHeadingDeg(end - start);
}

export function timelineTickForTime(timeS, sampleIntervalS, terminalTick) {
  assert(
    finite(timeS)
      && finite(sampleIntervalS)
      && sampleIntervalS > 0
      && Number.isInteger(terminalTick)
      && terminalTick >= 0,
    "timeline position is invalid",
  );
  return Math.min(terminalTick, Math.max(0, timeS / sampleIntervalS));
}

export function resolveTimelineInput(value, sampleIntervalS, terminalTick, isTrusted) {
  assert(
    finite(value)
      && finite(sampleIntervalS)
      && sampleIntervalS > 0
      && Number.isInteger(terminalTick)
      && terminalTick >= 0,
    "timeline input is invalid",
  );
  const clamped = Math.min(terminalTick, Math.max(0, value));
  if (!isTrusted && clamped > 0 && clamped < sampleIntervalS) {
    return {unit: "seconds", value: clamped};
  }
  return {unit: "ticks", value: clamped};
}

const pointPosition = (sample) => {
  const position = read(sample, "position_m", "positionM");
  assert(
    Array.isArray(position) && position.length === 2 && position.every(finite),
    "trajectory sample is invalid",
  );
  return [Number(position[0]), Number(position[1])];
};

const sampleTime = (sample) => read(sample, "simulation_time_s", "simulationTimeS");
const sampleTick = (sample) => Number(read(sample, "tick"));
const sampleHeading = (sample) => Number(read(sample, "heading_deg", "headingDeg"));
const sampleSpeed = (sample) => Number(read(sample, "speed_mps", "speedMps"));

const tangentForPair = (lower, upper) => {
  const [lowerX, lowerY] = pointPosition(lower);
  const [upperX, upperY] = pointPosition(upper);
  if (Math.hypot(upperX - lowerX, upperY - lowerY) < 1e-12) {
    return null;
  }
  return normalizeHeadingDeg(Math.atan2(upperY - lowerY, upperX - lowerX) * 180 / Math.PI);
};

export function interpolatePose(samples, requestedTimeS) {
  assert(Array.isArray(samples) && samples.length > 0 && finite(requestedTimeS), "interpolation input is invalid");
  const times = samples.map(sampleTime);
  assert(times.every(finite), "trajectory sample is invalid");
  assert(times.every((time, index) => index === 0 || time > times[index - 1]), "trajectory sample time is invalid");
  const simulationTimeS = Math.min(Math.max(requestedTimeS, times[0]), times.at(-1));
  let upperIndex = times.findIndex((time) => time >= simulationTimeS);
  if (upperIndex < 0) {
    upperIndex = samples.length - 1;
  }
  let lowerIndex = upperIndex;
  let alpha = 0;
  if (times[upperIndex] !== simulationTimeS && upperIndex > 0) {
    lowerIndex = upperIndex - 1;
    alpha = (simulationTimeS - times[lowerIndex]) / (times[upperIndex] - times[lowerIndex]);
  }
  const lower = samples[lowerIndex];
  const upper = samples[upperIndex];
  const lowerPosition = pointPosition(lower);
  const upperPosition = pointPosition(upper);
  const positionM = lowerPosition.map((value, axis) => value + (upperPosition[axis] - value) * alpha);
  const lowerHeading = sampleHeading(lower);
  const headingDeg = normalizeHeadingDeg(
    lowerHeading + shortestHeadingDeltaDeg(lowerHeading, sampleHeading(upper)) * alpha,
  );
  const speedMps = sampleSpeed(lower) + (sampleSpeed(upper) - sampleSpeed(lower)) * alpha;
  let tangentDeg = null;
  if (lowerIndex !== upperIndex) {
    tangentDeg = tangentForPair(lower, upper);
  } else if (samples.length > 1 && lowerIndex === samples.length - 1) {
    tangentDeg = tangentForPair(samples[lowerIndex - 1], lower);
  } else if (samples.length > 1) {
    tangentDeg = tangentForPair(lower, samples[lowerIndex + 1]);
  }
  const headingRad = headingDeg * Math.PI / 180;
  return {
    simulationTimeS,
    lowerTick: sampleTick(lower),
    upperTick: sampleTick(upper),
    alpha,
    positionM,
    renderPositionM: [positionM[0], 0, -positionM[1]],
    headingDeg,
    renderYawRad: headingRad,
    speedMps,
    collision: Boolean(read(lower, "collision")),
    localForward: [Math.cos(headingRad), Math.sin(headingRad)],
    trajectoryTangentDeg: tangentDeg,
    headingTangentErrorDeg: tangentDeg === null ? null : Math.abs(shortestHeadingDeltaDeg(tangentDeg, headingDeg)),
    sourceClassification: "display-derived",
    sourceTicks: [sampleTick(lower), sampleTick(upper)],
  };
}

const smoothVector = (previous, desired, alpha) => desired.map((value, index) => (
  previous[index] + (value - previous[index]) * alpha
));

export function createFollowCameraState(pose, previousState = null, elapsedMs = 0) {
  assert(pose !== null && typeof pose === "object", "ego pose is invalid");
  const position = read(pose, "position_m", "positionM");
  const headingDeg = Number(read(pose, "heading_deg", "headingDeg"));
  assert(Array.isArray(position) && position.length === 2 && position.every(finite) && finite(headingDeg), "ego pose is invalid");
  assert(finite(elapsedMs) && elapsedMs >= 0, "camera elapsed time is invalid");
  const headingRad = headingDeg * Math.PI / 180;
  const forward = [Math.cos(headingRad), Math.sin(headingRad)];
  const tolerance = VISUAL_REPLAY_TOLERANCE_V1.followCamera;
  const desiredPosition = [
    position[0] - forward[0] * tolerance.rearOffsetM,
    tolerance.heightOffsetM,
    -(position[1] - forward[1] * tolerance.rearOffsetM),
  ];
  const desiredLookAt = [
    position[0] + forward[0] * tolerance.lookAheadM,
    0,
    -(position[1] + forward[1] * tolerance.lookAheadM),
  ];
  const alpha = previousState === null
    ? 1
    : 1 - Math.exp(-Math.LN2 * elapsedMs / tolerance.dampingHalfLifeMs);
  const cameraPosition = previousState === null
    ? desiredPosition
    : smoothVector(previousState.cameraPosition, desiredPosition, alpha);
  const lookAt = previousState === null
    ? desiredLookAt
    : smoothVector(previousState.lookAt, desiredLookAt, alpha);
  return {
    schemaVersion: "scenarioforge.follow-camera-state/v1",
    mode: "ego-follow",
    cameraPosition,
    lookAt,
    desiredPosition,
    desiredLookAt,
    dampingAlpha: alpha,
    stableHorizon: [0, 1, 0],
    sourceClassification: "display-derived",
  };
}

const projectedSample = (point, interval) => {
  const tick = Number(read(point, "tick"));
  const positionM = pointPosition(point);
  const recordedHeadingDeg = Number(read(point, "heading_deg", "headingDeg"));
  const headingDeg = normalizeHeadingDeg(recordedHeadingDeg);
  const speedMps = Number(read(point, "speed_mps", "speedMps"));
  assert(Number.isInteger(tick) && tick >= 0 && finite(speedMps) && speedMps >= 0, "trajectory sample is invalid");
  return {
    sourceSchemaVersion: read(point, "schema_version", "schemaVersion"),
    tick,
    simulationTimeS: tick * interval,
    positionM,
    renderPositionM: [positionM[0], 0, -positionM[1]],
    headingDeg,
    recordedHeadingDeg,
    renderYawRad: headingDeg * Math.PI / 180,
    speedMps,
    collision: Boolean(read(point, "collision")),
  };
};

const eventProjection = (event, interval, terminalTick, tracks) => {
  const eventId = read(event, "event_id", "eventId");
  const participantId = read(event, "participant_id", "participantId");
  const triggerTick = Number(read(event, "trigger_tick", "triggerTick"));
  const effectStateTick = Number(read(event, "effect_state_tick", "effectStateTick"));
  const durationTicks = Number(read(event, "duration_ticks", "durationTicks") ?? 1);
  const action = read(event, "action") ?? null;
  assert(safeId(eventId) && tracks.has(participantId), "event is invalid");
  assert(Number.isInteger(triggerTick) && Number.isInteger(effectStateTick) && Number.isInteger(durationTicks), "event is invalid");
  const endTick = Math.min(terminalTick, Math.max(effectStateTick, triggerTick + durationTicks - 1));
  const braking = action !== null && Number(read(action, "throttle_brake", "throttleBrake")) < 0;
  const speeds = tracks.get(participantId).samples
    .filter((sample) => sample.tick >= triggerTick && sample.tick <= endTick)
    .map((sample) => sample.speedMps);
  const verifiedDeceleration = braking && speeds.some((speed, index) => index > 0 && speed < speeds[index - 1] - 1e-6);
  return {
    eventId,
    participantId,
    triggerTick,
    effectStateTick,
    endTick,
    startTimeS: triggerTick * interval,
    effectTimeS: effectStateTick * interval,
    endTimeS: endTick * interval,
    action: action === null ? null : {
      steering: Number(read(action, "steering")),
      throttleBrake: Number(read(action, "throttle_brake", "throttleBrake")),
    },
    braking,
    verifiedDeceleration,
    sourceClassification: "recorded-evidence",
    sourceRefs: ["$.events", "$.trajectory"],
  };
};

export function projectReplayScene(playback) {
  assert(playback !== null && typeof playback === "object", "playback projection is invalid");
  const schemaVersion = read(playback, "schema_version", "schemaVersion");
  assert(["scenarioforge.playback/v1", "scenarioforge.playback/v2"].includes(schemaVersion), "playback schema is invalid");
  const participants = read(playback, "participants");
  const trajectory = read(playback, "trajectory");
  const events = read(playback, "events");
  const interval = Number(read(playback, "sample_interval_s", "sampleIntervalS"));
  const terminalTick = Number(read(playback, "terminal_tick", "terminalTick"));
  assert(Array.isArray(participants) && participants.length > 0 && participants.length <= 64, "participants are invalid");
  assert(Array.isArray(trajectory) && trajectory.length > 0 && trajectory.length <= 500000, "trajectory is invalid");
  assert(Array.isArray(events) && finite(interval) && interval > 0 && Number.isInteger(terminalTick) && terminalTick >= 0, "timeline is invalid");
  const projectedParticipants = participants.map((participant) => ({
    participantId: read(participant, "id"),
    role: read(participant, "role"),
  }));
  assert(projectedParticipants.every((participant) => safeId(participant.participantId) && ["ego", "social"].includes(participant.role)), "participants are invalid");
  const egos = projectedParticipants.filter((participant) => participant.role === "ego");
  assert(egos.length === 1, "unique ego participant is required");
  const tracks = new Map(projectedParticipants.map((participant) => [participant.participantId, {
    ...participant,
    sourceClassification: "recorded-evidence",
    samples: [],
  }]));
  trajectory.forEach((point) => {
    const participantId = read(point, "participant_id", "participantId");
    assert(tracks.has(participantId), "trajectory sample is invalid");
    tracks.get(participantId).samples.push(projectedSample(point, interval));
  });
  tracks.forEach((track) => {
    assert(track.samples.length > 0, "trajectory sample order is invalid");
    assert(
      track.samples.every((sample, index) => (
        sample.tick <= terminalTick
          && (index === 0 || sample.tick > track.samples[index - 1].tick)
      )),
      "trajectory sample order is invalid",
    );
  });
  const projectedEvents = events.map((event) => eventProjection(event, interval, terminalTick, tracks));
  const road = read(playback, "road");
  assert(road !== null && typeof road === "object", "road projection is invalid");
  const geometry = read(road, "geometry");
  const conflictZones = read(geometry, "conflict_zones", "conflictZones") ?? [];
  const trajectoryDigest = read(playback, "trajectory_digest", "trajectoryDigest");
  assert(typeof trajectoryDigest === "string" && /^[0-9a-f]{64}$/.test(trajectoryDigest) && !/^0+$/.test(trajectoryDigest), "trajectory digest is invalid");
  const hasBraking = projectedEvents.some((event) => event.braking && event.verifiedDeceleration);
  const semantic = (elementId, label, meaning, status, sourceClassification, sourceRefs) => ({
    elementId,
    label,
    meaning,
    status,
    sourceClassification: status === "applicable" ? sourceClassification : "not-declared",
    sourceRefs: status === "applicable" ? sourceRefs : [],
  });
  return {
    schemaVersion: "scenarioforge.replay-scene/v1",
    sourceBinding: {
      classification: "recorded-evidence",
      playbackSchemaVersion: schemaVersion,
      scenarioId: read(playback, "scenario_id", "scenarioId"),
      runId: read(playback, "run_id", "runId"),
      attemptId: read(playback, "attempt_id", "attemptId"),
      logicalRef: read(playback, "logical_ref", "logicalRef"),
      trajectoryDigest,
    },
    coordinateContract: {
      schemaVersion: "scenarioforge.replay-coordinate/v1",
      evidenceCoordinateSystem: "right-handed-x-forward-y-left",
      rendererCoordinateSystem: "right-handed-x-forward-y-up",
      evidencePositionAxes: ["x-forward", "y-left"],
      rendererPositionMapping: ["x", "elevation", "-y"],
      headingUnit: "deg",
      headingRotationAxis: "+y",
      headingRotationSign: 1,
      localForwardAxis: "+x",
      stableHorizonAxis: "+y",
    },
    visualTolerance: VISUAL_REPLAY_TOLERANCE_V1,
    camera: {
      schemaVersion: "scenarioforge.replay-camera/v1",
      defaultMode: "ego-follow",
      availableModes: ["ego-follow", "overview", ...(conflictZones.length ? ["conflict-focus"] : [])],
      egoParticipantId: egos[0].participantId,
      ...VISUAL_REPLAY_TOLERANCE_V1.followCamera,
      stableHorizonAxis: "+y",
      sourceClassification: "display-derived",
      sourceRefs: ["$.participants", "$.trajectory"],
    },
    visualContext: {
      schemaVersion: "scenarioforge.visual-context-profile/v1",
      sourceTrajectoryDigest: trajectoryDigest,
      elements: [
        semantic("road-surface", "Road surface", "Verified drivable lane geometry", "applicable", "recorded-evidence", ["$.road.geometry"]),
        semantic("lane-boundaries", "Lane boundaries", "Verified left and right lane limits", "applicable", "recorded-evidence", ["$.road.geometry"]),
        semantic("lane-centrelines", "Lane centre lines", "Verified lane centre geometry", "applicable", "recorded-evidence", ["$.road.geometry"]),
        semantic("conflict-zones", "Conflict zones", "Verified shared road regions where participant paths conflict", conflictZones.length ? "applicable" : "not-applicable", "recorded-evidence", ["$.road.geometry.conflict_zones"]),
        semantic("vehicles", "Vehicles", "Recorded participants at evidence-bound poses", "applicable", "recorded-evidence", ["$.participants", "$.trajectory"]),
        semantic("brake-lights", "Brake lights", "Display state derived from a verified braking event and speed profile", hasBraking ? "applicable" : "not-applicable", "display-derived", ["$.events", "$.trajectory"]),
        semantic("traffic-signals", "Traffic signals", "Signal state declared by immutable scenario or backend evidence", "not-applicable", "recorded-evidence", []),
        semantic("curbs-and-pedestrian-areas", "Curbs and pedestrian areas", "Declared roadside and pedestrian-only geometry", "not-applicable", "recorded-evidence", []),
        semantic("pedestrians", "Pedestrians", "Recorded pedestrian participants", "not-applicable", "recorded-evidence", []),
        semantic("obstacles", "Obstacles", "Recorded static or dynamic obstacles", "not-applicable", "recorded-evidence", []),
      ],
    },
    timeline: {
      schemaVersion: "scenarioforge.replay-timeline/v1",
      sampleIntervalS: interval,
      startTimeS: 0,
      endTimeS: terminalTick * interval,
      terminalTick,
      controls: {playPause: true, speeds: [0.25, 0.5, 1, 2, 4], seek: true, eventNavigation: true},
    },
    tracks: [...tracks.values()],
    events: projectedEvents,
  };
}

export function replayAvailability(terminal) {
  assert(terminal !== null && typeof terminal === "object", "terminal projection is invalid");
  const playable = read(terminal, "playable");
  assert(playable === undefined || typeof playable === "boolean", "terminal projection is invalid");
  const status = read(terminal, "execution_status", "executionStatus") ?? read(terminal, "status") ?? read(terminal, "state");
  const base = (state, accessibleMessage, controlsEnabled = false, requestPlayback = false) => ({
    schemaVersion: "scenarioforge.replay-availability/v1",
    state,
    accessibleMessage,
    controlsEnabled,
    requestPlayback,
  });
  if (status === "cancelled") {
    return base("cancelled", "Cancelled runs do not have a replay.");
  }
  if (read(terminal, "terminal") !== true) {
    return base("incomplete", "Replay is available after verified completion.");
  }
  if (playable === true && ["completed", "success"].includes(status)) {
    return base("ready", "Verified replay is ready.", true, true);
  }
  if (playable === false) {
    return base("unavailable", "No fully verified trajectory is available.");
  }
  throw new TypeError("terminal projection is invalid");
}

export function renderReplayFailure(container, controls, reason) {
  const messages = {
    webgl_initialization_failed: "3D replay is unavailable because WebGL could not be initialized.",
    webgl_context_lost: "3D replay is unavailable because the WebGL context was lost.",
    invalid_evidence: "3D replay is unavailable because the evidence is invalid.",
    empty_evidence: "No fully verified trajectory is available.",
  };
  assert(container instanceof Element && Array.isArray(controls) && Object.hasOwn(messages, reason), "rendering failure input is invalid");
  controls.forEach((control) => {
    control.disabled = true;
  });
  const status = document.createElement("p");
  status.className = "replay-failure-state";
  status.setAttribute("role", "status");
  status.setAttribute("aria-live", "polite");
  status.textContent = messages[reason];
  container.replaceChildren(status);
  container.dataset.renderState = "failed";
  container.dataset.failureReason = reason;
  return status;
}

export function applyReplayDataset(container, scene, metrics = {}) {
  assert(container instanceof Element && scene?.schemaVersion === "scenarioforge.replay-scene/v1", "replay dataset input is invalid");
  container.dataset.replaySceneSchema = scene.schemaVersion;
  container.dataset.cameraMode = scene.camera.defaultMode;
  container.dataset.cameraOffsetRearM = String(scene.camera.rearOffsetM);
  container.dataset.cameraOffsetHeightM = String(scene.camera.heightOffsetM);
  container.dataset.cameraLookAheadM = String(scene.camera.lookAheadM);
  container.dataset.headingInterpolation = scene.visualTolerance.pose.headingInterpolation;
  container.dataset.coordinateContract = scene.coordinateContract.rendererCoordinateSystem;
  container.dataset.renderState = "ready";
  for (const [key, value] of Object.entries(metrics)) {
    assert(finite(value), "replay metric is invalid");
    container.dataset[key] = String(value);
  }
}

export function frameTimeP95(frameTimesMs) {
  assert(Array.isArray(frameTimesMs) && frameTimesMs.length > 0 && frameTimesMs.every((value) => finite(value) && value >= 0), "frame timing evidence is invalid");
  const ordered = [...frameTimesMs].sort((left, right) => left - right);
  return ordered[Math.max(0, Math.ceil(ordered.length * 0.95) - 1)];
}
