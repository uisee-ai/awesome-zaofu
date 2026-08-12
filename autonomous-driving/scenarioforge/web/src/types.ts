export interface ReplayFrame {
  step: number
  position: [number, number]
  heading: number
  speed_km_h: number
  collision: boolean
  off_road: boolean
  route_progress: number
  actors: ReplayActor[]
  event_receipts: ReplayEventReceipt[]
}

export interface ReplayActor {
  actor_id: string
  role: 'ego' | 'traffic'
  position: [number, number]
  speed_mps: number
  heading: number
  state: string
}

export interface ReplayEventReceipt {
  trigger_id: string
  target_actor_id: string
  action: string
  status: string
  result: string
}

export interface ReplayEvent {
  tick: number
  kind: 'collision' | 'off_road' | 'termination'
  label: string
}

export interface ReplayCase {
  case_index: number
  seed: number
  status: string
  scenario_verdict: 'pass' | 'fail' | null
  termination_reason: string
  steps: number
  simulated_seconds: number
  collision: boolean
  off_road: boolean
  route_progress: number
  frames: ReplayFrame[]
  events: ReplayEvent[]
}

export interface ReplayBundle {
  schema_version: 'scenarioforge.replay.v1'
  bundle_id: string
  status: string
  scenario_digest: string
  cases: ReplayCase[]
  metrics: {
    case_count: number
    completed_count: number
    failed_count: number
    total_steps: number
    total_case_wall_seconds: number
    total_cpu_seconds: number
    peak_worker_rss_bytes: number
  }
  safety_evidence: ReplaySafetyEvidence | null
  provider: {
    backend: 'metadrive-simulator'
    backend_version: '0.4.3'
    execution_kind: 'real-metadrive'
    network_policy: 'denied'
    auto_download: false
  }
  execution: {
    runner_state: 'stopped'
    metadrive_calls: 0
    external_network: 'denied'
  }
}

export interface ReplaySafetyEvidence {
  schema_version: 'scenarioforge.safety-evidence.v1'
  cases: ReplaySafetyCase[]
}

export interface ReplaySafetyCase {
  case_index: number
  metrics: {
    minimum_ttc_seconds: number | null
    minimum_headway_seconds: number | null
    event_to_response_latency_seconds: number | null
    collision: boolean
    off_road: boolean
    route_progress: number
  }
  safety_constraints: Record<string, boolean | number>
  safety_verdict: 'pass' | 'fail'
  violations: string[]
}

export interface CanonicalPreview {
  digest: string
  scenario: Record<string, unknown>
}

export interface Diagnostic {
  location: string
  code: string
  message: string
}

interface AuthoredActor {
  id?: unknown
  role?: unknown
  initial_state?: { lane?: unknown; longitudinal?: unknown; speed?: unknown }
}

interface AuthoredTrigger {
  id?: unknown
  action?: unknown
  target_actor_id?: unknown
  seconds?: unknown
  distance?: unknown
}

export interface AuthoringPreview {
  road: { laneCount: number | null; laneWidth: number | null }
  ego: { id: string; lane: number | null; longitudinal: number | null; speed: number | null } | null
  lead: { id: string; lane: number | null; longitudinal: number | null; speed: number | null } | null
  event: { id: string; action: string; targetActorId: string; at: string } | null
  safety: { maxSpeed: number | null; minimumHeadway: number | null; collisionFree: boolean | null } | null
}

function numberOrNull(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function actorPreview(actor: AuthoredActor | undefined) {
  if (!actor || typeof actor.id !== 'string') return null
  return {
    id: actor.id,
    lane: numberOrNull(actor.initial_state?.lane),
    longitudinal: numberOrNull(actor.initial_state?.longitudinal),
    speed: numberOrNull(actor.initial_state?.speed),
  }
}

export function scenarioPreview(scenario: Record<string, unknown>): AuthoringPreview {
  const map = (scenario.map ?? {}) as Record<string, unknown>
  const actors = Array.isArray(scenario.actors) ? scenario.actors as AuthoredActor[] : []
  const ego = actors.find((actor) => actor.role === 'ego')
  const lead = actors.find((actor) => actor.id === 'lead') ?? actors.find((actor) => actor.role === 'traffic')
  const triggers = Array.isArray(scenario.event_triggers) ? scenario.event_triggers as AuthoredTrigger[] : []
  const trigger = triggers.find((item) => item.target_actor_id === lead?.id) ?? triggers[0]
  const safety = scenario.safety as Record<string, unknown> | undefined
  const at = numberOrNull(trigger?.seconds) !== null
    ? `${trigger?.seconds} s`
    : numberOrNull(trigger?.distance) !== null ? `${trigger?.distance} m` : 'not configured'

  return {
    road: { laneCount: numberOrNull(map.lane_count), laneWidth: numberOrNull(map.lane_width) },
    ego: actorPreview(ego),
    lead: actorPreview(lead),
    event: trigger && typeof trigger.id === 'string' && typeof trigger.action === 'string' && typeof trigger.target_actor_id === 'string'
      ? { id: trigger.id, action: trigger.action, targetActorId: trigger.target_actor_id, at }
      : null,
    safety: safety
      ? { maxSpeed: numberOrNull(safety.max_speed), minimumHeadway: numberOrNull(safety.minimum_headway), collisionFree: typeof safety.collision_free === 'boolean' ? safety.collision_free : null }
      : null,
  }
}
