import type { DbcDatabase } from '../dbc/index.ts'
import { formatCanId } from '../decode/index.ts'

export interface HealthFrame {
  readonly seq: number
  readonly timestamp_us: number
  readonly can_id: string
  readonly is_extended: boolean
  readonly dlc: number
  readonly data: string
}

export interface ExpectedPeriodMessage {
  readonly canId: string
  readonly isExtended: boolean
  readonly messageName: string
  readonly expectedPeriodUs: number | null
}

export interface ExpectedPeriodCatalog {
  readonly messages: readonly ExpectedPeriodMessage[]
}

export interface HealthMetric {
  readonly canId: string
  readonly messageName: string
  readonly expectedPeriodUs: number | null
  readonly lastSeenUs: number | null
  readonly stale: boolean | null
  readonly inferredMissingFrames: number | null
  readonly frequencyHz: number
}

export class PeriodMirrorError extends Error {
  readonly code = 'PERIOD_MIRROR_MISMATCH'
  readonly canId: string

  constructor(canId: string, message: string) {
    super(`PERIOD_MIRROR_MISMATCH for ${canId}: ${message}`)
    this.name = 'PeriodMirrorError'
    this.canId = canId
  }
}

const isPositiveSafeInteger = (value: unknown): value is number =>
  typeof value === 'number' && Number.isSafeInteger(value) && value > 0

const isNonNegativeSafeInteger = (value: unknown): value is number =>
  typeof value === 'number' && Number.isSafeInteger(value) && value >= 0

export const createExpectedPeriodCatalog = (
  database: DbcDatabase,
  manifestExpectedPeriodUs: Readonly<Record<string, number>>,
): ExpectedPeriodCatalog => {
  const canonicalKeys = new Set<string>()
  const messages = database.messages.map((message): ExpectedPeriodMessage => {
    const canId = formatCanId(message.id, message.isExtended)
    canonicalKeys.add(canId)
    const dbcPeriod = message.cycleTimeUs
    const manifestHasPeriod = Object.hasOwn(manifestExpectedPeriodUs, canId)
    const manifestPeriod = manifestExpectedPeriodUs[canId]

    if (dbcPeriod === undefined) {
      if (manifestHasPeriod) {
        throw new PeriodMirrorError(
          canId,
          'manifest declares a period but the DBC message has no cycle',
        )
      }
      return {
        canId,
        isExtended: message.isExtended,
        messageName: message.name,
        expectedPeriodUs: null,
      }
    }

    if (!isPositiveSafeInteger(dbcPeriod)) {
      throw new PeriodMirrorError(canId, 'DBC cycle must be a positive safe integer')
    }
    if (!manifestHasPeriod || manifestPeriod !== dbcPeriod) {
      throw new PeriodMirrorError(
        canId,
        `manifest period ${String(manifestPeriod)} does not equal DBC period ${String(dbcPeriod)}`,
      )
    }

    return {
      canId,
      isExtended: message.isExtended,
      messageName: message.name,
      expectedPeriodUs: dbcPeriod,
    }
  })

  for (const [canId, period] of Object.entries(manifestExpectedPeriodUs)) {
    if (!canonicalKeys.has(canId)) {
      throw new PeriodMirrorError(
        canId,
        `manifest period ${String(period)} has no matching DBC message`,
      )
    }
  }

  return { messages }
}

interface CanonicalHealthEvent {
  readonly seq: number
  readonly timestampUs: number
  readonly canId: string
}

const canonicalEvent = (frame: HealthFrame): CanonicalHealthEvent => {
  if (
    !isNonNegativeSafeInteger(frame.seq) ||
    !isNonNegativeSafeInteger(frame.timestamp_us) ||
    !/^0x[\da-f]+$/i.test(frame.can_id)
  ) {
    throw new TypeError(
      'Health history requires non-negative integer seq/timestamp_us and hexadecimal can_id',
    )
  }
  const numericCanId = Number.parseInt(frame.can_id.slice(2), 16)
  return {
    seq: frame.seq,
    timestampUs: frame.timestamp_us,
    canId: formatCanId(numericCanId, frame.is_extended),
  }
}

export const calculateHealthMetrics = (
  catalog: ExpectedPeriodCatalog,
  history: readonly HealthFrame[],
  replayTimeUs: number,
): readonly HealthMetric[] => {
  if (!isNonNegativeSafeInteger(replayTimeUs)) {
    throw new RangeError('replayTimeUs must be a non-negative safe integer')
  }

  const events = history
    .map(canonicalEvent)
    .filter((event) => event.timestampUs <= replayTimeUs)
    .sort(
      (left, right) =>
        left.timestampUs - right.timestampUs || left.seq - right.seq,
    )

  return catalog.messages.map((message): HealthMetric => {
    const timestamps = events
      .filter((event) => event.canId === message.canId)
      .map((event) => event.timestampUs)
    const lastSeenUs = timestamps.at(-1) ?? null
    const frequencyHz = timestamps.filter(
      (timestampUs) =>
        timestampUs > replayTimeUs - 1_000_000 && timestampUs <= replayTimeUs,
    ).length

    if (message.expectedPeriodUs === null) {
      return {
        canId: message.canId,
        messageName: message.messageName,
        expectedPeriodUs: null,
        lastSeenUs,
        stale: null,
        inferredMissingFrames: null,
        frequencyHz,
      }
    }

    let inferredMissingFrames = 0
    for (let index = 1; index < timestamps.length; index += 1) {
      const deltaUs = timestamps[index]! - timestamps[index - 1]!
      inferredMissingFrames += Math.max(
        0,
        Math.floor(deltaUs / message.expectedPeriodUs) - 1,
      )
    }

    return {
      canId: message.canId,
      messageName: message.messageName,
      expectedPeriodUs: message.expectedPeriodUs,
      lastSeenUs,
      stale:
        lastSeenUs === null
          ? false
          : replayTimeUs - lastSeenUs > message.expectedPeriodUs * 2,
      inferredMissingFrames,
      frequencyHz,
    }
  })
}

export const buildHealthMetrics = (
  database: DbcDatabase,
  manifestExpectedPeriodUs: Readonly<Record<string, number>>,
  history: readonly HealthFrame[],
  replayTimeUs: number,
): readonly HealthMetric[] =>
  calculateHealthMetrics(
    createExpectedPeriodCatalog(database, manifestExpectedPeriodUs),
    history,
    replayTimeUs,
  )
