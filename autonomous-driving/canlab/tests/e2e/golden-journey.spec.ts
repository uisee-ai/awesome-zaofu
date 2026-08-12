import { expect, test } from '@playwright/test'

const isLoopback = (value: string): boolean => {
  const url = new URL(value)
  return (
    (url.protocol === 'http:' || url.protocol === 'https:') &&
    ['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname)
  )
}

test('runs the complete offline CAN Lab golden journey in Chromium', async ({
  page,
}, testInfo) => {
  const requestLog: Array<{
    readonly method: string
    readonly resourceType: string
    readonly url: string
  }> = []
  const nonLoopbackRequests: string[] = []

  page.on('request', (request) => {
    requestLog.push({
      method: request.method(),
      resourceType: request.resourceType(),
      url: request.url(),
    })
  })
  await page.route('**/*', async (route) => {
    const url = route.request().url()
    if (!isLoopback(url)) {
      nonLoopbackRequests.push(url)
    }
    await route.continue()
  })

  try {
    const navigation = await page.goto('/')
    await expect(
      page.getByRole('heading', { name: 'CAN Protocol Lab' }),
    ).toBeVisible()
    await expect(page.getByText('Offline fixture')).toBeVisible()
    const provenance = page.getByRole('region', { name: 'DBC asset provenance' })
    await expect(provenance).toContainText('project-authored synthetic fixture')
    await expect(provenance).toContainText('v1.0.0')
    await expect(provenance).toContainText('CC0-1.0')
    await expect(provenance).toContainText(
      'd5e6ab74ba4fccb17493cdfae79ae115e0b9b64c3153033531a3d3c74a1d23f7',
    )

    const policy = navigation?.headers()['content-security-policy']
    expect(policy).toContain("connect-src 'self'")
    expect(policy).toContain("object-src 'none'")
    expect(
      await page.evaluate(async () => {
        try {
          await fetch('https://example.invalid/can-lab-csp-probe')
          return 'unexpectedly allowed'
        } catch {
          return 'blocked'
        }
      }),
    ).toBe('blocked')

    const search = page.getByRole('searchbox', { name: 'Search DBC' })
    await search.fill('EngineRpm')
    await expect(page.getByRole('button', { name: 'EngineRpm' })).toBeVisible()
    await page.getByRole('button', { name: 'EngineRpm' }).click()

    const layout = page.getByLabel('64-bit layout for EngineRpm')
    await expect(layout.locator('[data-bit]')).toHaveCount(64)
    await expect(layout.locator('[data-active="true"]')).toHaveCount(16)
    await expect(page.getByText('start bit 0', { exact: true })).toBeVisible()
    await expect(page.getByText('length 16', { exact: true })).toBeVisible()

    await page.getByRole('button', { name: 'Step' }).click()
    await expect(page.getByText('3 frames · position 3/195')).toBeVisible()
    await expect(page.getByText('Replay time 0 µs')).toBeVisible()
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
    await expect(dashboard.getByTestId('gauge-EngineRpm')).toContainText('792 rpm')
    await expect(dashboard.getByTestId('gauge-VehicleSpeed')).toContainText('0 km/h')
    await expect(dashboard.getByTestId('trend-panel')).toHaveCount(6)

    await page.getByLabel('Replay speed').selectOption('2')
    await page.getByLabel('Loop replay').check()
    await page.getByRole('button', { name: 'Play' }).click()
    await expect(page.getByText('Status playing')).toBeVisible()
    await page.getByRole('button', { name: 'Pause' }).click()
    await expect(page.getByText('Status paused')).toBeVisible()

    await page.getByLabel('Seek time (µs)').fill('2600000')
    await page.getByRole('button', { name: 'Seek' }).click()
    await expect(page.getByText('Replay time 2600000 µs')).toBeVisible()
    await expect(dashboard.getByTestId('health-0x100')).toContainText('missing 1')
    await expect(dashboard.getByTestId('trend-VehicleSpeed')).toContainText(
      '2600000 µs',
    )
    await page.getByLabel('Loop replay').uncheck()

    const storageEvidence = await page.evaluate(async () => ({
      localStorageEntries: localStorage.length,
      sessionStorageEntries: sessionStorage.length,
      indexedDatabases: (await indexedDB.databases()).length,
      cacheEntries: (await caches.keys()).length,
      serviceWorkerRegistrations: (await navigator.serviceWorker.getRegistrations()).length,
    }))
    const cookieCount = (await page.context().cookies()).length
    expect({ ...storageEvidence, cookieCount }).toEqual({
      localStorageEntries: 0,
      sessionStorageEntries: 0,
      indexedDatabases: 0,
      cacheEntries: 0,
      serviceWorkerRegistrations: 0,
      cookieCount: 0,
    })
    await testInfo.attach('storage-evidence.json', {
      body: JSON.stringify(storageEvidence, null, 2),
      contentType: 'application/json',
    })

    expect(nonLoopbackRequests).toEqual([])
  } finally {
    await testInfo.attach('network-request-log.json', {
      body: JSON.stringify(
        { nonLoopbackRequests, requests: requestLog },
        null,
        2,
      ),
      contentType: 'application/json',
    })
  }
})
