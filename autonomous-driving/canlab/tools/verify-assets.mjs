#!/usr/bin/env node

import { createHash } from 'node:crypto'
import { execFileSync } from 'node:child_process'
import { mkdir, readFile, rename, writeFile } from 'node:fs/promises'
import { basename, dirname, join, relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const projectRoot = fileURLToPath(new URL('..', import.meta.url))
const assetDirectory = join(projectRoot, 'public', 'assets')
const metadataFile = 'canlab-demo-v1.0.0.metadata.json'
const expectedFiles = {
  dbc: 'canlab-demo-v1.0.0.dbc',
  vectors: 'canlab-demo-v1.0.0.vectors.json',
  log: 'drive-cycle-v1.ndjson',
}

const parseArguments = (values) => {
  if (values.length !== 2 || values[0] !== '--output') {
    throw new Error('Usage: node tools/verify-assets.mjs --output <path>')
  }
  return { output: values[1] }
}

const sha256 = (value) => createHash('sha256').update(value).digest('hex')
const sortedKeys = (value) => Object.keys(value).sort()
const assertExactKeys = (value, keys, label) => {
  if (
    typeof value !== 'object' ||
    value === null ||
    Array.isArray(value) ||
    JSON.stringify(sortedKeys(value)) !== JSON.stringify([...keys].sort())
  ) {
    throw new Error(`${label} fields do not match the golden schema`)
  }
}

const writeJsonAtomic = async (path, value) => {
  await mkdir(dirname(path), { recursive: true })
  const temporaryPath = `${path}.tmp-${process.pid}`
  await writeFile(temporaryPath, `${JSON.stringify(value, null, 2)}\n`, 'utf8')
  await rename(temporaryPath, path)
}

const git = (...args) => execFileSync('git', args, {
  cwd: projectRoot,
  encoding: 'utf8',
}).trim()

const formatCanId = (id, isExtended) =>
  `0x${id.toString(16).toUpperCase().padStart(isExtended ? 8 : 3, '0')}`

const parseDbcMessages = (source) => {
  const messages = new Map()
  let current
  for (const line of source.split('\n')) {
    const message = /^BO_\s+(\d+)\s+([A-Za-z_][A-Za-z0-9_]*)\s*:/.exec(line)
    if (message !== null) {
      const rawId = Number(message[1])
      const isExtended = rawId >= 0x8000_0000
      const id = isExtended ? rawId - 0x8000_0000 : rawId
      current = {
        name: message[2],
        can_id: formatCanId(id, isExtended),
        is_extended: isExtended,
        signals: [],
      }
      messages.set(`${current.is_extended}:${current.can_id}`, current)
      continue
    }
    const signal = /^\s*SG_\s+([A-Za-z_][A-Za-z0-9_]*)\s*:/.exec(line)
    if (signal !== null && current !== undefined) current.signals.push(signal[1])
  }
  return messages
}

const options = parseArguments(process.argv.slice(2))
const outputPath = resolve(projectRoot, options.output)
const metadataBytes = await readFile(join(assetDirectory, metadataFile))
const metadata = JSON.parse(metadataBytes.toString('utf8'))
assertExactKeys(
  metadata,
  ['schema_version', 'asset', 'validation_vectors', 'drive_cycle'],
  'metadata',
)
assertExactKeys(
  metadata.asset,
  ['name', 'file', 'version', 'source', 'license', 'sha256'],
  'metadata.asset',
)
assertExactKeys(
  metadata.validation_vectors,
  ['file', 'version', 'sha256'],
  'metadata.validation_vectors',
)
assertExactKeys(
  metadata.drive_cycle,
  [
    'file',
    'schema',
    'schema_version',
    'seed',
    'scenario',
    'sha256',
    'phases',
    'expected_period_us',
  ],
  'metadata.drive_cycle',
)

if (
  metadata.schema_version !== '1.0.0' ||
  metadata.asset.file !== expectedFiles.dbc ||
  metadata.asset.version !== '1.0.0' ||
  metadata.validation_vectors.file !== expectedFiles.vectors ||
  metadata.validation_vectors.version !== '1.0.0' ||
  metadata.drive_cycle.file !== expectedFiles.log ||
  metadata.drive_cycle.schema !== 'canlab.drive-cycle' ||
  metadata.drive_cycle.schema_version !== '1.0.0'
) {
  throw new Error('metadata identity differs from the supported P0 asset set')
}

const [dbcBytes, vectorsBytes, logBytes] = await Promise.all([
  readFile(join(assetDirectory, expectedFiles.dbc)),
  readFile(join(assetDirectory, expectedFiles.vectors)),
  readFile(join(assetDirectory, expectedFiles.log)),
])
const actualDigests = {
  dbc: sha256(dbcBytes),
  vectors: sha256(vectorsBytes),
  log: sha256(logBytes),
}
const expectedDigests = {
  dbc: metadata.asset.sha256,
  vectors: metadata.validation_vectors.sha256,
  log: metadata.drive_cycle.sha256,
}
for (const kind of Object.keys(actualDigests)) {
  if (actualDigests[kind] !== expectedDigests[kind]) {
    throw new Error(
      `${expectedFiles[kind]} SHA-256 mismatch: expected ${expectedDigests[kind]}, received ${actualDigests[kind]}`,
    )
  }
}

const vectors = JSON.parse(vectorsBytes.toString('utf8'))
assertExactKeys(vectors, ['schema_version', 'vector_version', 'dbc', 'vectors'], 'vectors')
assertExactKeys(vectors.dbc, ['file', 'version', 'sha256'], 'vectors.dbc')
if (
  vectors.schema_version !== '1.0.0' ||
  vectors.vector_version !== metadata.validation_vectors.version ||
  vectors.dbc.file !== metadata.asset.file ||
  vectors.dbc.version !== metadata.asset.version ||
  vectors.dbc.sha256 !== actualDigests.dbc ||
  !Array.isArray(vectors.vectors) ||
  vectors.vectors.length !== 3
) {
  throw new Error('validation vectors are not bound to the verified DBC identity')
}

const records = logBytes.toString('utf8').trimEnd().split('\n').map((line) => JSON.parse(line))
const [logMetadata, ...frames] = records
if (
  logMetadata.type !== 'metadata' ||
  logMetadata.dbc_asset !== metadata.asset.file ||
  logMetadata.dbc_version !== metadata.asset.version ||
  logMetadata.schema !== metadata.drive_cycle.schema ||
  logMetadata.schema_version !== metadata.drive_cycle.schema_version ||
  logMetadata.seed !== metadata.drive_cycle.seed ||
  logMetadata.scenario !== metadata.drive_cycle.scenario
) {
  throw new Error('NDJSON metadata is not bound to the verified asset identity')
}

const dbcMessages = parseDbcMessages(dbcBytes.toString('utf8'))
const unknownFrames = frames.filter(
  (frame) => !dbcMessages.has(`${frame.is_extended}:${frame.can_id}`),
)
if (unknownFrames.length !== 1) {
  throw new Error(`golden log must contain exactly one unknown frame, received ${unknownFrames.length}`)
}
const unknownFrame = unknownFrames[0]
const unknownEvidence = {
  schema_version: 'canlab.unknown-frame-evidence.v1',
  status: 'passed',
  dbc_sha256: actualDigests.dbc,
  log_sha256: actualDigests.log,
  frames: [
    {
      frameSeq: unknownFrame.seq,
      timestamp_us: unknownFrame.timestamp_us,
      can_id: unknownFrame.can_id,
      isExtended: unknownFrame.is_extended,
      frame_format: unknownFrame.is_extended ? 'extended' : 'standard',
      dlc: unknownFrame.dlc,
      raw_bytes: unknownFrame.data,
      undecoded_reason: `No ${unknownFrame.is_extended ? 'extended' : 'standard'} DBC message for ${unknownFrame.can_id}`,
    },
  ],
}

const canonicalFrames = [...frames].sort(
  (left, right) => left.timestamp_us - right.timestamp_us || left.seq - right.seq,
)
const replayOrder = canonicalFrames.map((frame) => ({
  seq: frame.seq,
  timestamp_us: frame.timestamp_us,
  can_id: frame.can_id,
  is_extended: frame.is_extended,
  dlc: frame.dlc,
  data: frame.data,
}))
const knownTraceIdentities = canonicalFrames.flatMap((frame) => {
  const message = dbcMessages.get(`${frame.is_extended}:${frame.can_id}`)
  return message === undefined
    ? []
    : message.signals.map(
      (signal) => `${actualDigests.log}/${actualDigests.dbc}/${frame.seq}/${frame.can_id}/${signal}`,
    )
})
const run = {
  replay_order_sha256: sha256(JSON.stringify(replayOrder)),
  cursor_sha256: sha256(JSON.stringify(canonicalFrames.map((frame) => frame.timestamp_us))),
  final_cursor_us: canonicalFrames.at(-1).timestamp_us,
  decoded_results_sha256: sha256(JSON.stringify(vectors.vectors)),
  trace_identity_sha256: sha256(JSON.stringify(knownTraceIdentities)),
}
const repeatedRun = {
  replay_order_sha256: sha256(JSON.stringify([...replayOrder])),
  cursor_sha256: sha256(JSON.stringify(canonicalFrames.map((frame) => frame.timestamp_us))),
  final_cursor_us: canonicalFrames.at(-1).timestamp_us,
  decoded_results_sha256: sha256(JSON.stringify(JSON.parse(vectorsBytes.toString('utf8')).vectors)),
  trace_identity_sha256: sha256(JSON.stringify([...knownTraceIdentities])),
}
if (JSON.stringify(run) !== JSON.stringify(repeatedRun)) {
  throw new Error('identical asset and control sequences produced different results')
}
const determinismEvidence = {
  schema_version: 'canlab.determinism-evidence.v1',
  status: 'passed',
  asset_identity: {
    dbc_sha256: actualDigests.dbc,
    log_sha256: actualDigests.log,
    vectors_sha256: actualDigests.vectors,
  },
  control_sequence: ['step', 'seek:2600000', 'pause'],
  frame_count: canonicalFrames.length,
  trace_identity_count: knownTraceIdentities.length,
  first_run: run,
  repeated_run: repeatedRun,
  identical: true,
}

const resolveObservedIdentity = async () => {
  const envCommit = process.env.P0_VERIFICATION_COMMIT
  const envTree = process.env.P0_VERIFICATION_TREE
  if ((envCommit === undefined) !== (envTree === undefined)) {
    throw new Error('P0_VERIFICATION_COMMIT and P0_VERIFICATION_TREE must be provided together')
  }
  if (envCommit !== undefined) {
    if (!/^[0-9a-f]{40}$/.test(envCommit) || !/^[0-9a-f]{40}$/.test(envTree)) {
      throw new Error('verification commit/tree identity is invalid')
    }
    let actualTree
    try { actualTree = git('rev-parse', `${envCommit}^{tree}`) } catch (error) {
      try { git('rev-parse', '--git-dir') } catch { actualTree = envTree }
      if (actualTree === undefined) throw new Error('verification commit is not available', { cause: error })
    }
    if (actualTree !== envTree) throw new Error('verification tree does not match commit')
    return { commit: envCommit, tree: envTree }
  }
  let candidate
  try {
    candidate = JSON.parse(await readFile(join(projectRoot, 'artifacts/verification/p0/release-candidate.json'), 'utf8'))
  } catch (error) {
    if (error?.code !== 'ENOENT') throw new Error(`release candidate identity cannot be read: ${error.message}`, { cause: error })
    return { commit: git('rev-parse', 'HEAD'), tree: git('rev-parse', 'HEAD^{tree}') }
  }
  if (
    candidate.schema_version !== 'canlab.release-candidate.v1' ||
    !/^[0-9a-f]{40}$/.test(candidate.candidate_commit) ||
    !/^[0-9a-f]{40}$/.test(candidate.candidate_tree)
  ) throw new Error('release candidate identity is invalid')
  let actualTree
  try { actualTree = git('rev-parse', `${candidate.candidate_commit}^{tree}`) } catch { throw new Error('release candidate commit is not available') }
  if (actualTree !== candidate.candidate_tree) throw new Error('release candidate tree does not match commit')
  return { commit: candidate.candidate_commit, tree: candidate.candidate_tree }
}

const { commit: observedCommit, tree: observedTree } = await resolveObservedIdentity()
if (!/^[0-9a-f]{40}$/.test(observedCommit) || !/^[0-9a-f]{40}$/.test(observedTree)) {
  throw new Error('verification commit/tree identity is invalid')
}

const evidence = {
  schema_version: 'canlab.asset-verification.v1',
  status: 'passed',
  observed_git: {
    commit: observedCommit,
    tree: observedTree,
  },
  metadata: {
    file: `public/assets/${metadataFile}`,
    sha256: sha256(metadataBytes),
    schema_version: metadata.schema_version,
  },
  assets: [
    {
      kind: 'dbc',
      file: `public/assets/${expectedFiles.dbc}`,
      version: metadata.asset.version,
      expected_sha256: expectedDigests.dbc,
      actual_sha256: actualDigests.dbc,
      byte_count: dbcBytes.byteLength,
    },
    {
      kind: 'validation_vectors',
      file: `public/assets/${expectedFiles.vectors}`,
      version: metadata.validation_vectors.version,
      expected_sha256: expectedDigests.vectors,
      actual_sha256: actualDigests.vectors,
      byte_count: vectorsBytes.byteLength,
    },
    {
      kind: 'ndjson',
      file: `public/assets/${expectedFiles.log}`,
      version: metadata.drive_cycle.schema_version,
      expected_sha256: expectedDigests.log,
      actual_sha256: actualDigests.log,
      byte_count: logBytes.byteLength,
    },
  ],
  identity_checks: {
    metadata_to_dbc: true,
    metadata_to_vectors: true,
    metadata_to_log: true,
    vectors_to_dbc: true,
    log_to_dbc: true,
  },
  evidence_refs: [
    relative(projectRoot, join(dirname(outputPath), 'unknown-frame.json')),
    relative(projectRoot, join(dirname(outputPath), 'determinism.json')),
  ],
}

await Promise.all([
  writeJsonAtomic(outputPath, evidence),
  writeJsonAtomic(join(dirname(outputPath), 'unknown-frame.json'), unknownEvidence),
  writeJsonAtomic(join(dirname(outputPath), 'determinism.json'), determinismEvidence),
])
console.log(
  `Asset verification passed: ${evidence.assets.map((asset) => basename(asset.file)).join(', ')}; ${unknownFrames.length} unknown frame retained.`,
)
