import { createHash } from 'node:crypto'
import { spawn, type ChildProcess } from 'node:child_process'
import { existsSync } from 'node:fs'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import path from 'node:path'
import playwrightTest from '../../web/node_modules/@playwright/test/index.js'

const { expect, test } = playwrightTest

const projectRoot = path.resolve(import.meta.dirname, '../..')
const webRoot = path.join(projectRoot, 'web')
const capability = 'e2e-capability-9e4236bd'
const csrf = 'e2e-csrf-c0fdbad4'
const processes: ChildProcess[] = []
const deniedNetwork: string[] = []
const userBrowserLibraries = process.env.HOME
  ? path.join(process.env.HOME, '.cache/scenarioforge/playwright-libs/usr/lib/x86_64-linux-gnu')
  : ''
if (userBrowserLibraries && existsSync(userBrowserLibraries)) {
  process.env.LD_LIBRARY_PATH = [userBrowserLibraries, process.env.LD_LIBRARY_PATH]
    .filter(Boolean)
    .join(':')
}

async function waitFor(url: string): Promise<void> {
  const deadline = Date.now() + 20_000
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url)
      if (response.ok || response.status === 403) return
    } catch {
      // The server has not opened its loopback socket yet.
    }
    await new Promise((resolve) => setTimeout(resolve, 100))
  }
  throw new Error(`loopback server did not become ready: ${new URL(url).origin}`)
}

function start(command: string, args: string[], environment: NodeJS.ProcessEnv): ChildProcess {
  const child = spawn(command, args, {
    cwd: projectRoot,
    env: environment,
    stdio: 'ignore',
  })
  processes.push(child)
  return child
}

async function writeEvidence(outputDirectory: string, report: object): Promise<void> {
  const serialized = `${JSON.stringify(report, null, 2)}\n`
  const digest = createHash('sha256').update(serialized).digest('hex')
  const reportPath = path.join(outputDirectory, 'report.json')
  const digestPath = path.join(outputDirectory, 'report.sha256')
  await mkdir(outputDirectory, { recursive: true })
  try {
    const [existing, existingDigest] = await Promise.all([
      readFile(reportPath, 'utf8'),
      readFile(digestPath, 'utf8'),
    ])
    expect(existing).toBe(serialized)
    expect(existingDigest).toBe(`${digest}  report.json\n`)
  } catch (error) {
    const code = (error as NodeJS.ErrnoException).code
    if (code !== 'ENOENT') throw error
    await writeFile(reportPath, serialized, { encoding: 'utf8', flag: 'wx', mode: 0o444 })
    await writeFile(digestPath, `${digest}  report.json\n`, {
      encoding: 'utf8',
      flag: 'wx',
      mode: 0o444,
    })
  }
}

test.beforeAll(async () => {
  const environment = {
    ...process.env,
    PYTHONPATH: path.join(projectRoot, 'src'),
    SCENARIOFORGE_ALLOWED_ORIGIN: 'http://127.0.0.1:4173',
    SCENARIOFORGE_BUNDLE_ROOT: path.join(projectRoot, 'evidence/runtime/metadrive-smoke'),
    SCENARIOFORGE_CAPABILITY_TOKEN: capability,
    SCENARIOFORGE_CSRF_TOKEN: csrf,
  }
  start(
    'python',
    ['-m', 'uvicorn', 'scenarioforge.api:app', '--host', '127.0.0.1', '--port', '4174'],
    environment,
  )
  start(
    path.join(webRoot, 'node_modules/.bin/vite'),
    ['--config', path.join(webRoot, 'vite.config.ts'), '--host', '127.0.0.1', '--port', '4173', webRoot + '/src'],
    environment,
  )
  await Promise.all([
    waitFor('http://127.0.0.1:4173'),
    waitFor('http://127.0.0.1:4174/api/health'),
  ])
})

test.afterAll(async () => {
  for (const child of processes) child.kill('SIGTERM')
})

test('@exact-replay sealed real-provider bundle replays exactly with no external network', async ({
  context,
  page,
}) => {
  await context.route('**/*', async (route) => {
    const url = new URL(route.request().url())
    if (url.hostname === '127.0.0.1' || url.hostname === 'localhost') {
      await route.continue()
      return
    }
    deniedNetwork.push(url.origin)
    await route.abort('blockedbyclient')
  })

  await page.goto('/')
  await page.getByLabel('Capability token').fill(capability)
  await page.getByLabel('CSRF token').fill(csrf)
  await page.getByLabel('Bundle ID').fill('bundle')
  await page.getByRole('button', { name: 'Load sealed replay' }).click()

  await expect(page.getByTestId('replay-status')).toHaveText('Sealed replay ready')
  await expect(page.getByLabel('Case')).toHaveValue('0')
  await expect(page.getByTestId('tick')).toHaveText('0 / 20')
  await expect(page.getByTestId('position')).toHaveText('5, 3.5')
  await expect(page.getByTestId('speed')).toHaveText('0 km/h')

  await page.getByRole('button', { name: 'Step forward' }).click()
  await expect(page.getByTestId('tick')).toHaveText('1 / 20')
  await page.getByRole('button', { name: 'Step backward' }).click()
  await expect(page.getByTestId('tick')).toHaveText('0 / 20')

  await page.getByLabel('Playback rate').selectOption('2')
  await expect(page.getByLabel('Playback rate')).toHaveValue('2')
  await page.getByRole('button', { name: 'Play', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Pause', exact: true })).toBeVisible()
  await expect(page.getByTestId('tick')).not.toHaveText('0 / 20')
  await page.getByRole('button', { name: 'Pause', exact: true }).click()

  await page.getByLabel('Seek tick').fill('20')
  await expect(page.getByTestId('tick')).toHaveText('20 / 20')
  await expect(page.getByTestId('position')).toHaveText('7.8343329429626465, 3.5')
  await expect(page.getByTestId('speed')).toHaveText('10.517005062104593 km/h')
  await expect(page.getByTestId('route-progress')).toHaveText('0.0634676881231387')
  await expect(page.getByTestId('events')).toContainText('max_steps')
  await expect(page.getByTestId('metrics')).toContainText('20 total steps')
  await expect(page.getByTestId('replay-canvas')).toHaveAttribute('data-renderer', /three/)

  const frame = JSON.parse((await page.getByTestId('frame-json').getAttribute('data-frame')) ?? '{}')
  expect(frame).toEqual({
    step: 20,
    position: [7.8343329429626465, 3.5],
    heading: -5.326322183307752e-7,
    speed_km_h: 10.517005062104593,
    collision: false,
    off_road: false,
    route_progress: 0.0634676881231387,
  })
  expect(deniedNetwork).toEqual([])

  const outputDirectory = process.env.SCENARIOFORGE_E2E_OUTPUT
  if (outputDirectory) {
    await writeEvidence(path.resolve(projectRoot, outputDirectory), {
      schema_version: 'scenarioforge.browser-exact-replay-evidence.v1',
      acceptance_criterion: 'AC-07',
      bundle_id: 'bundle',
      provider: 'metadrive-simulator@0.4.3',
      runner_state: 'stopped',
      metadrive_calls: 0,
      external_network_attempts: deniedNetwork,
      controls_verified: ['case', 'play', 'pause', 'step', 'seek', 'rate', 'events', 'metrics'],
      terminal_frame: frame,
      result: 'passed',
    })
  }
})
