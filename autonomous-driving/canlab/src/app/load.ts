import { sha256 } from '@noble/hashes/sha2.js'
import { bytesToHex } from '@noble/hashes/utils.js'

import { createExpectedPeriodCatalog } from '../domain/health/index.ts'
import { parseDbc, type DbcDatabase } from '../domain/dbc/index.ts'
import { parseCanLogNdjson, type CanLogFrame } from '../domain/log/index.ts'
import type { CanLabAssetMetadata } from '../ui/shared/model.ts'

const METADATA_URL = '/assets/canlab-demo-v1.0.0.metadata.json'
const DBC_URL = '/assets/canlab-demo-v1.0.0.dbc'
const VECTORS_URL = '/assets/canlab-demo-v1.0.0.vectors.json'
const LOG_URL = '/assets/drive-cycle-v1.ndjson'
const SUPPORTED_ASSET_VERSION = '1.0.0'

export interface BundledCanLab {
  readonly assetMetadata: CanLabAssetMetadata
  readonly database: DbcDatabase
  readonly expectedPeriodUs: Readonly<Record<string, number>>
  readonly frames: readonly CanLogFrame[]
  readonly dbcHash: string
  readonly vectorsHash: string
  readonly logHash: string
}

export class BundledAssetError extends Error {
  readonly code = 'BUNDLED_ASSET_INVALID'

  constructor(message: string) {
    super(message)
    this.name = 'BundledAssetError'
  }
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)

const hasExactKeys = (
  value: Record<string, unknown>,
  keys: readonly string[],
): boolean => {
  const actual = Object.keys(value).sort()
  const expected = [...keys].sort()
  return (
    actual.length === expected.length &&
    actual.every((key, index) => key === expected[index])
  )
}

const isStringRecord = (value: unknown): value is Record<string, string> =>
  isRecord(value) && Object.values(value).every((item) => typeof item === 'string')

const isPositiveIntegerRecord = (
  value: unknown,
): value is Record<string, number> =>
  isRecord(value) &&
  Object.values(value).every(
    (item) => Number.isSafeInteger(item) && Number(item) > 0,
  )

const parseMetadata = (source: string): CanLabAssetMetadata => {
  let value: unknown
  try {
    value = JSON.parse(source)
  } catch {
    throw new BundledAssetError('metadata is not valid JSON')
  }

  if (
    !isRecord(value) ||
    !hasExactKeys(value, [
      'schema_version',
      'asset',
      'validation_vectors',
      'drive_cycle',
    ]) ||
    typeof value.schema_version !== 'string' ||
    !isRecord(value.asset) ||
    !hasExactKeys(value.asset, [
      'name',
      'file',
      'version',
      'source',
      'license',
      'sha256',
    ]) ||
    !isStringRecord(value.asset) ||
    !isRecord(value.validation_vectors) ||
    !hasExactKeys(value.validation_vectors, ['file', 'version', 'sha256']) ||
    !isStringRecord(value.validation_vectors) ||
    !isRecord(value.drive_cycle) ||
    !hasExactKeys(value.drive_cycle, [
      'file',
      'schema',
      'schema_version',
      'seed',
      'scenario',
      'sha256',
      'phases',
      'expected_period_us',
    ]) ||
    typeof value.drive_cycle.file !== 'string' ||
    typeof value.drive_cycle.schema !== 'string' ||
    typeof value.drive_cycle.schema_version !== 'string' ||
    !Number.isSafeInteger(value.drive_cycle.seed) ||
    typeof value.drive_cycle.scenario !== 'string' ||
    typeof value.drive_cycle.sha256 !== 'string' ||
    !Array.isArray(value.drive_cycle.phases) ||
    !value.drive_cycle.phases.every((phase) => typeof phase === 'string') ||
    !isPositiveIntegerRecord(value.drive_cycle.expected_period_us)
  ) {
    throw new BundledAssetError('metadata fields do not match the bundled schema')
  }

  return value as unknown as CanLabAssetMetadata
}

interface FetchedAsset {
  readonly source: string
  readonly sha256: string
}

const sha256Hex = async (bytes: Uint8Array): Promise<string> => {
  if (globalThis.crypto?.subtle === undefined) {
    return bytesToHex(sha256(bytes))
  }
  const buffer = new ArrayBuffer(bytes.byteLength)
  new Uint8Array(buffer).set(bytes)
  const digest = await globalThis.crypto.subtle.digest('SHA-256', buffer)
  return bytesToHex(new Uint8Array(digest))
}

const fetchAsset = async (
  fetcher: typeof fetch,
  url: string,
): Promise<FetchedAsset> => {
  const response = await fetcher(url)
  if (!response.ok) {
    throw new BundledAssetError(`${url} returned HTTP ${response.status}`)
  }
  const bytes = new Uint8Array(await response.arrayBuffer())
  let source: string
  try {
    source = new TextDecoder('utf-8', { fatal: true }).decode(bytes)
  } catch {
    throw new BundledAssetError(`${url} is not valid UTF-8`)
  }
  return { source, sha256: await sha256Hex(bytes) }
}

interface ValidationVectorIdentity {
  readonly schemaVersion: string
  readonly vectorVersion: string
  readonly dbc: {
    readonly file: string
    readonly version: string
    readonly sha256: string
  }
}

const parseValidationVectorIdentity = (
  source: string,
): ValidationVectorIdentity => {
  let value: unknown
  try {
    value = JSON.parse(source)
  } catch {
    throw new BundledAssetError('validation vectors are not valid JSON')
  }
  if (
    !isRecord(value) ||
    !hasExactKeys(value, [
      'schema_version',
      'vector_version',
      'dbc',
      'vectors',
    ]) ||
    typeof value.schema_version !== 'string' ||
    typeof value.vector_version !== 'string' ||
    !isRecord(value.dbc) ||
    !hasExactKeys(value.dbc, ['file', 'version', 'sha256']) ||
    !isStringRecord(value.dbc) ||
    !Array.isArray(value.vectors) ||
    value.vectors.length === 0
  ) {
    throw new BundledAssetError(
      'validation vector fields do not match the bundled schema',
    )
  }
  return {
    schemaVersion: value.schema_version,
    vectorVersion: value.vector_version,
    dbc: {
      file: value.dbc.file,
      version: value.dbc.version,
      sha256: value.dbc.sha256,
    },
  }
}

const equalRecord = (
  left: Readonly<Record<string, number>>,
  right: Readonly<Record<string, number>>,
): boolean => {
  const leftEntries = Object.entries(left).sort(([a], [b]) => a.localeCompare(b))
  const rightEntries = Object.entries(right).sort(([a], [b]) => a.localeCompare(b))
  return JSON.stringify(leftEntries) === JSON.stringify(rightEntries)
}

export const loadBundledCanLab = async (
  fetcher: typeof fetch = globalThis.fetch,
): Promise<BundledCanLab> => {
  const metadataAsset = await fetchAsset(fetcher, METADATA_URL)
  const assetMetadata = parseMetadata(metadataAsset.source)

  if (
    assetMetadata.schema_version !== SUPPORTED_ASSET_VERSION ||
    assetMetadata.asset.file !== DBC_URL.split('/').at(-1) ||
    assetMetadata.asset.version !== SUPPORTED_ASSET_VERSION ||
    assetMetadata.validation_vectors.file !== VECTORS_URL.split('/').at(-1) ||
    assetMetadata.validation_vectors.version !== SUPPORTED_ASSET_VERSION ||
    assetMetadata.drive_cycle.file !== LOG_URL.split('/').at(-1) ||
    assetMetadata.drive_cycle.schema_version !== SUPPORTED_ASSET_VERSION
  ) {
    throw new BundledAssetError('unsupported bundled asset identity')
  }

  const [dbcAsset, vectorsAsset, logAsset] = await Promise.all([
    fetchAsset(fetcher, DBC_URL),
    fetchAsset(fetcher, VECTORS_URL),
    fetchAsset(fetcher, LOG_URL),
  ])

  const digestMismatches = [
    [assetMetadata.asset.file, assetMetadata.asset.sha256, dbcAsset.sha256],
    [
      assetMetadata.validation_vectors.file,
      assetMetadata.validation_vectors.sha256,
      vectorsAsset.sha256,
    ],
    [
      assetMetadata.drive_cycle.file,
      assetMetadata.drive_cycle.sha256,
      logAsset.sha256,
    ],
  ].filter(([, expected, actual]) => expected !== actual)
  if (digestMismatches.length > 0) {
    const [file, expected, actual] = digestMismatches[0]!
    throw new BundledAssetError(
      `${file} SHA-256 mismatch: expected ${expected}, received ${actual}`,
    )
  }

  const vectorIdentity = parseValidationVectorIdentity(vectorsAsset.source)
  if (
    vectorIdentity.schemaVersion !== SUPPORTED_ASSET_VERSION ||
    vectorIdentity.vectorVersion !== assetMetadata.validation_vectors.version ||
    vectorIdentity.dbc.file !== assetMetadata.asset.file ||
    vectorIdentity.dbc.version !== assetMetadata.asset.version ||
    vectorIdentity.dbc.sha256 !== dbcAsset.sha256
  ) {
    throw new BundledAssetError('validation vectors and DBC identity do not match')
  }

  const dbc = parseDbc(dbcAsset.source)
  if (!dbc.ok) {
    throw new BundledAssetError(`DBC parse failed: ${dbc.error.message}`)
  }
  const log = parseCanLogNdjson(logAsset.source)

  if (
    assetMetadata.asset.file !== log.metadata.dbc_asset ||
    assetMetadata.asset.version !== log.metadata.dbc_version ||
    assetMetadata.drive_cycle.file !== LOG_URL.split('/').at(-1) ||
    assetMetadata.drive_cycle.schema !== log.metadata.schema ||
    assetMetadata.drive_cycle.schema_version !== log.metadata.schema_version ||
    assetMetadata.drive_cycle.seed !== log.metadata.seed ||
    assetMetadata.drive_cycle.scenario !== log.metadata.scenario ||
    JSON.stringify(assetMetadata.drive_cycle.phases) !==
      JSON.stringify(log.metadata.phases.map(({ name }) => name)) ||
    !equalRecord(
      assetMetadata.drive_cycle.expected_period_us,
      log.metadata.expected_period_us,
    )
  ) {
    throw new BundledAssetError('metadata and NDJSON identity do not match')
  }

  createExpectedPeriodCatalog(
    dbc.database,
    assetMetadata.drive_cycle.expected_period_us,
  )

  return {
    assetMetadata,
    database: dbc.database,
    expectedPeriodUs: assetMetadata.drive_cycle.expected_period_us,
    frames: log.frames,
    dbcHash: dbcAsset.sha256,
    vectorsHash: vectorsAsset.sha256,
    logHash: logAsset.sha256,
  }
}
