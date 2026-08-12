#!/usr/bin/env node

import { createHash } from 'node:crypto'
import { execFileSync } from 'node:child_process'
import { mkdir, mkdtemp, readFile, rename, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { spawn } from 'node:child_process'

const projectRoot = fileURLToPath(new URL('..', import.meta.url))
const sourceUrl =
  'https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json'
const imageRef = 'canlab-p0-chromium:qualified'
const executablePath = '/opt/chrome/chrome-linux64/chrome'

const parseArguments = (values) => {
  const options = { channel: undefined, platform: undefined, output: undefined }
  for (let index = 0; index < values.length; index += 1) {
    const name = values[index]
    if (!['--channel', '--platform', '--output'].includes(name)) {
      throw new Error(`Unknown argument ${name}`)
    }
    const value = values[index + 1]
    if (value === undefined || value.startsWith('--')) {
      throw new Error(`${name} requires a value`)
    }
    options[name.slice(2)] = value
    index += 1
  }
  if (options.channel !== 'stable') {
    throw new Error('Only --channel stable is accepted for the P0 gate')
  }
  if (options.platform !== 'linux64') {
    throw new Error('Only --platform linux64 is accepted for the P0 gate')
  }
  if (options.output === undefined) throw new Error('--output is required')
  return options
}

const run = (command, args, { capture = false } = {}) => new Promise(
  (resolveRun, rejectRun) => {
    const child = spawn(command, args, {
      cwd: projectRoot,
      env: process.env,
      stdio: capture ? ['ignore', 'pipe', 'pipe'] : 'inherit',
    })
    let stdout = ''
    let stderr = ''
    if (capture) {
      child.stdout.on('data', (chunk) => { stdout += chunk.toString() })
      child.stderr.on('data', (chunk) => { stderr += chunk.toString() })
    }
    child.once('error', rejectRun)
    child.once('exit', (code) => {
      if (code === 0) resolveRun(stdout.trim())
      else rejectRun(new Error(
        `${command} exited ${String(code)}${stderr.length === 0 ? '' : `: ${stderr.trim()}`}`,
      ))
    })
  },
)

const downloadHttps = (url, output) => run('curl', [
  '--fail',
  '--location',
  '--proto',
  '=https',
  '--retry',
  '4',
  '--retry-all-errors',
  '--retry-delay',
  '2',
  '--connect-timeout',
  '30',
  '--max-time',
  '600',
  '--user-agent',
  'canlab-p0-chromium-qualification/1.0',
  '--output',
  output,
  url,
])

const hashFile = async (path) => {
  const hash = createHash('sha256')
  const body = await readFile(path)
  hash.update(body)
  return hash.digest('hex')
}

const gitBuffer = (...args) => execFileSync('git', args, {
  cwd: projectRoot,
  maxBuffer: 64 * 1024 * 1024,
})

const git = (...args) => gitBuffer(...args).toString('utf8').trim()

const productPatchDigest = (baseCommit, commit) => createHash('sha256').update(gitBuffer(
  'diff', '--binary', baseCommit, commit, '--', '.',
  ':(exclude)artifacts/verification/p0',
)).digest('hex')

const gitIsAncestor = (ancestor, descendant) => {
  try {
    execFileSync('git', ['merge-base', '--is-ancestor', ancestor, descendant], {
      cwd: projectRoot,
      stdio: 'ignore',
    })
    return true
  } catch (error) {
    if (error?.status === 1) return false
    throw error
  }
}

const resolveIntegratedProduct = (baseCommit, sourceCommit, integratedCommit) => {
  if (!gitIsAncestor(baseCommit, integratedCommit)) {
    throw new Error('integrated candidate is not based on expected old main')
  }
  if (git('rev-list', '--merges', `${baseCommit}..${integratedCommit}`)) {
    throw new Error('integrated candidate lineage contains merge commits')
  }
  const sourceTree = git('rev-parse', `${sourceCommit}^{tree}`)
  const sourcePatch = productPatchDigest(baseCommit, sourceCommit)
  const matches = git('rev-list', '--first-parent', `${baseCommit}..${integratedCommit}`)
    .split('\n')
    .filter(Boolean)
    .filter((commit) =>
      git('rev-parse', `${commit}^{tree}`) === sourceTree &&
      productPatchDigest(baseCommit, commit) === sourcePatch)
  if (matches.length !== 1) {
    throw new Error(`integrated product mapping is not unique: ${matches.length} matches`)
  }
  return matches[0]
}

const validateCandidateLineage = async () => {
  const currentCommit = await run('git', ['rev-parse', 'HEAD'], { capture: true })
  const candidateBody = await readFile(resolve(projectRoot, 'artifacts/verification/p0/release-candidate.json'), 'utf8')
  const candidate = JSON.parse(candidateBody)
  if (
    !/^[0-9a-f]{40}$/.test(candidate.base_commit) ||
    !/^[0-9a-f]{40}$/.test(candidate.candidate_commit) ||
    !/^[0-9a-f]{40}$/.test(candidate.candidate_tree) ||
    await run('git', ['rev-parse', `${candidate.candidate_commit}^{tree}`], { capture: true }) !== candidate.candidate_tree
  ) {
    throw new Error('release candidate identity is invalid')
  }
  if (!gitIsAncestor(candidate.base_commit, candidate.candidate_commit) || !gitIsAncestor(candidate.base_commit, currentCommit)) {
    throw new Error('candidate lineage is not based on the declared base')
  }
  if (candidate.source_commit !== undefined || candidate.source_tree !== undefined) {
    if (
      !/^[0-9a-f]{40}$/.test(candidate.source_commit) ||
      !/^[0-9a-f]{40}$/.test(candidate.source_tree) ||
      git('rev-parse', `${candidate.source_commit}^{tree}`) !== candidate.source_tree ||
      productPatchDigest(candidate.base_commit, candidate.source_commit) !==
        productPatchDigest(candidate.base_commit, candidate.candidate_commit)
    ) {
      throw new Error('product source and integrated candidate are not patch-equivalent')
    }
  }
  const integratedProductCommit = resolveIntegratedProduct(
    candidate.base_commit,
    candidate.candidate_commit,
    currentCommit,
  )
  if (currentCommit !== integratedProductCommit) {
    if (!gitIsAncestor(integratedProductCommit, currentCommit)) {
      throw new Error('evidence carrier is not based on integrated product candidate')
    }
    const changedPaths = (await run('git', ['diff', '--name-only', integratedProductCommit, currentCommit], { capture: true }))
      .split('\n').filter(Boolean)
    if (changedPaths.length === 0 || changedPaths.some((path) => !path.startsWith('artifacts/verification/p0/'))) {
      throw new Error('evidence carrier contains non-evidence changes')
    }
  }
  return { candidate, currentCommit, integratedProductCommit }
}

const writeJsonAtomic = async (path, value) => {
  await mkdir(dirname(path), { recursive: true })
  const temporaryPath = `${path}.tmp-${process.pid}`
  await writeFile(temporaryPath, `${JSON.stringify(value, null, 2)}\n`, 'utf8')
  await rename(temporaryPath, path)
}

const options = parseArguments(process.argv.slice(2))
const outputPath = resolve(projectRoot, options.output)
const temporaryDirectory = await mkdtemp(join(tmpdir(), 'canlab-chromium-'))
try {
  // Reject stale or ambiguously rewritten identities before any network download.
  const { candidate } = await validateCandidateLineage()
  const sourcePath = join(temporaryDirectory, 'stable-snapshot.json')
  await downloadHttps(sourceUrl, sourcePath)
  const sourceBytes = await readFile(sourcePath)
  const sourceSha256 = createHash('sha256').update(sourceBytes).digest('hex')
  const snapshot = JSON.parse(sourceBytes.toString('utf8'))
  const stable = snapshot.channels?.Stable
  if (
    stable?.channel !== 'Stable' ||
    typeof stable.version !== 'string' ||
    typeof stable.revision !== 'string' ||
    !Array.isArray(stable.downloads?.chrome)
  ) {
    throw new Error('Chrome for Testing stable snapshot does not match its API schema')
  }
  const chromeDownload = stable.downloads.chrome.find(
    (candidate) => candidate.platform === options.platform,
  )
  if (chromeDownload === undefined || typeof chromeDownload.url !== 'string') {
    throw new Error(`Stable Chrome has no ${options.platform} download`)
  }
  const parsedDownloadUrl = new URL(chromeDownload.url)
  if (
    parsedDownloadUrl.protocol !== 'https:' ||
    parsedDownloadUrl.hostname !== 'storage.googleapis.com' ||
    !parsedDownloadUrl.pathname.includes(`/${stable.version}/${options.platform}/`)
  ) {
    throw new Error('Stable Chrome download URL is outside the official version binding')
  }

  const archivePath = join(temporaryDirectory, 'chrome-linux64.zip')
  await downloadHttps(chromeDownload.url, archivePath)
  const archiveSha256 = await hashFile(archivePath)
  const targetCommit = candidate.candidate_commit
  const targetTree = candidate.candidate_tree

  await run('docker', [
    'build',
    '--build-context',
    `p0_browser_archive=${temporaryDirectory}`,
    '--build-arg',
    `CHROME_ARCHIVE_SHA256=${archiveSha256}`,
    '--build-arg',
    `CHROME_VERSION=${stable.version}`,
    '--build-arg',
    `TARGET_COMMIT=${targetCommit}`,
    '--build-arg',
    `TARGET_TREE=${targetTree}`,
    '--label',
    `org.canlab.chromium.version=${stable.version}`,
    '--label',
    `org.canlab.target.commit=${targetCommit}`,
    '--label',
    `org.canlab.target.tree=${targetTree}`,
    '--tag',
    imageRef,
    '--file',
    'tools/browser/Dockerfile.p0',
    '.',
  ])

  const imageDigest = await run(
    'docker',
    ['image', 'inspect', '--format', '{{.Id}}', imageRef],
    { capture: true },
  )
  const versionOutput = await run(
    'docker',
    [
      'run',
      '--rm',
      '--network=none',
      '--entrypoint',
      executablePath,
      imageRef,
      '--version',
    ],
    { capture: true },
  )
  const versionMatch = /([0-9]+(?:\.[0-9]+){3})/.exec(versionOutput)
  if (versionMatch?.[1] !== stable.version) {
    throw new Error(
      `qualified executable version ${versionMatch?.[1] ?? 'unknown'} differs from stable ${stable.version}`,
    )
  }
  const executableHashOutput = await run(
    'docker',
    [
      'run',
      '--rm',
      '--network=none',
      '--entrypoint',
      'sha256sum',
      imageRef,
      executablePath,
    ],
    { capture: true },
  )
  const executableSha256 = executableHashOutput.split(/\s+/)[0]
  if (!/^[0-9a-f]{64}$/.test(executableSha256)) {
    throw new Error('qualified executable did not produce a SHA-256 digest')
  }

  const receipt = {
    schema_version: 'canlab.chromium-qualification.v1',
    status: 'qualified',
    channel: options.channel,
    platform: options.platform,
    stable_version: stable.version,
    stable_revision: stable.revision,
    browser_version: versionMatch[1],
    executable_path: executablePath,
    executable_sha256: executableSha256,
    archive_sha256: archiveSha256,
    image_ref: imageRef,
    image_digest: imageDigest,
    target_commit: targetCommit,
    target_tree: targetTree,
    qualification_snapshot: {
      source_url: sourceUrl,
      source_sha256: sourceSha256,
      published_at: snapshot.timestamp,
      download_url: chromeDownload.url,
    },
  }
  await writeJsonAtomic(outputPath, receipt)
  console.log(
    `Qualified Stable Chrome ${receipt.browser_version} as ${receipt.image_digest} for ${receipt.target_commit}.`,
  )
} finally {
  await rm(temporaryDirectory, { recursive: true, force: true })
}
