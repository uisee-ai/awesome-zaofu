#!/usr/bin/env node

import { createHash } from 'node:crypto'
import { mkdir, readFile, readdir, rename, writeFile } from 'node:fs/promises'
import { dirname, extname, join, relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const projectRoot = fileURLToPath(new URL('..', import.meta.url))
const sourceExtensions = new Set(['.ts', '.tsx', '.js', '.jsx', '.html'])
const requiredFixtureRules = [
  'webhid',
  'webbluetooth',
  'websocket',
  'eventsource',
  'webrtc',
  'serviceworker',
  'hardware_access',
  'can_transmit',
]

const parseArguments = (values) => {
  const options = {
    policy: 'config/passive-boundary-policy.json',
    fixtures: 'tests/fixtures/passive-boundary',
    output: undefined,
  }
  for (let index = 0; index < values.length; index += 1) {
    const name = values[index]
    if (!['--policy', '--fixtures', '--output'].includes(name)) {
      throw new Error(`Unknown argument ${name}`)
    }
    const value = values[index + 1]
    if (value === undefined || value.startsWith('--')) {
      throw new Error(`${name} requires a value`)
    }
    options[name.slice(2)] = value
    index += 1
  }
  return options
}

const readJson = async (path, label) => {
  let value
  try {
    value = JSON.parse(await readFile(path, 'utf8'))
  } catch (error) {
    throw new Error(`${label} is not valid JSON: ${error.message}`, {
      cause: error,
    })
  }
  return value
}

const collectSourceFiles = async (path) => {
  const entries = await readdir(path, { withFileTypes: true })
  const files = []
  for (const entry of entries) {
    const child = join(path, entry.name)
    if (entry.isDirectory()) {
      files.push(...(await collectSourceFiles(child)))
    } else if (entry.isFile() && sourceExtensions.has(extname(entry.name))) {
      files.push(child)
    }
  }
  return files
}

const resolveProductionSources = async (entries) => {
  const files = []
  for (const entry of entries) {
    const path = resolve(projectRoot, entry)
    const stats = await import('node:fs/promises').then(({ stat }) => stat(path))
    if (stats.isDirectory()) files.push(...(await collectSourceFiles(path)))
    else if (stats.isFile()) files.push(path)
  }
  return [...new Set(files)].sort()
}

const compileRules = (policy) => policy.forbidden_rules.map((rule) => ({
  ...rule,
  expressions: rule.patterns.map((pattern) => new RegExp(pattern, 'i')),
}))

const matchingRuleIds = (content, rules) => rules
  .filter((rule) => rule.expressions.some((expression) => expression.test(content)))
  .map((rule) => rule.id)

const absoluteUrls = (content) =>
  content.match(/(?:https?|wss?):\/\/[^\s"'`<>)]*/gi) ?? []

const isAllowedLoopbackUrl = (value, allowedHosts) => {
  try {
    const url = new URL(value)
    return (
      (url.protocol === 'http:' || url.protocol === 'https:') &&
      allowedHosts.includes(url.hostname === '::1' ? '[::1]' : url.hostname)
    )
  } catch {
    return false
  }
}

const writeJsonAtomic = async (path, value) => {
  await mkdir(dirname(path), { recursive: true })
  const temporaryPath = `${path}.tmp-${process.pid}`
  await writeFile(temporaryPath, `${JSON.stringify(value, null, 2)}\n`, 'utf8')
  await rename(temporaryPath, path)
}

const options = parseArguments(process.argv.slice(2))
const policyPath = resolve(projectRoot, options.policy)
const fixturesPath = resolve(projectRoot, options.fixtures)
const policySource = await readFile(policyPath, 'utf8')
const policy = JSON.parse(policySource)

if (
  policy.schema_version !== 'canlab.passive-boundary-policy.v1' ||
  typeof policy.policy_version !== 'string' ||
  !Array.isArray(policy.production_sources) ||
  !Array.isArray(policy.forbidden_rules) ||
  !Array.isArray(policy.allowed_loopback_hosts) ||
  !Array.isArray(policy.allowed_browser_apis) ||
  !Array.isArray(policy.allowed_url_scopes) ||
  !Array.isArray(policy.persistence_surfaces) ||
  !Array.isArray(policy.blocked_dependency_patterns)
) {
  throw new Error('Passive boundary policy does not match schema v1')
}

const rules = compileRules(policy)
const sourceFiles = await resolveProductionSources(policy.production_sources)
const productionViolations = []

for (const path of sourceFiles) {
  const content = await readFile(path, 'utf8')
  for (const ruleId of matchingRuleIds(content, rules)) {
    productionViolations.push({
      file: relative(projectRoot, path),
      rule_id: ruleId,
      reason: rules.find((rule) => rule.id === ruleId).label,
    })
  }
  for (const url of absoluteUrls(content)) {
    if (!isAllowedLoopbackUrl(url, policy.allowed_loopback_hosts)) {
      productionViolations.push({
        file: relative(projectRoot, path),
        rule_id: 'forbidden_url',
        reason: `URL is outside the versioned loopback allowlist: ${url}`,
      })
    }
  }
}

const packageManifest = await readJson(join(projectRoot, 'package.json'), 'package.json')
const packageLock = await readJson(join(projectRoot, 'package-lock.json'), 'package-lock.json')
const dependencyPatterns = policy.blocked_dependency_patterns.map(
  (pattern) => new RegExp(pattern, 'i'),
)
const dependencies = [
  ...Object.keys(packageManifest.dependencies ?? {}),
  ...Object.keys(packageManifest.devDependencies ?? {}),
  ...Object.keys(packageLock.packages ?? {}).map((path) =>
    path.replace(/^node_modules\//, ''),
  ),
]
for (const dependency of [...new Set(dependencies)].filter(Boolean).sort()) {
  if (dependencyPatterns.some((pattern) => pattern.test(dependency))) {
    productionViolations.push({
      file: dependency in (packageManifest.dependencies ?? {}) ||
        dependency in (packageManifest.devDependencies ?? {})
        ? 'package.json'
        : 'package-lock.json',
      rule_id: 'blocked_dependency',
      reason: `blocked dependency ${dependency}`,
    })
  }
}

const fixtureManifest = await readJson(
  join(fixturesPath, 'manifest.json'),
  'passive boundary fixture manifest',
)
if (
  fixtureManifest.schema_version !== 'canlab.passive-boundary-fixtures.v1' ||
  !Array.isArray(fixtureManifest.fixtures)
) {
  throw new Error('Passive boundary fixture manifest does not match schema v1')
}

const fixtureResults = []
const fixtureFailures = []
for (const fixture of fixtureManifest.fixtures) {
  if (
    typeof fixture?.file !== 'string' ||
    typeof fixture?.expected_rule !== 'string'
  ) {
    fixtureFailures.push('fixture manifest contains an invalid entry')
    continue
  }
  const content = await readFile(join(fixturesPath, fixture.file), 'utf8')
  const detectedRuleIds = matchingRuleIds(content, rules)
  const rejected = detectedRuleIds.includes(fixture.expected_rule)
  fixtureResults.push({
    file: fixture.file,
    expected_rule: fixture.expected_rule,
    detected_rule_ids: detectedRuleIds,
    rejected,
  })
  if (!rejected) {
    fixtureFailures.push(
      `${fixture.file} was not rejected by ${fixture.expected_rule}`,
    )
  }
}

const actualFixtureRules = fixtureManifest.fixtures
  .map((fixture) => fixture.expected_rule)
  .sort()
const expectedFixtureRules = [...requiredFixtureRules].sort()
if (JSON.stringify(actualFixtureRules) !== JSON.stringify(expectedFixtureRules)) {
  fixtureFailures.push(
    `fixture coverage must be exactly ${expectedFixtureRules.join(', ')}`,
  )
}
if (policy.persistence_surfaces.length !== 6) {
  fixtureFailures.push('policy must enumerate all six persistence surfaces')
}

const passed = productionViolations.length === 0 && fixtureFailures.length === 0
const evidence = {
  schema_version: 'canlab.passive-boundary-evidence.v1',
  status: passed ? 'passed' : 'failed',
  policy: {
    file: relative(projectRoot, policyPath),
    version: policy.policy_version,
    sha256: createHash('sha256').update(policySource).digest('hex'),
  },
  allowlist: {
    browser_apis: policy.allowed_browser_apis,
    url_scopes: policy.allowed_url_scopes,
    loopback_hosts: policy.allowed_loopback_hosts,
  },
  denylist_rule_ids: rules.map((rule) => rule.id),
  persistence_surfaces: policy.persistence_surfaces,
  checked_production_files: sourceFiles.map((path) => relative(projectRoot, path)),
  production_violations: productionViolations,
  negative_fixtures: fixtureResults,
  fixture_failures: fixtureFailures,
}

if (options.output !== undefined) {
  await writeJsonAtomic(resolve(projectRoot, options.output), evidence)
}

if (!passed) {
  console.error('Passive-only boundary failed:')
  for (const violation of productionViolations) {
    console.error(`- ${violation.file}: ${violation.reason}`)
  }
  for (const failure of fixtureFailures) console.error(`- ${failure}`)
  process.exitCode = 1
} else {
  console.log(
    `Passive-only boundary passed: ${sourceFiles.length} production files, ${fixtureResults.length} negative fixtures, and six persistence surfaces checked.`,
  )
}
