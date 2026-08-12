import type { CanonicalPreview, Diagnostic, ReplayBundle } from './types'

export interface LocalConnection {
  apiBase: string
  capability: string
  csrf: string
}

interface ApiErrorBody {
  error?: { code?: string; message?: string }
  diagnostics?: Diagnostic[]
}

export interface SampleCatalog { samples: Array<{ id: string; json: string; yaml: string }> }
export interface SampleDocument { id: string; media_type: 'application/json'; source: string }
export interface JobSnapshot { job_id: string; status: string; bundle_path?: string | null; cancel_requested?: boolean; error?: string | null }
export interface ResimulationReport { status: 'pass' | 'regression' | 'incompatible'; exact_differences: unknown[]; numeric_differences: unknown[] }

function assertLoopbackApi(apiBase: string): void {
  const url = new URL(apiBase)
  if (url.protocol !== 'http:' || !['127.0.0.1', 'localhost', '[::1]', '::1'].includes(url.hostname)) {
    throw new Error('ScenarioForge API endpoint must use HTTP loopback')
  }
}

async function request<T>(
  connection: LocalConnection,
  path: string,
  method: 'GET' | 'POST',
  body?: object,
): Promise<T> {
  assertLoopbackApi(connection.apiBase)
  const response = await fetch(`${connection.apiBase}${path}`, {
    method,
    credentials: 'omit',
    cache: 'no-store',
    referrerPolicy: 'no-referrer',
    headers: {
      'Content-Type': 'application/json',
      'X-ScenarioForge-Capability': connection.capability,
      'X-ScenarioForge-CSRF': connection.csrf,
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const payload = (await response.json()) as T & ApiErrorBody
  if (!response.ok) {
    const error = new Error(payload.error?.message ?? 'Local API request failed')
    Object.assign(error, {
      code: payload.error?.code ?? 'request_failed',
      diagnostics: payload.diagnostics ?? [],
    })
    throw error
  }
  return payload
}

function post<T>(connection: LocalConnection, path: string, body: object): Promise<T> {
  return request(connection, path, 'POST', body)
}

export function loadSamples(connection: LocalConnection): Promise<SampleCatalog> {
  return request(connection, '/api/samples', 'GET')
}

export function loadSampleDocument(connection: LocalConnection, sampleId: string): Promise<SampleDocument> {
  return request(connection, `/api/samples/${encodeURIComponent(sampleId)}`, 'GET')
}

export async function validateScenario(
  connection: LocalConnection,
  source: string,
): Promise<{ valid: true; diagnostics: []; canonical: CanonicalPreview }> {
  return post(connection, '/api/scenarios/validate', {
    source,
    media_type: 'application/json',
  })
}

export async function exportScenario(
  connection: LocalConnection,
  source: string,
  format: 'json' | 'yaml',
): Promise<{ format: string; document: string }> {
  return post(connection, '/api/scenarios/export', {
    source,
    media_type: 'application/json',
    format,
  })
}

export async function runScenario(
  connection: LocalConnection,
  source: string,
  scenarioDigest: string,
  seeds: number[],
): Promise<JobSnapshot> {
  return post(connection, '/api/runs', {
    source,
    media_type: 'application/json',
    request: {
      schema_version: 'scenarioforge.run-request.v1',
      scenario_digest: scenarioDigest,
      seeds,
      profile: 'default',
      limits: {
        workers: 1,
        aggregate_cpu_threads: 2,
        max_steps: 200,
        max_simulated_seconds: 30,
        case_wall_seconds: 60,
        bundle_wall_seconds: 600,
        bundle_disk_bytes: 1_073_741_824,
      },
    },
  })
}

export function refreshJob(connection: LocalConnection, jobId: string): Promise<JobSnapshot> {
  return request(connection, `/api/runs/${encodeURIComponent(jobId)}`, 'GET')
}

export function cancelJob(connection: LocalConnection, jobId: string): Promise<JobSnapshot> {
  return post(connection, `/api/runs/${encodeURIComponent(jobId)}/cancel`, {})
}

export async function loadReplay(
  connection: LocalConnection,
  bundleId: string,
): Promise<ReplayBundle> {
  return post(connection, '/api/replays/load', { bundle_id: bundleId })
}

export function verifyReplay(connection: LocalConnection, bundleId: string): Promise<{ status: 'pass'; bundle_id: string; replay?: ReplayBundle }> {
  return post(connection, '/api/replays/verify', { bundle_id: bundleId })
}

export function compareBundles(connection: LocalConnection, baselineBundleId: string, candidateBundleId: string, profile: Record<string, unknown>): Promise<ResimulationReport> {
  return post(connection, '/api/oracle/compare', { baseline_bundle_id: baselineBundleId, candidate_bundle_id: candidateBundleId, profile })
}
