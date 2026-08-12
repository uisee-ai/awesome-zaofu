import { expect, test, type BrowserContext, type Page } from '@playwright/test'
import { createHash } from 'node:crypto'
import { createServer, type RequestListener, type Server } from 'node:http'
import { mkdir, readFile, stat, writeFile } from 'node:fs/promises'
import { dirname, extname, join, resolve, sep } from 'node:path'
import { mergeP0EvidenceArtifacts, type P0EvidenceArtifact } from '../../tools/merge-p0-evidence'

interface QualificationReceipt {
  readonly schema_version: string
  readonly status: string
  readonly channel: string
  readonly platform: string
  readonly stable_version: string
  readonly browser_version: string
  readonly executable_path: string
  readonly executable_sha256: string
  readonly image_ref: string
  readonly image_digest: string
  readonly target_commit: string
  readonly target_tree: string
  readonly qualification_snapshot: {
    readonly source_url: string
    readonly source_sha256: string
    readonly download_url: string
  }
}

const projectRoot = process.cwd()
const evidenceDirectory = resolve(
  process.env.P0_EVIDENCE_DIR ?? 'artifacts/verification/p0/browser',
)
const qualificationPath = resolve(
  process.env.P0_QUALIFICATION_RECEIPT ??
    join(evidenceDirectory, 'qualification.json'),
)
const cspPolicy = JSON.parse(
  await readFile(join(projectRoot, 'config/csp-policy.json'), 'utf8'),
) as { policy_version: string; directives: Record<string, string[]> }
const expectedCsp = Object.entries(cspPolicy.directives)
  .map(([name, values]) => `${name} ${values.join(' ')}`)
  .join('; ')

const sha256 = (value: Buffer | string) =>
  createHash('sha256').update(value).digest('hex')

const writeJson = async (path: string, value: unknown) => {
  await mkdir(dirname(path), { recursive: true })
  await writeFile(path, `${JSON.stringify(value, null, 2)}\n`, 'utf8')
}

const isLoopback = (value: string): boolean => {
  const url = new URL(value)
  return (
    (url.protocol === 'http:' || url.protocol === 'https:') &&
    ['127.0.0.1', 'localhost', '[::1]', '::1'].includes(url.hostname)
  )
}

const listen = (
  handler: RequestListener,
): Promise<{ server: Server; origin: string }> => new Promise((resolveListen, reject) => {
  const server = createServer(handler)
  server.once('error', reject)
  server.listen(0, '127.0.0.1', () => {
    const address = server.address()
    if (address === null || typeof address === 'string') {
      reject(new Error('loopback evidence server did not expose a TCP address'))
      return
    }
    resolveListen({ server, origin: `http://127.0.0.1:${address.port}` })
  })
})

const closeServer = (server: Server): Promise<void> => new Promise((resolveClose, reject) => {
  server.close((error) => {
    if (error === undefined) resolveClose()
    else reject(error)
  })
})

const storageSnapshot = async (context: BrowserContext, page: Page) => {
  const browserState = await page.evaluate(async () => ({
    localStorageEntries: localStorage.length,
    sessionStorageEntries: sessionStorage.length,
    indexedDatabases: (await indexedDB.databases()).map(({ name, version }) => ({
      name,
      version,
    })),
    cacheStorageKeys: await caches.keys(),
    serviceWorkerRegistrations: (await navigator.serviceWorker.getRegistrations())
      .map(({ scope }) => scope),
  }))
  return {
    cookies: (await context.cookies()).map(({ name, domain, path }) => ({
      name,
      domain,
      path,
    })),
    ...browserState,
  }
}

const expectEmptyStorage = (snapshot: Awaited<ReturnType<typeof storageSnapshot>>) => {
  expect(snapshot).toEqual({
    cookies: [],
    serviceWorkerRegistrations: [],
    localStorageEntries: 0,
    sessionStorageEntries: 0,
    indexedDatabases: [],
    cacheStorageKeys: [],
  })
}

const startTamperedPreview = async () => {
  const distRoot = resolve(projectRoot, 'dist')
  return listen(async (request, response) => {
    try {
      const pathname = decodeURIComponent(
        new URL(request.url ?? '/', 'http://127.0.0.1').pathname,
      )
      const normalized = pathname === '/' ? '/index.html' : pathname
      const path = resolve(distRoot, `.${normalized}`)
      if (path !== distRoot && !path.startsWith(`${distRoot}${sep}`)) {
        response.writeHead(400)
        response.end('invalid path')
        return
      }
      const details = await stat(path)
      if (!details.isFile()) throw new Error('not a file')
      let body = await readFile(path)
      if (normalized === '/assets/canlab-demo-v1.0.0.dbc') {
        body = Buffer.concat([body, Buffer.from(' ')])
      }
      const type = new Map([
        ['.css', 'text/css; charset=utf-8'],
        ['.dbc', 'text/plain; charset=utf-8'],
        ['.html', 'text/html; charset=utf-8'],
        ['.js', 'text/javascript; charset=utf-8'],
        ['.json', 'application/json; charset=utf-8'],
        ['.ndjson', 'application/x-ndjson; charset=utf-8'],
      ]).get(extname(path)) ?? 'application/octet-stream'
      response.writeHead(200, {
        'Cache-Control': 'no-store',
        'Content-Security-Policy': expectedCsp,
        'Content-Type': type,
        'X-Content-Type-Options': 'nosniff',
      })
      response.end(body)
    } catch {
      response.writeHead(404)
      response.end('not found')
    }
  })
}

const createEvidenceManifest = async (qualification: QualificationReceipt) => {
  const requiredPaths = [
    'static/tests.json',
    'static/assets.json',
    'static/unknown-frame.json',
    'static/determinism.json',
    'static/boundary-matrix.json',
    'static/csp.json',
    'browser/qualification.json',
    'browser/fail-closed.json',
    'browser/csp-evidence.json',
    'browser/golden-journey.png',
    'browser/unknown-frame.png',
    'browser/network.json',
    'browser/storage.json',
    'browser/trace.zip',
  ]
  const p0Root = dirname(evidenceDirectory)
  const existingManifestPath = join(p0Root, 'manifest.json')
  let existingManifest: {
    asset_identity?: Record<string, unknown>
    artifacts?: Array<{ path: string; sha256: string; byte_count: number }>
  } = {}
  try {
    existingManifest = JSON.parse(await readFile(existingManifestPath, 'utf8'))
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error
  }
  const regeneratedArtifacts: P0EvidenceArtifact[] = []
  for (const path of requiredPaths) {
    const absolutePath = join(p0Root, path)
    const body = await readFile(absolutePath)
    const artifact: P0EvidenceArtifact = {
      path: `artifacts/verification/p0/${path}`,
      sha256: sha256(body),
      byte_count: body.byteLength,
    }
    regeneratedArtifacts.push(artifact)
  }
  const artifacts = mergeP0EvidenceArtifacts(existingManifest.artifacts ?? [], regeneratedArtifacts)
  await writeJson(join(p0Root, 'manifest.json'), {
    schema_version: 'canlab.p0-evidence-manifest.v1',
    status: 'candidate-verified',
    subject: {
      target_commit: qualification.target_commit,
      target_tree: qualification.target_tree,
    },
    asset_identity: existingManifest.asset_identity ?? {
      dbc_sha256: 'd5e6ab74ba4fccb17493cdfae79ae115e0b9b64c3153033531a3d3c74a1d23f7',
      vectors_sha256: '9ca0fb7a52ed9307337b23b6bc7bf5556e50ad6cc83f637ffeffed3c8d3436b4',
      log_sha256: '31e49897877e494e147cac0564d2a4f9c09d25ecb5c1fc6cf3d3603e3edc1110',
    },
    browser_qualification: {
      version: qualification.browser_version,
      executable_sha256: qualification.executable_sha256,
      image_digest: qualification.image_digest,
    },
    artifacts,
  })
}

test('closes the P0 browser journey with falsifiable offline evidence', async ({
  browser,
  context,
  page,
}, testInfo) => {
  await mkdir(evidenceDirectory, { recursive: true })
  const qualification = JSON.parse(
    await readFile(qualificationPath, 'utf8'),
  ) as QualificationReceipt
  expect(qualification).toMatchObject({
    schema_version: 'canlab.chromium-qualification.v1',
    status: 'qualified',
    channel: 'stable',
    platform: 'linux64',
    image_ref: 'canlab-p0-chromium:qualified',
  })
  expect(qualification.target_commit).toMatch(/^[0-9a-f]{40}$/)
  expect(qualification.target_tree).toMatch(/^[0-9a-f]{40}$/)
  expect(qualification.image_digest).toMatch(/^sha256:[0-9a-f]{64}$/)
  expect(qualification.qualification_snapshot.source_sha256).toMatch(/^[0-9a-f]{64}$/)
  expect(qualification.qualification_snapshot.source_url).toMatch(/^https:\/\//)
  expect(qualification.qualification_snapshot.download_url).toMatch(/^https:\/\//)
  expect(browser.version()).toBe(qualification.browser_version)
  expect(
    sha256(await readFile(qualification.executable_path)),
  ).toBe(qualification.executable_sha256)
  const targetMarker = '/opt/canlab/target-commit'
  try {
    expect((await readFile(targetMarker, 'utf8')).trim()).toBe(
      qualification.target_commit,
    )
  } catch (error) {
    if (process.env.P0_QUALIFICATION_RECEIPT !== undefined) throw error
  }

  const requestLog: Array<{
    method: string
    resourceType: string
    url: string
  }> = []
  const routeObservations: string[] = []
  page.on('request', (request) => {
    requestLog.push({
      method: request.method(),
      resourceType: request.resourceType(),
      url: request.url(),
    })
  })
  await page.route('**/*', async (route) => {
    routeObservations.push(route.request().url())
    await route.continue()
  })

  let sentinelArrivals = 0
  const sentinel = await listen((_request, response) => {
    sentinelArrivals += 1
    response.writeHead(204)
    response.end()
  })
  let tampered: Awaited<ReturnType<typeof startTamperedPreview>> | undefined
  const tracePath = join(evidenceDirectory, 'trace.zip')
  await context.tracing.start({ screenshots: true, snapshots: true, sources: true })
  try {
    const navigation = await page.goto('/')
    expect(navigation?.status()).toBe(200)
    expect(navigation?.headers()['content-security-policy']).toBe(expectedCsp)
    await expect(page.getByRole('heading', { name: 'CAN Protocol Lab' })).toBeVisible()
    await expect(page.getByText('Offline fixture')).toBeVisible()

    const provenance = page.getByRole('region', { name: 'DBC asset provenance' })
    await expect(provenance).toContainText('project-authored synthetic fixture')
    await expect(provenance).toContainText('v1.0.0')
    await expect(provenance).toContainText('CC0-1.0')
    await expect(provenance).toContainText(
      'd5e6ab74ba4fccb17493cdfae79ae115e0b9b64c3153033531a3d3c74a1d23f7',
    )

    await page.evaluate(() => {
      const state = window as typeof window & {
        __canlabCspViolations?: Array<Record<string, string>>
      }
      state.__canlabCspViolations = []
      document.addEventListener('securitypolicyviolation', (event) => {
        state.__canlabCspViolations?.push({
          blockedURI: event.blockedURI,
          disposition: event.disposition,
          effectiveDirective: event.effectiveDirective,
          originalPolicy: event.originalPolicy,
        })
      })
    })
    const probeResult = await page.evaluate(async (url) => {
      try {
        await fetch(url, { cache: 'no-store' })
        return 'unexpectedly-reached'
      } catch (error) {
        return error instanceof Error ? error.name : String(error)
      }
    }, `${sentinel.origin}/forbidden-connect`)
    await expect.poll(() => page.evaluate(() => {
      const state = window as typeof window & {
        __canlabCspViolations?: Array<Record<string, string>>
      }
      return state.__canlabCspViolations?.length ?? 0
    })).toBeGreaterThan(0)
    const violations = await page.evaluate(() => {
      const state = window as typeof window & {
        __canlabCspViolations?: Array<Record<string, string>>
      }
      return state.__canlabCspViolations ?? []
    })
    expect(probeResult).not.toBe('unexpectedly-reached')
    expect(sentinelArrivals).toBe(0)
    expect(violations).toEqual([
      expect.objectContaining({
        disposition: 'enforce',
        effectiveDirective: 'connect-src',
      }),
    ])
    await writeJson(join(evidenceDirectory, 'csp-evidence.json'), {
      schema_version: 'canlab.browser-csp-evidence.v1',
      status: 'passed',
      policy_version: cspPolicy.policy_version,
      response_header: navigation?.headers()['content-security-policy'],
      forbidden_origin: sentinel.origin,
      probe_result: probeResult,
      sentinel_arrivals: sentinelArrivals,
      violations,
      route_behavior: 'observe-and-continue',
    })

    const search = page.getByRole('searchbox', { name: 'Search DBC' })
    await search.click({ position: { x: 12, y: 10 } })
    await page.keyboard.type('EngineRpm')
    const engineRpm = page.getByRole('button', { name: 'EngineRpm' })
    await expect(engineRpm).toBeVisible()
    await engineRpm.click({ position: { x: 10, y: 10 } })
    const layout = page.getByLabel('64-bit layout for EngineRpm')
    await expect(layout.locator('[data-bit]')).toHaveCount(64)
    await expect(layout.locator('[data-active="true"]')).toHaveCount(16)

    await page.getByRole('button', { name: 'Step' }).click()
    await expect(page.getByText('3 frames · position 3/195')).toBeVisible()
    await page.getByRole('button', { name: 'Frame seq 0' }).click()
    const trace = page.getByRole('region', { name: 'Signal trace' })
    await expect(trace).toContainText(
      '31e49897877e494e147cac0564d2a4f9c09d25ecb5c1fc6cf3d3603e3edc1110/d5e6ab74ba4fccb17493cdfae79ae115e0b9b64c3153033531a3d3c74a1d23f7/0/0x100/EngineRpm',
    )
    await expect(trace).toContainText('raw bytes 600C000000280000')
    await expect(trace).toContainText('raw integer 3168')
    await expect(trace).toContainText('3168 × 0.25 + 0 = 792')
    await expect(trace).toContainText('final value 792 rpm')

    const dashboard = page.getByRole('region', { name: 'Vehicle dashboard' })
    await page.getByLabel('Seek time (µs)').fill('2600000')
    await page.getByRole('button', { name: 'Seek' }).click()
    await expect(page.getByText('Replay time 2600000 µs')).toBeVisible()
    await expect(dashboard.getByTestId('health-0x100')).toContainText('missing 1')

    await page.getByLabel('Seek time (µs)').fill('7500000')
    await page.getByRole('button', { name: 'Seek' }).click()
    const unknown = page.getByRole('region', { name: 'Signal trace' })
    for (const value of [
      'Unknown frame 0x555',
      'frame seq 121',
      '7500000 µs',
      'standard · isExtended false',
      'DLC8',
      'raw bytes DEADBEEF01020304',
      'No standard DBC message for 0x555',
    ]) await expect(unknown).toContainText(value)
    await expect(unknown.locator('[data-signal-chain]')).toHaveCount(0)
    await unknown.screenshot({ path: join(evidenceDirectory, 'unknown-frame.png') })

    const beforeRefresh = await storageSnapshot(context, page)
    expectEmptyStorage(beforeRefresh)
    await page.reload()
    await expect(page.getByRole('heading', { name: 'CAN Protocol Lab' })).toBeVisible()
    const afterRefresh = await storageSnapshot(context, page)
    expectEmptyStorage(afterRefresh)
    await writeJson(join(evidenceDirectory, 'storage.json'), {
      schema_version: 'canlab.zero-persistence-evidence.v1',
      status: 'passed',
      surfaces: [
        'cookies',
        'service-worker-registrations',
        'localStorage',
        'sessionStorage',
        'IndexedDB',
        'CacheStorage',
      ],
      before_refresh: beforeRefresh,
      after_refresh: afterRefresh,
    })

    tampered = await startTamperedPreview()
    const failClosedPage = await context.newPage()
    const failClosedResponse = await failClosedPage.goto(tampered.origin)
    const alert = failClosedPage.getByRole('alert')
    await expect(alert).toContainText('Unable to load the bundled CAN Lab assets')
    await expect(alert).toContainText('SHA-256 mismatch')
    const failClosedText = await alert.innerText()
    await writeJson(join(evidenceDirectory, 'fail-closed.json'), {
      schema_version: 'canlab.browser-fail-closed-evidence.v1',
      status: 'passed',
      mutation: 'DBC response bytes appended with one ASCII space',
      response_csp: failClosedResponse?.headers()['content-security-policy'],
      observed_alert: failClosedText,
      workspace_rendered: await failClosedPage
        .getByRole('heading', { name: 'CAN Protocol Lab' })
        .isVisible()
        .catch(() => false),
    })
    await failClosedPage.close()

    const nonLoopbackRequests = requestLog
      .map(({ url }) => url)
      .filter((url) => !isLoopback(url))
    expect(nonLoopbackRequests).toEqual([])
    expect(routeObservations.every((url) => isLoopback(url))).toBe(true)
    await writeJson(join(evidenceDirectory, 'network.json'), {
      schema_version: 'canlab.network-evidence.v1',
      status: 'passed',
      policy: 'loopback-only',
      requests: requestLog,
      non_loopback_requests: nonLoopbackRequests,
      route_observations: routeObservations,
      route_behavior: 'observe-and-continue',
      forbidden_probe_sentinel_arrivals: sentinelArrivals,
    })
    await page.screenshot({
      path: join(evidenceDirectory, 'golden-journey.png'),
      fullPage: false,
    })
  } finally {
    await context.tracing.stop({ path: tracePath })
    if (tampered !== undefined) await closeServer(tampered.server)
    await closeServer(sentinel.server)
  }

  await createEvidenceManifest(qualification)
  for (const name of ['network.json', 'storage.json', 'csp-evidence.json']) {
    await testInfo.attach(name, {
      body: await readFile(join(evidenceDirectory, name)),
      contentType: 'application/json',
    })
  }
})
