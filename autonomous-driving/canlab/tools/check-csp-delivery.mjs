#!/usr/bin/env node

import { createHash } from 'node:crypto'
import { spawn } from 'node:child_process'
import { mkdir, readFile, rename, writeFile } from 'node:fs/promises'
import { dirname, relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const projectRoot = fileURLToPath(new URL('..', import.meta.url))

const parseArguments = (values) => {
  const options = { policy: undefined, server: undefined, output: undefined }
  for (let index = 0; index < values.length; index += 1) {
    const name = values[index]
    if (!['--policy', '--server', '--output'].includes(name)) {
      throw new Error(`Unknown argument ${name}`)
    }
    const value = values[index + 1]
    if (value === undefined || value.startsWith('--')) {
      throw new Error(`${name} requires a value`)
    }
    options[name.slice(2)] = value
    index += 1
  }
  for (const name of ['policy', 'server', 'output']) {
    if (options[name] === undefined) throw new Error(`--${name} is required`)
  }
  return options
}

const serializeCsp = (directives) => Object.entries(directives)
  .map(([name, values]) => `${name} ${values.join(' ')}`)
  .join('; ')

const writeJsonAtomic = async (path, value) => {
  await mkdir(dirname(path), { recursive: true })
  const temporaryPath = `${path}.tmp-${process.pid}`
  await writeFile(temporaryPath, `${JSON.stringify(value, null, 2)}\n`, 'utf8')
  await rename(temporaryPath, path)
}

const waitForReady = (child) => new Promise((resolveReady, rejectReady) => {
  let stdout = ''
  let stderr = ''
  const timeout = setTimeout(() => {
    rejectReady(new Error(`preview readiness timed out: ${stderr || stdout}`))
  }, 15_000)
  child.stderr.on('data', (chunk) => { stderr += chunk.toString() })
  child.stdout.on('data', (chunk) => {
    stdout += chunk.toString()
    for (const line of stdout.split('\n')) {
      if (!line.startsWith('CANLAB_PREVIEW_READY ')) continue
      clearTimeout(timeout)
      resolveReady(JSON.parse(line.slice('CANLAB_PREVIEW_READY '.length)))
      return
    }
  })
  child.once('exit', (code) => {
    clearTimeout(timeout)
    rejectReady(new Error(`preview exited ${String(code)}: ${stderr || stdout}`))
  })
})

const options = parseArguments(process.argv.slice(2))
const policyPath = resolve(projectRoot, options.policy)
const serverPath = resolve(projectRoot, options.server)
const outputPath = resolve(projectRoot, options.output)
const policySource = await readFile(policyPath, 'utf8')
const policy = JSON.parse(policySource)
if (
  policy.schema_version !== 'canlab.csp-policy.v1' ||
  policy.header_name !== 'Content-Security-Policy' ||
  policy.delivery?.transport !== 'http-response-header' ||
  policy.delivery?.meta_policy_allowed !== false
) {
  throw new Error('CSP policy does not require response-header-only delivery')
}
const expectedHeader = serializeCsp(policy.directives)
const child = spawn(
  process.execPath,
  [serverPath, '--host', '127.0.0.1', '--port', '0', '--strictPort'],
  { cwd: projectRoot, env: { ...process.env, P0_CSP_POLICY: policyPath } },
)

let evidence
try {
  const ready = await waitForReady(child)
  const routes = ['/', '/assets/canlab-demo-v1.0.0.metadata.json']
  const responses = []
  for (const path of routes) {
    const response = await fetch(`${ready.origin}${path}`, { cache: 'no-store' })
    const body = await response.text()
    responses.push({
      path,
      status: response.status,
      csp: response.headers.get(policy.header_name),
      cache_control: response.headers.get('cache-control'),
      body_sha256: createHash('sha256').update(body).digest('hex'),
      contains_meta_csp: /http-equiv=["']Content-Security-Policy["']/i.test(body),
    })
  }
  const failures = []
  for (const response of responses) {
    if (response.status !== 200) failures.push(`${response.path} returned ${response.status}`)
    if (response.csp !== expectedHeader) failures.push(`${response.path} CSP differs from policy`)
    if (response.contains_meta_csp) failures.push(`${response.path} contains a meta CSP`)
  }
  const staticHeaders = await readFile(resolve(projectRoot, 'public/_headers'), 'utf8')
  const expectedStaticHeaders = `/*\n  Content-Security-Policy: ${expectedHeader}\n`
  if (staticHeaders !== expectedStaticHeaders) {
    failures.push('public/_headers differs from the versioned policy')
  }
  evidence = {
    schema_version: 'canlab.csp-delivery-evidence.v1',
    status: failures.length === 0 ? 'passed' : 'failed',
    policy: {
      file: relative(projectRoot, policyPath),
      version: policy.policy_version,
      sha256: createHash('sha256').update(policySource).digest('hex'),
      header_name: policy.header_name,
      header_value: expectedHeader,
    },
    preview_origin: ready.origin,
    responses,
    failures,
  }
} finally {
  child.kill('SIGTERM')
  await new Promise((resolveExit) => {
    if (child.exitCode !== null) resolveExit()
    else child.once('exit', resolveExit)
  })
}

await writeJsonAtomic(outputPath, evidence)
if (evidence.status !== 'passed') {
  for (const failure of evidence.failures) console.error(`- ${failure}`)
  process.exitCode = 1
} else {
  console.log(
    `CSP delivery passed: policy ${evidence.policy.version} matched ${evidence.responses.length} HTTP responses.`,
  )
}
