import { existsSync } from 'node:fs'
import { mkdir, writeFile } from 'node:fs/promises'
import path from 'node:path'
import playwrightTest from '../../web/node_modules/@playwright/test/index.js'

const { chromium } = playwrightTest
const releaseUrl = process.env.SCENARIOFORGE_RELEASE_URL
const outputDirectory = process.env.SCENARIOFORGE_BROWSER_OUTPUT
const resultPath = process.env.SCENARIOFORGE_BROWSER_RESULT
const capability = process.env.SCENARIOFORGE_CAPABILITY_TOKEN
const csrf = process.env.SCENARIOFORGE_CSRF_TOKEN

if (!releaseUrl || !outputDirectory || !resultPath || !capability || !csrf) {
  throw new Error('production browser environment is incomplete')
}

const userBrowserLibraries = process.env.HOME
  ? path.join(process.env.HOME, '.cache/scenarioforge/playwright-libs/usr/lib/x86_64-linux-gnu')
  : ''
if (userBrowserLibraries && existsSync(userBrowserLibraries)) {
  process.env.LD_LIBRARY_PATH = [userBrowserLibraries, process.env.LD_LIBRARY_PATH]
    .filter(Boolean)
    .join(':')
}

await mkdir(outputDirectory, { recursive: true })
const tracePath = path.join(outputDirectory, 'chromium-trace.zip')
const deniedNetwork = []
const browser = await chromium.launch({ headless: true })
const browserVersion = browser.version()
const context = await browser.newContext()
await context.route('**/*', async (route) => {
  const url = new URL(route.request().url())
  if (
    !['http:', 'https:'].includes(url.protocol)
    || url.hostname === '127.0.0.1'
    || url.hostname === 'localhost'
    || url.hostname === '[::1]'
  ) {
    await route.continue()
    return
  }
  deniedNetwork.push(url.origin)
  await route.abort('blockedbyclient')
})
await context.tracing.start({ screenshots: true, snapshots: true, sources: true })

const page = await context.newPage()
let result
try {
  await page.goto(releaseUrl, { waitUntil: 'networkidle' })
  await page.getByLabel('API endpoint').fill(releaseUrl)
  await page.getByLabel('Capability token').fill(capability)
  await page.getByLabel('CSRF token').fill(csrf)

  const editor = page.getByLabel('Scenario JSON')
  const original = JSON.parse(await editor.inputValue())
  await editor.fill(JSON.stringify({ ...original, map: { ...original.map, lane_count: 99 } }, null, 2))
  await page.getByRole('button', { name: 'Validate' }).click()
  const diagnostic = page.locator('.diagnostics li').first()
  await diagnostic.waitFor({ state: 'visible' })
  const diagnosticText = (await diagnostic.textContent()) ?? ''
  if (!diagnosticText.includes('map.lane_count')) throw new Error('field error location was absent')

  const edited = { ...original, name: 'release-golden-path-edited' }
  await editor.fill(JSON.stringify(edited, null, 2))
  await page.getByRole('button', { name: 'Validate' }).click()
  await page.getByText('Scenario is valid and canonical').waitFor()
  const canonicalPreview = page.getByRole('heading', { name: 'Canonical preview' }).locator('..').locator('pre')
  if (!((await canonicalPreview.textContent()) ?? '').includes('release-golden-path-edited')) {
    throw new Error('canonical preview did not contain the edit')
  }

  await page.getByRole('button', { name: 'Export JSON' }).click()
  await page.getByText('Canonical JSON export ready').waitFor()
  const exportPreview = page.getByRole('heading', { name: 'Export' }).locator('..').locator('pre')
  const jsonExport = (await exportPreview.textContent()) ?? ''
  if (!jsonExport.includes('release-golden-path-edited')) throw new Error('JSON export failed')

  await page.getByRole('button', { name: 'Export YAML' }).click()
  await page.getByText('Canonical YAML export ready').waitFor()
  const yamlExport = (await exportPreview.textContent()) ?? ''
  if (!yamlExport.includes('release-golden-path-edited')) throw new Error('YAML export failed')

  await page.getByRole('button', { name: 'Run real case' }).click()
  await page.getByText(/Run completed; sealed bundle/).waitFor({ timeout: 180_000 })
  const bundleId = await page.getByLabel('Bundle ID').inputValue()
  if (!bundleId.startsWith('run-')) throw new Error('real run did not publish a bundle id')

  await page.getByRole('button', { name: 'Load sealed replay' }).click()
  await page.getByTestId('replay-status').getByText('Sealed replay ready').waitFor({ timeout: 30_000 })
  const metrics = (await page.getByTestId('metrics').textContent()) ?? ''
  if (!metrics.includes('total steps') || !metrics.includes('metadrive-simulator@0.4.3')) {
    throw new Error('run metrics or real-provider provenance was absent')
  }
  const initialTick = (await page.getByTestId('tick').textContent()) ?? ''
  await page.getByRole('button', { name: 'Step forward' }).click()
  const nextTick = (await page.getByTestId('tick').textContent()) ?? ''
  if (initialTick === nextTick) throw new Error('exact replay did not advance')

  result = {
    status: 'passed',
    chromium_version: browserVersion,
    bundle_id: bundleId,
    metrics,
    external_network_attempts: deniedNetwork,
    checks: {
      import: 'passed',
      edit: 'passed',
      field_error_location: 'passed',
      canonical_preview: 'passed',
      real_run: 'passed',
      metrics: 'passed',
      exact_replay: 'passed',
      json_export: 'passed',
      yaml_export: 'passed',
    },
  }
} finally {
  await context.tracing.stop({ path: tracePath })
  await context.close()
  await browser.close()
}

await writeFile(resultPath, `${JSON.stringify(result)}\n`, { encoding: 'utf8', flag: 'wx' })
