#!/usr/bin/env node

import { createHash } from 'node:crypto'
import { spawn } from 'node:child_process'
import { execFileSync } from 'node:child_process'
import { mkdirSync, rmSync, writeFileSync } from 'node:fs'
import { mkdir, mkdtemp, readFile, rename, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, join, relative, resolve, sep } from 'node:path'
import { fileURLToPath } from 'node:url'

const projectRoot = resolve(fileURLToPath(new URL('..', import.meta.url)))

const parseArguments = (values) => {
  const options = {
    mode: undefined,
    expectedOldMain: undefined,
    candidateManifest: undefined,
    casReceipt: undefined,
    output: undefined,
  }
  const names = new Map([
    ['--mode', 'mode'],
    ['--expected-old-main', 'expectedOldMain'],
    ['--candidate-manifest', 'candidateManifest'],
    ['--cas-receipt', 'casReceipt'],
    ['--output', 'output'],
  ])
  for (let index = 0; index < values.length; index += 1) {
    const key = names.get(values[index])
    if (key === undefined) throw new Error(`Unknown argument ${values[index]}`)
    const value = values[index + 1]
    if (value === undefined || value.startsWith('--')) {
      throw new Error(`${values[index]} requires a value`)
    }
    options[key] = value
    index += 1
  }
  for (const [name, key] of names) {
    if (options[key] === undefined) throw new Error(`${name} is required`)
  }
  if (options.mode !== 'read-only') {
    throw new Error('release verification only supports --mode read-only')
  }
  return options
}

const gitBuffer = (...args) => execFileSync('git', args, {
  cwd: projectRoot,
  maxBuffer: 64 * 1024 * 1024,
})

const git = (...args) => gitBuffer(...args).toString('utf8').trim()

const sha256 = (value) => createHash('sha256').update(value).digest('hex')

const productPatchDigest = (baseCommit, commit) => sha256(gitBuffer(
  'diff', '--binary', baseCommit, commit, '--', '.',
  ':(exclude)artifacts/verification/p0',
))

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

const evidenceCarrierProof = (baseCommit, pendingCommit, carrierCommit) => {
  if (!gitIsAncestor(baseCommit, pendingCommit)) {
    throw new Error('pending candidate is not based on expected old main')
  }
  if (pendingCommit === carrierCommit || !gitIsAncestor(pendingCommit, carrierCommit)) {
    throw new Error('evidence carrier must be a strict descendant of pending candidate')
  }
  if (git('rev-list', '--merges', `${baseCommit}..${pendingCommit}`)) {
    throw new Error('non-ancestor pending candidate contains merge commits')
  }
  const changedPaths = git('diff', '--name-only', pendingCommit, carrierCommit)
    .split('\n')
    .filter(Boolean)
  if (
    changedPaths.length === 0 ||
    changedPaths.some((path) => !path.startsWith('artifacts/verification/p0/'))
  ) {
    throw new Error('evidence carrier contains non-evidence changes')
  }
  return 'evidence-only'
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

const resolveEvidenceArtifactPath = (path) => {
  if (
    typeof path !== 'string' ||
    path.length === 0 ||
    path.startsWith('/') ||
    path.split(/[\\/]/).includes('..')
  ) {
    throw new Error(`evidence artifact path must be repository-relative: ${String(path)}`)
  }
  const absolutePath = resolve(projectRoot, path)
  if (!absolutePath.startsWith(`${projectRoot}${sep}`)) {
    throw new Error(`evidence artifact path escaped the repository: ${path}`)
  }
  return absolutePath
}

const writeJsonAtomic = async (path, value) => {
  await mkdir(dirname(path), { recursive: true })
  const temporaryPath = `${path}.tmp-${process.pid}`
  await writeFile(temporaryPath, `${JSON.stringify(value, null, 2)}\n`, 'utf8')
  await rename(temporaryPath, path)
}

const run = (command, args, cwd, extraEnvironment = {}) => new Promise((resolveRun, rejectRun) => {
  const child = spawn(command, args, {
    cwd,
    env: { ...process.env, ...extraEnvironment },
    stdio: ['ignore', 'pipe', 'pipe'],
  })
  let stdout = ''
  let stderr = ''
  child.stdout.on('data', (chunk) => { stdout += chunk.toString() })
  child.stderr.on('data', (chunk) => { stderr += chunk.toString() })
  child.once('error', rejectRun)
  child.once('exit', (code) => {
    const result = {
      command: [command, ...args].join(' '),
      exit_code: code,
      stdout_sha256: sha256(stdout),
      stderr_sha256: sha256(stderr),
    }
    if (code === 0) resolveRun(result)
    else rejectRun(new Error(
      `${result.command} exited ${String(code)}: ${stderr || stdout}`,
    ))
  })
})

const exportCommit = async (commit, destination) => {
  await new Promise((resolveExport, rejectExport) => {
    const archive = spawn('git', ['archive', '--format=tar', commit], {
      cwd: projectRoot,
      stdio: ['ignore', 'pipe', 'pipe'],
    })
    const extract = spawn('tar', ['-x', '-C', destination], {
      stdio: ['pipe', 'ignore', 'pipe'],
    })
    let archiveError = ''
    let extractError = ''
    archive.stderr.on('data', (chunk) => { archiveError += chunk.toString() })
    extract.stderr.on('data', (chunk) => { extractError += chunk.toString() })
    archive.stdout.pipe(extract.stdin)
    let archiveCode
    let extractCode
    const finish = () => {
      if (archiveCode === undefined || extractCode === undefined) return
      if (archiveCode === 0 && extractCode === 0) resolveExport()
      else rejectExport(new Error(
        `clean export failed: git=${String(archiveCode)} tar=${String(extractCode)} ${archiveError}${extractError}`,
      ))
    }
    archive.once('error', rejectExport)
    extract.once('error', rejectExport)
    archive.once('exit', (code) => { archiveCode = code; finish() })
    extract.once('exit', (code) => { extractCode = code; finish() })
  })
}

const options = parseArguments(process.argv.slice(2))
if (!/^[0-9a-f]{40}$/.test(options.expectedOldMain)) {
  throw new Error('--expected-old-main must be a full commit SHA')
}

const trackedEvidencePaths = gitBuffer(
  'ls-files',
  '-z',
  '--',
  'artifacts/verification/p0',
).toString('utf8').split('\0').filter(Boolean)
const trackedEvidence = new Map(
  trackedEvidencePaths.map((path) => [path, gitBuffer('show', `HEAD:${path}`)]),
)
let evidenceRestored = false
const restoreTrackedEvidence = () => {
  if (evidenceRestored) return
  evidenceRestored = true
  rmSync(resolve(projectRoot, 'artifacts/verification/p0'), {
    recursive: true,
    force: true,
  })
  for (const [path, body] of trackedEvidence) {
    const absolutePath = resolve(projectRoot, path)
    mkdirSync(dirname(absolutePath), { recursive: true })
    writeFileSync(absolutePath, body)
  }
}
process.once('exit', restoreTrackedEvidence)

const outputDirectory = resolve(projectRoot, options.output)
const candidateManifestPath = resolve(projectRoot, options.candidateManifest)
const casReceiptPath = resolve(projectRoot, options.casReceipt)
let candidateBody = await readFile(candidateManifestPath)
let candidate = JSON.parse(candidateBody.toString('utf8'))
let casReceipt = JSON.parse(await readFile(casReceiptPath, 'utf8'))
if (
  candidate.schema_version !== 'canlab.release-candidate.v1' ||
  candidate.status !== 'verified-awaiting-owner-cas' ||
  candidate.base_commit !== options.expectedOldMain ||
  !/^[0-9a-f]{40}$/.test(candidate.candidate_commit) ||
  !/^[0-9a-f]{40}$/.test(candidate.candidate_tree)
) {
  throw new Error('release candidate manifest does not match schema v1')
}
if (
  casReceipt.schema_version !== 'canlab.cas-intent.v1' ||
  casReceipt.status !== 'pending-owner-action' ||
  casReceipt.issued !== false ||
  casReceipt.immutable_receipt_present !== false ||
  casReceipt.expected_old_main !== options.expectedOldMain ||
  casReceipt.candidate_commit !== candidate.candidate_commit ||
  casReceipt.candidate_tree !== candidate.candidate_tree ||
  casReceipt.candidate_manifest_sha256 !== sha256(candidateBody) ||
  casReceipt.authorization?.actor !== 'owner' ||
  casReceipt.authorization?.mechanism !== 'token-gated-kernel-control-plane' ||
  JSON.stringify(casReceipt.forbidden_callers) !==
    JSON.stringify(['verify', 'tools/verify-p0-release.sh'])
) {
  throw new Error('CAS input is not an unissued Owner-only promotion intent')
}

const refsBefore = git('for-each-ref', '--format=%(refname) %(objectname)')
const mainBefore = git('rev-parse', 'refs/heads/main')
const integratedCommit = git('rev-parse', 'HEAD')
if (mainBefore !== options.expectedOldMain) {
  throw new Error(`main is ${mainBefore}, expected ${options.expectedOldMain}`)
}
if (!gitIsAncestor(options.expectedOldMain, candidate.candidate_commit)) {
  throw new Error('pending candidate is not based on expected old main')
}
if (git('rev-parse', `${candidate.candidate_commit}^{tree}`) !== candidate.candidate_tree) {
  throw new Error('candidate tree does not match candidate commit')
}

const integratedProductCommit = resolveIntegratedProduct(
  options.expectedOldMain,
  candidate.candidate_commit,
  integratedCommit,
)
if (candidate.source_commit !== undefined || candidate.source_tree !== undefined) {
  if (
    !/^[0-9a-f]{40}$/.test(candidate.source_commit) ||
    !/^[0-9a-f]{40}$/.test(candidate.source_tree) ||
    git('rev-parse', `${candidate.source_commit}^{tree}`) !== candidate.source_tree ||
    productPatchDigest(options.expectedOldMain, candidate.source_commit) !==
      productPatchDigest(options.expectedOldMain, candidate.candidate_commit)
  ) {
    throw new Error('product source and integrated candidate are not patch-equivalent')
  }
}

const evidenceManifestPath = resolve(projectRoot, candidate.evidence_manifest_ref)
const evidenceManifest = JSON.parse(await readFile(evidenceManifestPath, 'utf8'))
if (
  evidenceManifest.schema_version !== 'canlab.p0-evidence-manifest.v1' ||
  evidenceManifest.subject?.target_commit !== candidate.candidate_commit ||
  evidenceManifest.subject?.target_tree !== candidate.candidate_tree ||
  !Array.isArray(evidenceManifest.artifacts)
) {
  throw new Error('P0 evidence manifest is not bound to the pending product candidate')
}
for (const artifact of evidenceManifest.artifacts) {
  const body = await readFile(resolveEvidenceArtifactPath(artifact.path))
  if (sha256(body) !== artifact.sha256 || body.byteLength !== artifact.byte_count) {
    throw new Error(`evidence digest mismatch for ${artifact.path}`)
  }
}
const identityArtifacts = [
  ['artifacts/verification/p0/static/assets.json', 'observed_git.commit', 'observed_git.tree'],
  ['artifacts/verification/p0/browser/qualification.json', 'target_commit', 'target_tree'],
  ['artifacts/verification/p0/release/clean-checkout.json', 'candidate_commit', 'candidate_tree'],
  ['artifacts/verification/p0/release/final-verification.json', 'candidate_commit', 'candidate_tree'],
]
const qualificationEvidence = JSON.parse(
  await readFile(resolveEvidenceArtifactPath('artifacts/verification/p0/browser/qualification.json'), 'utf8'),
)
if (qualificationEvidence.image_digest !== evidenceManifest.browser_qualification?.image_digest) {
  throw new Error('browser qualification image digest does not match evidence manifest')
}
const finalVerificationReceipt = JSON.parse(
  await readFile(resolveEvidenceArtifactPath('artifacts/verification/p0/release/final-verification.json'), 'utf8'),
)
if (finalVerificationReceipt.evidence_artifact_count !== evidenceManifest.artifacts.length) {
  throw new Error('final verification evidence artifact count does not match evidence manifest')
}
for (const [path, commitKey, treeKey] of identityArtifacts) {
  const value = JSON.parse(await readFile(resolveEvidenceArtifactPath(path), 'utf8'))
  const readKey = (object, key) => key.split('.').reduce((current, part) => current?.[part], object)
  if (readKey(value, commitKey) !== candidate.candidate_commit || readKey(value, treeKey) !== candidate.candidate_tree) {
    throw new Error(`identity-bearing evidence is not bound to product candidate: ${path}`)
  }
}

const pendingIntentRebound = false
const pendingIntentLineageProof = evidenceCarrierProof(
  options.expectedOldMain,
  integratedProductCommit,
  integratedCommit,
)

const temporaryCheckout = await mkdtemp(join(tmpdir(), 'canlab-release-'))
let commandReceipts
try {
  await exportCommit(candidate.candidate_commit, temporaryCheckout)
  commandReceipts = []
  const verificationEnvironment = {
    CANLAB_NESTED_RELEASE_VERIFY: '1',
  P0_VERIFICATION_COMMIT: candidate.candidate_commit,
  P0_VERIFICATION_TREE: candidate.candidate_tree,
  }
  for (const [command, args] of [
    ['npm', ['ci']],
    ['npm', ['run', 'lint']],
    ['npm', ['test']],
    ['npm', ['run', 'build']],
    ['node', ['tools/verify-assets.mjs', '--output', 'artifacts/verification/p0/static/assets.json']],
    ['node', ['tools/check-passive-boundary.mjs', '--policy', 'config/passive-boundary-policy.json', '--fixtures', 'tests/fixtures/passive-boundary', '--output', 'artifacts/verification/p0/static/boundary-matrix.json']],
    ['node', ['tools/check-csp-delivery.mjs', '--policy', 'config/csp-policy.json', '--server', 'tools/serve-p0-preview.mjs', '--output', 'artifacts/verification/p0/static/csp.json']],
  ]) {
    commandReceipts.push(await run(
      command,
      args,
      temporaryCheckout,
      verificationEnvironment,
    ))
  }
} finally {
  await rm(temporaryCheckout, { recursive: true, force: true })
}

const refsAfter = git('for-each-ref', '--format=%(refname) %(objectname)')
const mainAfter = git('rev-parse', 'refs/heads/main')
if (refsAfter !== refsBefore || mainAfter !== mainBefore) {
  throw new Error('read-only verifier changed a Git ref')
}

const cleanCheckoutEvidence = {
  schema_version: 'canlab.clean-checkout-evidence.v1',
  status: 'passed',
  candidate_commit: candidate.candidate_commit,
  candidate_tree: candidate.candidate_tree,
  integrated_candidate_commit: integratedProductCommit,
  source_to_integrated_mapping: {
    source_commit: candidate.candidate_commit,
    integrated_commit: integratedProductCommit,
  },
  method: 'git-archive-to-ephemeral-directory',
  command_receipts: commandReceipts,
}
const writerSeparationEvidence = {
  schema_version: 'canlab.writer-separation-evidence.v1',
  status: 'passed',
  verifier_mode: options.mode,
  main_before: mainBefore,
  main_after: mainAfter,
  refs_before_sha256: sha256(refsBefore),
  refs_after_sha256: sha256(refsAfter),
  refs_unchanged: true,
  cas_state: 'pending-owner-action',
  authorized_writer: casReceipt.authorization.mechanism,
  forbidden_callers: casReceipt.forbidden_callers,
}
const runtimeAuditEvidence = {
  schema_version: 'canlab.runtime-audit-evidence.v1',
  status: 'passed',
  lifecycle: 'candidate-ready',
  promotion_state: 'pending-owner-action',
  contradiction: false,
  rationale:
    'Candidate verification is complete; no final-main delivery is asserted before the Owner-only CAS action.',
}
const finalVerificationEvidence = {
  schema_version: 'canlab.release-verification.v1',
  status: 'passed',
  mode: options.mode,
  release_status: 'candidate-ready-awaiting-owner-cas',
  expected_old_main: options.expectedOldMain,
  observed_main: mainAfter,
  candidate_commit: candidate.candidate_commit,
  candidate_tree: candidate.candidate_tree,
  evidence_manifest_ref: candidate.evidence_manifest_ref,
  evidence_artifact_count: evidenceManifest.artifacts.length,
  clean_checkout_gate_count: commandReceipts.length,
  refs_unchanged: true,
  owner_cas_required: true,
  pending_intent_rebound: pendingIntentRebound,
  pending_intent_lineage_proof: pendingIntentLineageProof,
}

await Promise.all([
  writeJsonAtomic(join(outputDirectory, 'clean-checkout.json'), cleanCheckoutEvidence),
  writeJsonAtomic(join(outputDirectory, 'writer-separation.json'), writerSeparationEvidence),
  writeJsonAtomic(join(outputDirectory, 'runtime-audit.json'), runtimeAuditEvidence),
  writeJsonAtomic(join(outputDirectory, 'final-verification.json'), finalVerificationEvidence),
])

const releasePaths = [
  relative(projectRoot, candidateManifestPath),
  relative(projectRoot, casReceiptPath),
  relative(projectRoot, join(outputDirectory, 'clean-checkout.json')),
  relative(projectRoot, join(outputDirectory, 'writer-separation.json')),
  relative(projectRoot, join(outputDirectory, 'runtime-audit.json')),
  relative(projectRoot, join(outputDirectory, 'final-verification.json')),
]
const releaseArtifacts = []
for (const path of releasePaths) {
  const body = await readFile(resolve(projectRoot, path))
  releaseArtifacts.push({ path, sha256: sha256(body), byte_count: body.byteLength })
}
await writeJsonAtomic(evidenceManifestPath, {
  ...evidenceManifest,
  status: 'candidate-ready-awaiting-owner-cas',
  artifacts: [
    ...evidenceManifest.artifacts.filter(
      (artifact) => !releasePaths.includes(artifact.path),
    ),
    ...releaseArtifacts,
  ],
  release: {
    mode: options.mode,
    promotion_state: 'pending-owner-action',
    refs_unchanged: true,
  },
})

console.log(
  `Read-only release gate passed for ${candidate.candidate_commit} -> ${integratedProductCommit}; main remained ${mainAfter}, Owner CAS is pending, pending intent rebound to integrated candidate=${String(pendingIntentRebound)}, lineage proof=${pendingIntentLineageProof}.`,
)
