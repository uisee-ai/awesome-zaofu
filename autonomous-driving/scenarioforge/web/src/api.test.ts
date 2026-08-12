import { afterEach, expect, it, vi } from 'vitest'

import { cancelJob, compareBundles, loadSampleDocument, loadSamples, refreshJob, runScenario, verifyReplay } from './api'
import { scenarioPreview } from './types'

const connection = { apiBase: 'http://127.0.0.1:4174', capability: 'cap', csrf: 'csrf' }

afterEach(() => vi.unstubAllGlobals())

it('uses the protected catalog and authoritative sample document endpoints', async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify({ samples: [{ id: 'following', json: 'following.json', yaml: 'following.yaml' }] })))
    .mockResolvedValueOnce(new Response(JSON.stringify({ id: 'following', media_type: 'application/json', source: '{"name":"following"}' })))
  vi.stubGlobal('fetch', fetchMock)

  await expect(loadSamples(connection)).resolves.toMatchObject({ samples: [{ id: 'following' }] })
  await expect(loadSampleDocument(connection, 'following')).resolves.toMatchObject({ source: '{"name":"following"}' })
  expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
    'http://127.0.0.1:4174/api/samples',
    'http://127.0.0.1:4174/api/samples/following',
  ])
})

it('sends multi-seed jobs and lifecycle/replay controls to the real API', async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify({ job_id: 'run-1', status: 'queued' })))
    .mockResolvedValueOnce(new Response(JSON.stringify({ job_id: 'run-1', status: 'running' })))
    .mockResolvedValueOnce(new Response(JSON.stringify({ job_id: 'run-1', status: 'running', cancel_requested: true })))
    .mockResolvedValueOnce(new Response(JSON.stringify({ status: 'pass', bundle_id: 'bundle' })))
    .mockResolvedValueOnce(new Response(JSON.stringify({ status: 'pass', exact_differences: [], numeric_differences: [] })))
  vi.stubGlobal('fetch', fetchMock)

  await runScenario(connection, '{}', 'a'.repeat(64), [17, 23])
  await refreshJob(connection, 'run-1')
  await cancelJob(connection, 'run-1')
  await verifyReplay(connection, 'bundle')
  await compareBundles(connection, 'bundle', 'resimulated-bundle', {})

  expect(JSON.parse(fetchMock.mock.calls[0]?.[1]?.body as string).request.seeds).toEqual([17, 23])
  expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
    'http://127.0.0.1:4174/api/runs',
    'http://127.0.0.1:4174/api/runs/run-1',
    'http://127.0.0.1:4174/api/runs/run-1/cancel',
    'http://127.0.0.1:4174/api/replays/verify',
    'http://127.0.0.1:4174/api/oracle/compare',
  ])
  expect(JSON.parse(fetchMock.mock.calls[4]?.[1]?.body as string)).toEqual({
    baseline_bundle_id: 'bundle',
    candidate_bundle_id: 'resimulated-bundle',
    profile: {},
  })
})

it('rejects non-loopback API bases before credentials can be sent', async () => {
  const fetchMock = vi.fn()
  vi.stubGlobal('fetch', fetchMock)

  await expect(loadSamples({ ...connection, apiBase: 'https://example.test' })).rejects.toThrow(
    'must use HTTP loopback',
  )
  expect(fetchMock).not.toHaveBeenCalled()
})

it('projects the authored road, ego, lead, and emergency-brake trigger before a run', () => {
  expect(scenarioPreview({
    map: { lane_count: 2, lane_width: 3.5 },
    actors: [
      { id: 'ego', role: 'ego', initial_state: { lane: 0, longitudinal: 5, speed: 8 } },
      { id: 'lead', role: 'traffic', initial_state: { lane: 0, longitudinal: 24, speed: 12 } },
    ],
    event_triggers: [
      { id: 'brake', kind: 'at_time', seconds: 2, action: 'yield', target_actor_id: 'lead' },
    ],
    safety: { max_speed: 20, minimum_headway: 1.5, collision_free: true },
  })).toEqual({
    road: { laneCount: 2, laneWidth: 3.5 },
    ego: { id: 'ego', lane: 0, longitudinal: 5, speed: 8 },
    lead: { id: 'lead', lane: 0, longitudinal: 24, speed: 12 },
    event: { id: 'brake', action: 'yield', targetActorId: 'lead', at: '2 s' },
    safety: { maxSpeed: 20, minimumHeadway: 1.5, collisionFree: true },
  })
})
