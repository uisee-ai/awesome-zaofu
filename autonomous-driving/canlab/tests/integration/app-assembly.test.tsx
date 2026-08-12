import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { App } from '../../src/App.tsx'
import { loadBundledCanLab } from '../../src/app/load.ts'

const assetBodies = new Map([
  [
    '/assets/canlab-demo-v1.0.0.metadata.json',
    readFileSync(
      join(process.cwd(), 'public/assets/canlab-demo-v1.0.0.metadata.json'),
      'utf8',
    ),
  ],
  [
    '/assets/canlab-demo-v1.0.0.dbc',
    readFileSync(
      join(process.cwd(), 'public/assets/canlab-demo-v1.0.0.dbc'),
      'utf8',
    ),
  ],
  [
    '/assets/canlab-demo-v1.0.0.vectors.json',
    readFileSync(
      join(process.cwd(), 'public/assets/canlab-demo-v1.0.0.vectors.json'),
      'utf8',
    ),
  ],
  [
    '/assets/drive-cycle-v1.ndjson',
    readFileSync(
      join(process.cwd(), 'public/assets/drive-cycle-v1.ndjson'),
      'utf8',
    ),
  ],
])

const requestPath = (input: RequestInfo | URL): string => {
  if (typeof input === 'string') return input
  if (input instanceof URL) return input.pathname
  return new URL(input.url).pathname
}

const localAssetFetch = vi.fn<typeof fetch>(async (input) => {
  const path = requestPath(input)
  const body = assetBodies.get(path)
  return body === undefined
    ? new Response('not found', { status: 404 })
    : new Response(body, { status: 200 })
})

afterEach(() => {
  cleanup()
  localAssetFetch.mockClear()
  vi.unstubAllGlobals()
})

describe('CAN Lab application assembly', () => {
  it('loads only the four bundled assets and validates their complete identity', async () => {
    const bundle = await loadBundledCanLab(localAssetFetch)

    expect(localAssetFetch.mock.calls.map(([input]) => requestPath(input))).toEqual([
      '/assets/canlab-demo-v1.0.0.metadata.json',
      '/assets/canlab-demo-v1.0.0.dbc',
      '/assets/canlab-demo-v1.0.0.vectors.json',
      '/assets/drive-cycle-v1.ndjson',
    ])
    expect(bundle.assetMetadata).toEqual({
      schema_version: '1.0.0',
      asset: {
        name: 'CAN Lab Demo',
        file: 'canlab-demo-v1.0.0.dbc',
        version: '1.0.0',
        source: 'project-authored synthetic fixture',
        license: 'CC0-1.0',
        sha256: 'd5e6ab74ba4fccb17493cdfae79ae115e0b9b64c3153033531a3d3c74a1d23f7',
      },
      validation_vectors: {
        file: 'canlab-demo-v1.0.0.vectors.json',
        version: '1.0.0',
        sha256: '9ca0fb7a52ed9307337b23b6bc7bf5556e50ad6cc83f637ffeffed3c8d3436b4',
      },
      drive_cycle: {
        file: 'drive-cycle-v1.ndjson',
        schema: 'canlab.drive-cycle',
        schema_version: '1.0.0',
        seed: 20260804,
        scenario: 'six-phase-demo',
        sha256: '31e49897877e494e147cac0564d2a4f9c09d25ecb5c1fc6cf3d3603e3edc1110',
        phases: ['start', 'acceleration', 'cruise', 'turn', 'deceleration', 'stop'],
        expected_period_us: {
          '0x100': 100_000,
          '0x200': 200_000,
          '0x00000300': 1_000_000,
        },
      },
    })
    expect(bundle.database.messages.map(({ name, signals }) => [name, signals.length])).toEqual([
      ['Powertrain', 6],
      ['Chassis', 1],
      ['EnvironmentExtended', 2],
    ])
    expect(bundle.frames).toHaveLength(195)
    expect(bundle.dbcHash).toBe(
      'd5e6ab74ba4fccb17493cdfae79ae115e0b9b64c3153033531a3d3c74a1d23f7',
    )
    expect(bundle.vectorsHash).toBe(
      '9ca0fb7a52ed9307337b23b6bc7bf5556e50ad6cc83f637ffeffed3c8d3436b4',
    )
    expect(bundle.logHash).toBe(
      '31e49897877e494e147cac0564d2a4f9c09d25ecb5c1fc6cf3d3603e3edc1110',
    )
    expect(bundle.frames[0]).toEqual({
      type: 'frame',
      seq: 0,
      timestamp_us: 0,
      phase: 'start',
      can_id: '0x100',
      is_extended: false,
      dlc: 8,
      data: '600C000000280000',
    })
    expect(bundle.frames.at(-1)).toEqual({
      type: 'frame',
      seq: 194,
      timestamp_us: 12_000_000,
      phase: 'stop',
      can_id: '0x00000300',
      is_extended: true,
      dlc: 8,
      data: '3C7D000000000000',
    })
  })

  it.each([
    '/assets/canlab-demo-v1.0.0.dbc',
    '/assets/canlab-demo-v1.0.0.vectors.json',
    '/assets/drive-cycle-v1.ndjson',
  ])('fails closed when the actual bytes drift for %s', async (driftedPath) => {
    const driftedFetch = vi.fn<typeof fetch>(async (input) => {
      const path = requestPath(input)
      const body = assetBodies.get(path)
      return body === undefined
        ? new Response('not found', { status: 404 })
        : new Response(path === driftedPath ? `${body} ` : body, { status: 200 })
    })

    await expect(loadBundledCanLab(driftedFetch)).rejects.toThrow(
      'SHA-256 mismatch',
    )
  })

  it('uses the bundled SHA-256 fallback and still rejects drift outside secure contexts', async () => {
    vi.stubGlobal('crypto', undefined)

    const bundle = await loadBundledCanLab(localAssetFetch)
    expect(bundle.dbcHash).toBe(
      'd5e6ab74ba4fccb17493cdfae79ae115e0b9b64c3153033531a3d3c74a1d23f7',
    )

    const driftedFetch = vi.fn<typeof fetch>(async (input) => {
      const path = requestPath(input)
      const body = assetBodies.get(path)
      return body === undefined
        ? new Response('not found', { status: 404 })
        : new Response(
            path === '/assets/canlab-demo-v1.0.0.dbc' ? `${body} ` : body,
            { status: 200 },
          )
    })

    await expect(loadBundledCanLab(driftedFetch)).rejects.toThrow(
      'SHA-256 mismatch',
    )
  })

  it('renders the assembled workspace after local loading and fails closed on an asset error', async () => {
    const { unmount } = render(<App fetcher={localAssetFetch} />)

    expect(screen.getByRole('status').textContent).toContain(
      'Loading bundled CAN Lab assets',
    )
    expect(await screen.findByRole('heading', { name: 'CAN Protocol Lab' })).not.toBeNull()
    expect(screen.getByText('Offline fixture')).not.toBeNull()
    unmount()

    const failingFetch = vi.fn<typeof fetch>(async () =>
      new Response('unavailable', { status: 503 }),
    )
    render(<App fetcher={failingFetch} />)

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('Unable to load the bundled CAN Lab assets')
    expect(alert.textContent).toContain('HTTP 503')
    expect(screen.queryByRole('heading', { name: 'CAN Protocol Lab' })).toBeNull()
  })

  it('keeps CSP out of meta tags and mirrors the versioned response-header policy', () => {
    const cspPolicy = JSON.parse(
      readFileSync(join(process.cwd(), 'config/csp-policy.json'), 'utf8'),
    ) as { directives: Record<string, string[]> }
    const policy = Object.entries(cspPolicy.directives)
      .map(([name, values]) => `${name} ${values.join(' ')}`)
      .join('; ')
    const html = readFileSync(join(process.cwd(), 'index.html'), 'utf8')
    const headers = readFileSync(join(process.cwd(), 'public/_headers'), 'utf8')

    expect(html).not.toMatch(/http-equiv=["']Content-Security-Policy["']/i)
    expect(headers).toBe(`/*\n  Content-Security-Policy: ${policy}\n`)
  })
})
