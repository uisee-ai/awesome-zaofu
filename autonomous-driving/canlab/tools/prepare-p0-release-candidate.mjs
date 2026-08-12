#!/usr/bin/env node

import { createHash } from 'node:crypto'
import { execFileSync } from 'node:child_process'
import { mkdir, readFile, rename, writeFile } from 'node:fs/promises'
import { dirname, relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const projectRoot = fileURLToPath(new URL('..', import.meta.url))

const parseArguments = (values) => {
  const options = {
    expectedOldMain: undefined,
    evidenceManifest: undefined,
    output: undefined,
    receiptOutput: undefined,
  }
  const names = new Map([
    ['--expected-old-main', 'expectedOldMain'],
    ['--evidence-manifest', 'evidenceManifest'],
    ['--output', 'output'],
    ['--receipt-output', 'receiptOutput'],
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
  return options
}

const git = (...args) => execFileSync('git', args, {
  cwd: projectRoot,
  encoding: 'utf8',
}).trim()

const writeJsonAtomic = async (path, value) => {
  await mkdir(dirname(path), { recursive: true })
  const temporaryPath = `${path}.tmp-${process.pid}`
  await writeFile(temporaryPath, `${JSON.stringify(value, null, 2)}\n`, 'utf8')
  await rename(temporaryPath, path)
}

const options = parseArguments(process.argv.slice(2))
if (!/^[0-9a-f]{40}$/.test(options.expectedOldMain)) {
  throw new Error('--expected-old-main must be a full commit SHA')
}
const currentMain = git('rev-parse', 'refs/heads/main')
if (currentMain !== options.expectedOldMain) {
  throw new Error(`main is ${currentMain}, expected ${options.expectedOldMain}`)
}
const candidateCommit = git('rev-parse', 'HEAD')
const candidateTree = git('rev-parse', 'HEAD^{tree}')
execFileSync(
  'git',
  ['merge-base', '--is-ancestor', options.expectedOldMain, candidateCommit],
  { cwd: projectRoot, stdio: 'ignore' },
)
const evidenceManifestPath = resolve(projectRoot, options.evidenceManifest)
const evidenceManifest = JSON.parse(await readFile(evidenceManifestPath, 'utf8'))
if (
  evidenceManifest.schema_version !== 'canlab.p0-evidence-manifest.v1' ||
  evidenceManifest.subject?.target_commit !== candidateCommit ||
  evidenceManifest.subject?.target_tree !== candidateTree
) {
  throw new Error('evidence manifest is not bound to the current candidate')
}

const candidate = {
  schema_version: 'canlab.release-candidate.v1',
  status: 'verified-awaiting-owner-cas',
  base_commit: options.expectedOldMain,
  candidate_commit: candidateCommit,
  candidate_tree: candidateTree,
  evidence_manifest_ref: relative(projectRoot, evidenceManifestPath),
  required_gate_ids: [
    'V-P0-STATIC',
    'V-P0-QUALIFY',
    'V-P0-BROWSER',
    'V-P0-RELEASE',
  ],
  promotion_action: 'ACTION-CAS-01',
}
const candidateBody = `${JSON.stringify(candidate, null, 2)}\n`
const intent = {
  schema_version: 'canlab.cas-intent.v1',
  status: 'pending-owner-action',
  issued: false,
  immutable_receipt_present: false,
  action_id: 'ACTION-CAS-01',
  expected_old_main: options.expectedOldMain,
  candidate_commit: candidateCommit,
  candidate_tree: candidateTree,
  candidate_manifest_sha256: createHash('sha256')
    .update(candidateBody)
    .digest('hex'),
  authorization: {
    required: true,
    actor: 'owner',
    mechanism: 'token-gated-kernel-control-plane',
  },
  forbidden_callers: ['verify', 'tools/verify-p0-release.sh'],
}

await writeJsonAtomic(resolve(projectRoot, options.output), candidate)
await writeJsonAtomic(resolve(projectRoot, options.receiptOutput), intent)
console.log(
  `Prepared read-only release candidate ${candidateCommit}; Owner CAS remains pending.`,
)
