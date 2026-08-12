import { useEffect, useMemo, useState } from 'react'

import {
  cancelJob,
  compareBundles,
  exportScenario,
  loadSampleDocument,
  loadSamples,
  refreshJob,
  loadReplay,
  runScenario,
  validateScenario,
  verifyReplay,
  type JobSnapshot,
  type LocalConnection,
  type ResimulationReport,
} from './api'
import { ReplayScene } from './ReplayScene'
import { scenarioPreview, type CanonicalPreview, type Diagnostic, type ReplayBundle } from './types'

const initialScenario = JSON.stringify(
  {
    schema_version: 'scenarioforge.scenario-spec.v1',
    name: 'following-emergency-brake',
    map: { block_sequence: 'S', lane_count: 2, lane_width: 3.5 },
    actors: [
      { id: 'ego', role: 'ego', initial_state: { lane: 0, longitudinal: 5, speed: 8 }, behavior: 'follow_lead' },
      { id: 'lead', role: 'traffic', initial_state: { lane: 0, longitudinal: 24, speed: 12 }, behavior: 'keep_lane' },
    ],
    environment: { traffic_density: 0.1 },
    event_triggers: [{ id: 'lead-emergency-brake', kind: 'at_time', seconds: 2, action: 'yield', target_actor_id: 'lead' }],
    safety: { max_speed: 20, minimum_headway: 1.5, collision_free: true },
    tags: ['following-emergency-brake', 'offline'],
  },
  null,
  2,
)

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : 'Local operation failed'
}

function diagnosticsOf(error: unknown): Diagnostic[] {
  if (error instanceof Error && 'diagnostics' in error && Array.isArray(error.diagnostics)) {
    return error.diagnostics as Diagnostic[]
  }
  return []
}

function parseSeeds(value: string): number[] {
  const seeds = value.split(',').map((item) => Number(item.trim())).filter((item) => Number.isInteger(item) && item >= 0)
  if (seeds.length === 0) throw new Error('Enter at least one non-negative seed')
  return [...new Set(seeds)]
}

function updateJson(source: string, update: (document: Record<string, unknown>) => void): string {
  const document = JSON.parse(source) as Record<string, unknown>
  update(document)
  return JSON.stringify(document, null, 2)
}

function updateActor(
  document: Record<string, unknown>,
  id: 'ego' | 'lead',
  role: 'ego' | 'traffic',
  update: (actor: Record<string, unknown>) => void,
) {
  const actors = Array.isArray(document.actors) ? [...document.actors] as Record<string, unknown>[] : []
  const index = actors.findIndex((actor) => actor.id === id)
  const actor = { ...(index >= 0 ? actors[index] : { id, role }) }
  update(actor)
  if (index >= 0) actors[index] = actor
  else actors.push(actor)
  document.actors = actors
}

export default function App() {
  const [connection, setConnection] = useState<LocalConnection>({
    apiBase: 'http://127.0.0.1:4174',
    capability: '',
    csrf: '',
  })
  const [source, setSource] = useState(initialScenario)
  const [samples, setSamples] = useState<Array<{ id: string; json: string; yaml: string }>>([])
  const [sampleId, setSampleId] = useState('')
  const [canonical, setCanonical] = useState<CanonicalPreview | null>(null)
  const [diagnostics, setDiagnostics] = useState<Diagnostic[]>([])
  const [authoringStatus, setAuthoringStatus] = useState('Ready to validate')
  const [exported, setExported] = useState('')
  const [seeds, setSeeds] = useState('17, 23')
  const [job, setJob] = useState<JobSnapshot | null>(null)
  const [jobStatus, setJobStatus] = useState('No job submitted')
  const [bundleId, setBundleId] = useState('bundle')
  const [replay, setReplay] = useState<ReplayBundle | null>(null)
  const [replayStatus, setReplayStatus] = useState('No replay loaded')
  const [verificationStatus, setVerificationStatus] = useState('Exact replay has not been verified')
  const [candidateBundleId, setCandidateBundleId] = useState('')
  const [profile, setProfile] = useState('{}')
  const [comparison, setComparison] = useState<ResimulationReport | null>(null)
  const [caseIndex, setCaseIndex] = useState(0)
  const [tick, setTick] = useState(0)
  const [rate, setRate] = useState(1)
  const [playing, setPlaying] = useState(false)

  const selectedCase = replay?.cases.find((item) => item.case_index === caseIndex)
  const safetyCase = replay?.safety_evidence?.cases.find((item) => item.case_index === caseIndex)
  const frames = selectedCase?.frames ?? []
  const maxTick = Math.max(0, frames.length - 1)
  const frame = frames[Math.min(tick, maxTick)]

  useEffect(() => {
    if (!playing || frames.length === 0) return
    const timer = window.setInterval(() => {
      setTick((current) => {
        if (current >= maxTick) {
          setPlaying(false)
          return current
        }
        return current + 1
      })
    }, 350 / rate)
    return () => window.clearInterval(timer)
  }, [frames.length, maxTick, playing, rate])

  useEffect(() => {
    setPlaying(false)
    setTick(0)
  }, [caseIndex])

  const canonicalText = useMemo(
    () => (canonical ? JSON.stringify(canonical.scenario, null, 2) : 'Validate to preview'),
    [canonical],
  )
  const authoredPreview = useMemo(() => {
    try { return scenarioPreview(JSON.parse(source) as Record<string, unknown>) } catch { return null }
  }, [source])

  function updateField(update: (document: Record<string, unknown>) => void) {
    try {
      setSource(updateJson(source, update))
      setCanonical(null)
    } catch {
      setAuthoringStatus('Fix the JSON source before using structured fields')
    }
  }

  function applyJob(snapshot: JobSnapshot) {
    setJob(snapshot)
    setJobStatus(`${snapshot.status}${snapshot.cancel_requested ? ' · cancel requested' : ''}${snapshot.error ? ` · ${snapshot.error}` : ''}`)
    if (snapshot.bundle_path) setBundleId(snapshot.bundle_path.split('/').at(-1) ?? bundleId)
  }

  async function refreshSamples() {
    try {
      const catalog = await loadSamples(connection)
      setSamples(catalog.samples)
      setSampleId((current) => current || catalog.samples.find((sample) => sample.id === 'following-emergency-brake')?.id || catalog.samples.find((sample) => sample.id === 'following')?.id || '')
      setAuthoringStatus(`${catalog.samples.length} committed samples available`)
    } catch (error) { setAuthoringStatus(messageOf(error)) }
  }

  async function loadSample() {
    if (!sampleId) return
    try {
      const document = await loadSampleDocument(connection, sampleId)
      setSource(document.source)
      setCanonical(null)
      setDiagnostics([])
      setExported('')
      setAuthoringStatus(`Loaded authoritative committed sample: ${document.id}`)
    } catch (error) { setAuthoringStatus(messageOf(error)) }
  }

  function loadEmergencyBrakeTemplate() {
    setSource(initialScenario)
    setCanonical(null)
    setDiagnostics([])
    setExported('')
    setAuthoringStatus('Loaded following-emergency-brake authoring template')
  }

  async function validate() {
    setDiagnostics([])
    try {
      const result = await validateScenario(connection, source)
      setCanonical(result.canonical)
      setAuthoringStatus('Scenario is valid and canonical')
    } catch (error) {
      setCanonical(null)
      setDiagnostics(diagnosticsOf(error))
      setAuthoringStatus(messageOf(error))
    }
  }

  async function exportDocument(format: 'json' | 'yaml') {
    try {
      const result = await exportScenario(connection, source, format)
      setExported(result.document)
      setAuthoringStatus(`Canonical ${format.toUpperCase()} export ready`)
    } catch (error) {
      setAuthoringStatus(messageOf(error))
    }
  }

  async function run() {
    try {
      const current = canonical ?? (await validateScenario(connection, source)).canonical
      setCanonical(current)
      const result = await runScenario(connection, source, current.digest, parseSeeds(seeds))
      applyJob(result)
      setAuthoringStatus(`Submitted real MetaDrive job ${result.job_id}`)
    } catch (error) {
      setAuthoringStatus(messageOf(error))
    }
  }

  async function refreshCurrentJob() {
    if (!job) return
    try { applyJob(await refreshJob(connection, job.job_id)) } catch (error) { setJobStatus(messageOf(error)) }
  }

  async function cancelCurrentJob() {
    if (!job) return
    try { applyJob(await cancelJob(connection, job.job_id)) } catch (error) { setJobStatus(messageOf(error)) }
  }

  async function load() {
    setPlaying(false)
    try {
      const result = await loadReplay(connection, bundleId)
      setReplay(result)
      setCaseIndex(result.cases[0]?.case_index ?? 0)
      setTick(0)
      setReplayStatus('Sealed replay ready')
    } catch (error) {
      setReplay(null)
      setReplayStatus(messageOf(error))
    }
  }

  async function verify() {
    try {
      const result = await verifyReplay(connection, bundleId)
      if (result.replay) setReplay(result.replay)
      setVerificationStatus(`Exact replay ${result.status}`)
    } catch (error) { setVerificationStatus(messageOf(error)) }
  }

  async function compare() {
    try {
      const parsed = JSON.parse(profile)
      if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('Tolerance profile must be a JSON object')
      setComparison(await compareBundles(connection, bundleId, candidateBundleId, parsed as Record<string, unknown>))
    } catch (error) { setReplayStatus(messageOf(error)) }
  }

  return (
    <main>
      <header className="hero">
        <div>
          <p className="eyebrow">LOCAL-FIRST · SEALED EVIDENCE</p>
          <h1>ScenarioForge Offline Studio</h1>
          <p>Author, run, and inspect exact MetaDrive traces without a cloud dependency.</p>
        </div>
        <div className="security-badge">Loopback only<br />No cookies · No telemetry</div>
      </header>

      <section className="connection panel" aria-label="Local API connection">
        <label>API endpoint<input value={connection.apiBase} onChange={(event) => setConnection({ ...connection, apiBase: event.target.value })} /></label>
        <label>Capability token<input type="password" autoComplete="off" value={connection.capability} onChange={(event) => setConnection({ ...connection, capability: event.target.value })} /></label>
        <label>CSRF token<input type="password" autoComplete="off" value={connection.csrf} onChange={(event) => setConnection({ ...connection, csrf: event.target.value })} /></label>
      </section>

      <div className="workspace">
        <section className="panel authoring">
          <div className="section-heading"><div><p className="eyebrow">01 · AUTHOR</p><h2>Scenario document</h2></div><span>{authoringStatus}</span></div>
          <div className="sample-row">
            <label>Committed sample<select aria-label="Committed sample" value={sampleId} onChange={(event) => setSampleId(event.target.value)}><option value="">Refresh catalog first</option>{samples.map((sample) => <option key={sample.id} value={sample.id}>{sample.id}</option>)}</select></label>
            <button className="secondary" onClick={refreshSamples}>Refresh samples</button>
            <button onClick={loadSample} disabled={!sampleId}>Load authoritative sample</button>
          </div>
          <button className="secondary showcase-template" onClick={loadEmergencyBrakeTemplate}>Load following-emergency-brake template</button>
          <div className="structured-fields" aria-label="Structured P0 fields">
            <label>Lane count<input type="number" min="1" defaultValue="2" onChange={(event) => updateField((document) => { document.map = { ...((document.map ?? {}) as Record<string, unknown>), lane_count: Number(event.target.value) } })} /></label>
            <label>Traffic density<input type="number" min="0" step="0.05" defaultValue="0.1" onChange={(event) => updateField((document) => { document.environment = { ...((document.environment ?? {}) as Record<string, unknown>), traffic_density: Number(event.target.value) } })} /></label>
            <label>Seeds<input aria-label="Seeds" value={seeds} onChange={(event) => setSeeds(event.target.value)} /></label>
          </div>
          <div className="structured-fields emergency-fields" aria-label="Following emergency brake fields">
            <label>Ego start (m)<input aria-label="Ego start" type="number" defaultValue="5" onChange={(event) => updateField((document) => updateActor(document, 'ego', 'ego', (actor) => { actor.initial_state = { ...((actor.initial_state ?? {}) as Record<string, unknown>), longitudinal: Number(event.target.value), lane: 0, speed: 8 }; actor.behavior = 'follow_lead' }))} /></label>
            <label>Ego speed (m/s)<input aria-label="Ego speed" type="number" defaultValue="8" onChange={(event) => updateField((document) => updateActor(document, 'ego', 'ego', (actor) => { actor.initial_state = { ...((actor.initial_state ?? {}) as Record<string, unknown>), speed: Number(event.target.value), lane: 0, longitudinal: 5 }; actor.behavior = 'follow_lead' }))} /></label>
            <label>Lead start (m)<input aria-label="Lead start" type="number" defaultValue="24" onChange={(event) => updateField((document) => updateActor(document, 'lead', 'traffic', (actor) => { actor.initial_state = { ...((actor.initial_state ?? {}) as Record<string, unknown>), longitudinal: Number(event.target.value), lane: 0, speed: 12 } }))} /></label>
            <label>Lead speed (m/s)<input aria-label="Lead speed" type="number" defaultValue="12" onChange={(event) => updateField((document) => updateActor(document, 'lead', 'traffic', (actor) => { actor.initial_state = { ...((actor.initial_state ?? {}) as Record<string, unknown>), speed: Number(event.target.value), lane: 0, longitudinal: 24 } }))} /></label>
            <label>Brake time (s)<input aria-label="Brake time" type="number" min="0" step="0.1" defaultValue="2" onChange={(event) => updateField((document) => { document.event_triggers = [{ id: 'lead-emergency-brake', kind: 'at_time', seconds: Number(event.target.value), action: 'yield', target_actor_id: 'lead' }] })} /></label>
            <label>Minimum headway (s)<input aria-label="Minimum headway" type="number" min="0.1" step="0.1" defaultValue="1.5" onChange={(event) => updateField((document) => { document.safety = { ...((document.safety ?? {}) as Record<string, unknown>), max_speed: 20, minimum_headway: Number(event.target.value), collision_free: true } })} /></label>
          </div>
          <section className="preflight-preview" aria-label="Pre-run following emergency brake preview">
            <h3>Pre-run road and actor preview</h3>
            {authoredPreview ? <div className="preflight-grid"><p><b>Road</b> {authoredPreview.road.laneCount ?? '—'} lanes · {authoredPreview.road.laneWidth ?? '—'} m</p><p><b>Ego</b> {authoredPreview.ego ? `${authoredPreview.ego.longitudinal ?? '—'} m · ${authoredPreview.ego.speed ?? '—'} m/s` : 'not configured'}</p><p><b>Lead</b> {authoredPreview.lead ? `${authoredPreview.lead.longitudinal ?? '—'} m · ${authoredPreview.lead.speed ?? '—'} m/s` : 'not configured'}</p><p><b>Emergency event</b> {authoredPreview.event ? `${authoredPreview.event.action} ${authoredPreview.event.targetActorId} at ${authoredPreview.event.at}` : 'not configured'}</p><p><b>Safety</b> {authoredPreview.safety ? `headway ≥ ${authoredPreview.safety.minimumHeadway ?? '—'} s` : 'not configured'}</p></div> : <p className="preview-error">Fix the JSON source to restore the pre-run preview.</p>}
          </section>
          <label className="editor-label">Scenario JSON<textarea spellCheck={false} value={source} onChange={(event) => setSource(event.target.value)} /></label>
          <div className="actions">
            <button onClick={validate}>Validate</button>
            <button onClick={run}>Run real case</button>
            <button className="secondary" onClick={() => exportDocument('json')}>Export JSON</button>
            <button className="secondary" onClick={() => exportDocument('yaml')}>Export YAML</button>
          </div>
          <div className="job-controls" aria-label="Multi-seed job controls"><span data-testid="job-status">{jobStatus}</span><div className="actions"><button className="secondary" onClick={refreshCurrentJob} disabled={!job}>Refresh job</button><button className="secondary" onClick={cancelCurrentJob} disabled={!job || job.cancel_requested}>Cancel job</button></div></div>
          {diagnostics.length > 0 && <ul className="diagnostics">{diagnostics.map((item) => <li key={`${item.location}:${item.code}`}><code>{item.location}</code> {item.message}</li>)}</ul>}
          <div className="preview-grid">
            <div><h3>Canonical preview</h3><pre>{canonicalText}</pre></div>
            <div><h3>Export</h3><pre>{exported || 'Choose JSON or YAML'}</pre></div>
          </div>
        </section>

        <section className="panel replay">
          <div className="section-heading"><div><p className="eyebrow">02 · REPLAY</p><h2>Exact trace viewer</h2></div><span data-testid="replay-status">{replayStatus}</span></div>
          <div className="load-row"><label>Bundle ID<input value={bundleId} onChange={(event) => setBundleId(event.target.value)} /></label><div className="actions"><button onClick={load}>Load sealed replay</button><button className="secondary" onClick={verify}>Verify exact replay</button></div></div>
          <p className="operation-status" data-testid="verification-status">{verificationStatus}</p>
          <ReplayScene frame={frame} />
          <div className="transport">
            <label>Case<select value={caseIndex} onChange={(event) => setCaseIndex(Number(event.target.value))}>{replay?.cases.map((item) => <option key={item.case_index} value={item.case_index}>Case {item.case_index} · seed {item.seed}</option>)}</select></label>
            <button aria-label="Step backward" onClick={() => setTick((current) => Math.max(0, current - 1))}>−1</button>
            <button aria-label={playing ? 'Pause' : 'Play'} onClick={() => setPlaying((current) => !current)} disabled={!frame}>{playing ? 'Pause' : 'Play'}</button>
            <button aria-label="Step forward" onClick={() => setTick((current) => Math.min(maxTick, current + 1))}>+1</button>
            <label>Playback rate<select value={rate} onChange={(event) => setRate(Number(event.target.value))}><option value="0.5">0.5×</option><option value="1">1×</option><option value="2">2×</option></select></label>
          </div>
          <label className="seek">Seek tick<input aria-label="Seek tick" type="range" min="0" max={maxTick} value={Math.min(tick, maxTick)} onChange={(event) => { setPlaying(false); setTick(Number(event.target.value)) }} /></label>
          <div className="readout">
            <div><span>Canonical tick</span><strong data-testid="tick">{frame ? `${frame.step} / ${maxTick}` : '—'}</strong></div>
            <div><span>Position</span><strong data-testid="position">{frame ? frame.position.join(', ') : '—'}</strong></div>
            <div><span>Speed</span><strong data-testid="speed">{frame ? `${frame.speed_km_h} km/h` : '—'}</strong></div>
            <div><span>Route progress</span><strong data-testid="route-progress">{frame?.route_progress ?? '—'}</strong></div>
            <div><span>Minimum TTC</span><strong data-testid="minimum-ttc">{safetyCase?.metrics.minimum_ttc_seconds ?? '—'} s</strong></div>
          </div>
          <output data-testid="frame-json" data-frame={frame ? JSON.stringify(frame) : '{}'} hidden />
          <div className="details-grid">
            <div data-testid="events"><h3>Events</h3>{frame?.event_receipts.length ? frame.event_receipts.map((event) => <p key={event.trigger_id}><b>{event.trigger_id}</b> {event.action} → {event.target_actor_id} · {event.result}</p>) : selectedCase?.events.map((event) => <p key={`${event.tick}:${event.kind}`}><b>T{event.tick}</b> {event.label}</p>) ?? <p>No events loaded</p>}</div>
            <div data-testid="metrics"><h3>Safety & actors</h3>{replay ? <><p>{frame?.actors.map((actor) => `${actor.actor_id}: ${actor.state}`).join(' · ') || 'No actor evidence at this tick'}</p><p><b>Safety verdict:</b> {safetyCase?.safety_verdict ?? selectedCase?.scenario_verdict ?? '—'}</p><p>{replay.provider.backend}@{replay.provider.backend_version}</p></> : <p>No metrics loaded</p>}</div>
          </div>
          <section className="comparison" aria-label="Re-simulation result"><h3>Re-simulation comparison</h3><label>New bundle ID<input aria-label="New bundle ID" value={candidateBundleId} onChange={(event) => setCandidateBundleId(event.target.value)} /></label><label>Tolerance profile JSON<textarea aria-label="Tolerance profile JSON" value={profile} onChange={(event) => setProfile(event.target.value)} /></label><button onClick={compare} disabled={!candidateBundleId}>Compare immutable bundles</button><output data-testid="comparison-result">{comparison ? `${comparison.status} · ${comparison.exact_differences.length + comparison.numeric_differences.length} differences` : 'No re-simulation comparison yet'}</output></section>
        </section>
      </div>
    </main>
  )
}
