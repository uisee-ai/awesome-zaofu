export type CanLogParseErrorCode =
  | 'EMPTY_LOG'
  | 'BLANK_RECORD'
  | 'INVALID_JSON'
  | 'METADATA_REQUIRED'
  | 'INVALID_METADATA'
  | 'FRAME_REQUIRED'
  | 'INVALID_RECORD_TYPE'
  | 'INVALID_FRAME'
  | 'DUPLICATE_SEQ'
  | 'INVALID_TIMESTAMP'
  | 'INVALID_CAN_ID'
  | 'INVALID_DLC'
  | 'INVALID_DATA'
  | 'INVALID_PHASE'

export class CanLogParseError extends Error {
  readonly code: CanLogParseErrorCode
  readonly line: number

  constructor(code: CanLogParseErrorCode, line: number, message: string) {
    super(`${code} at line ${line}: ${message}`)
    this.name = 'CanLogParseError'
    this.code = code
    this.line = line
  }
}

export interface CanLogPhase {
  readonly name: string
  readonly start_us: number
  readonly end_us: number
}

export interface CanLogMetadata {
  readonly type: 'metadata'
  readonly schema: string
  readonly schema_version: string
  readonly seed: number
  readonly scenario: string
  readonly time_base: 'integer_microseconds'
  readonly dbc_asset: string
  readonly dbc_version: string
  readonly phases: readonly CanLogPhase[]
  readonly expected_period_us: Readonly<Record<string, number>>
}

export interface CanLogFrame {
  readonly type: 'frame'
  readonly seq: number
  readonly timestamp_us: number
  readonly phase: string
  readonly can_id: string
  readonly is_extended: boolean
  readonly dlc: number
  readonly data: string
}

export interface ParsedCanLog {
  readonly metadata: CanLogMetadata
  readonly frames: readonly CanLogFrame[]
  readonly startTimeUs: number
  readonly endTimeUs: number
}

const METADATA_KEYS = [
  'type',
  'schema',
  'schema_version',
  'seed',
  'scenario',
  'time_base',
  'dbc_asset',
  'dbc_version',
  'phases',
  'expected_period_us',
] as const

const FRAME_KEYS = [
  'type',
  'seq',
  'timestamp_us',
  'phase',
  'can_id',
  'is_extended',
  'dlc',
  'data',
] as const

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)

const hasExactKeys = (
  value: Record<string, unknown>,
  expected: readonly string[],
) => {
  const actual = Object.keys(value).sort()
  const sortedExpected = [...expected].sort()
  return (
    actual.length === sortedExpected.length &&
    actual.every((key, index) => key === sortedExpected[index])
  )
}

const isNonNegativeSafeInteger = (value: unknown): value is number =>
  typeof value === 'number' && Number.isSafeInteger(value) && value >= 0

const parseJsonRecord = (line: string, lineNumber: number) => {
  try {
    return JSON.parse(line) as unknown
  } catch {
    throw new CanLogParseError(
      'INVALID_JSON',
      lineNumber,
      'record is not valid JSON',
    )
  }
}

const parseMetadata = (value: unknown): CanLogMetadata => {
  if (!isRecord(value) || value.type !== 'metadata') {
    throw new CanLogParseError(
      'METADATA_REQUIRED',
      1,
      'the first record must be metadata',
    )
  }
  if (!hasExactKeys(value, METADATA_KEYS)) {
    throw new CanLogParseError(
      'INVALID_METADATA',
      1,
      'metadata fields do not match schema v1',
    )
  }
  if (
    typeof value.schema !== 'string' ||
    typeof value.schema_version !== 'string' ||
    !isNonNegativeSafeInteger(value.seed) ||
    typeof value.scenario !== 'string' ||
    value.time_base !== 'integer_microseconds' ||
    typeof value.dbc_asset !== 'string' ||
    typeof value.dbc_version !== 'string' ||
    !Array.isArray(value.phases) ||
    !isRecord(value.expected_period_us)
  ) {
    throw new CanLogParseError(
      'INVALID_METADATA',
      1,
      'metadata contains an invalid field value',
    )
  }

  const phaseNames = new Set<string>()
  let previousEnd = -1
  const phases = value.phases.map((phase) => {
    if (
      !isRecord(phase) ||
      !hasExactKeys(phase, ['name', 'start_us', 'end_us']) ||
      typeof phase.name !== 'string' ||
      phase.name.length === 0 ||
      !isNonNegativeSafeInteger(phase.start_us) ||
      !isNonNegativeSafeInteger(phase.end_us) ||
      phase.start_us > phase.end_us ||
      phase.start_us <= previousEnd ||
      phaseNames.has(phase.name)
    ) {
      throw new CanLogParseError(
        'INVALID_METADATA',
        1,
        'phase windows must be unique, ordered integer ranges',
      )
    }
    phaseNames.add(phase.name)
    previousEnd = phase.end_us
    return {
      name: phase.name,
      start_us: phase.start_us,
      end_us: phase.end_us,
    }
  })
  if (phases.length === 0) {
    throw new CanLogParseError(
      'INVALID_METADATA',
      1,
      'at least one phase is required',
    )
  }

  const expectedPeriodUs: Record<string, number> = {}
  for (const [canId, period] of Object.entries(value.expected_period_us)) {
    if (!isNonNegativeSafeInteger(period) || period === 0) {
      throw new CanLogParseError(
        'INVALID_METADATA',
        1,
        `expected period for ${canId} must be a positive integer`,
      )
    }
    expectedPeriodUs[canId] = period
  }

  return {
    type: 'metadata',
    schema: value.schema,
    schema_version: value.schema_version,
    seed: value.seed,
    scenario: value.scenario,
    time_base: value.time_base,
    dbc_asset: value.dbc_asset,
    dbc_version: value.dbc_version,
    phases,
    expected_period_us: expectedPeriodUs,
  }
}

const parseFrame = (
  value: unknown,
  line: number,
  metadata: CanLogMetadata,
): CanLogFrame => {
  if (!isRecord(value)) {
    throw new CanLogParseError('INVALID_FRAME', line, 'frame must be an object')
  }
  if (value.type !== 'frame') {
    throw new CanLogParseError(
      'INVALID_RECORD_TYPE',
      line,
      'only frame records may follow metadata',
    )
  }
  if (!hasExactKeys(value, FRAME_KEYS)) {
    throw new CanLogParseError(
      'INVALID_FRAME',
      line,
      'frame fields do not match schema v1',
    )
  }
  if (!isNonNegativeSafeInteger(value.seq)) {
    throw new CanLogParseError(
      'INVALID_FRAME',
      line,
      'seq must be a non-negative safe integer',
    )
  }
  if (!isNonNegativeSafeInteger(value.timestamp_us)) {
    throw new CanLogParseError(
      'INVALID_TIMESTAMP',
      line,
      'timestamp_us must be a non-negative safe integer',
    )
  }
  const timestampUs = value.timestamp_us
  if (typeof value.is_extended !== 'boolean' || typeof value.can_id !== 'string') {
    throw new CanLogParseError(
      'INVALID_CAN_ID',
      line,
      'CAN identifier fields are invalid',
    )
  }
  const idPattern = value.is_extended
    ? /^0x[0-9A-F]{8}$/
    : /^0x[0-9A-F]{3}$/
  const numericId = Number.parseInt(value.can_id.slice(2), 16)
  const maximumId = value.is_extended ? 0x1fff_ffff : 0x7ff
  if (!idPattern.test(value.can_id) || numericId > maximumId) {
    throw new CanLogParseError(
      'INVALID_CAN_ID',
      line,
      'CAN identifier does not match its frame format',
    )
  }
  if (
    !isNonNegativeSafeInteger(value.dlc) ||
    value.dlc > 8
  ) {
    throw new CanLogParseError(
      'INVALID_DLC',
      line,
      'Classical CAN DLC must be an integer from 0 through 8',
    )
  }
  if (
    typeof value.data !== 'string' ||
    !/^[0-9A-F]*$/.test(value.data) ||
    value.data.length !== value.dlc * 2
  ) {
    throw new CanLogParseError(
      'INVALID_DATA',
      line,
      'data must be uppercase hexadecimal matching DLC',
    )
  }
  if (typeof value.phase !== 'string') {
    throw new CanLogParseError('INVALID_PHASE', line, 'phase must be a string')
  }
  const matchingPhase = metadata.phases.find(
    (phase) =>
      timestampUs >= phase.start_us && timestampUs <= phase.end_us,
  )
  if (matchingPhase?.name !== value.phase) {
    throw new CanLogParseError(
      'INVALID_PHASE',
      line,
      'phase does not match the timestamp window',
    )
  }

  return {
    type: 'frame',
    seq: value.seq,
    timestamp_us: timestampUs,
    phase: value.phase,
    can_id: value.can_id,
    is_extended: value.is_extended,
    dlc: value.dlc,
    data: value.data,
  }
}

export const parseCanLogNdjson = (content: string): ParsedCanLog => {
  const lines = content.split('\n')
  if (lines.at(-1) === '') {
    lines.pop()
  }
  if (lines.length === 0 || (lines.length === 1 && lines[0] === '')) {
    throw new CanLogParseError('EMPTY_LOG', 1, 'log is empty')
  }

  for (const [index, line] of lines.entries()) {
    if (line.trim().length === 0) {
      throw new CanLogParseError(
        'BLANK_RECORD',
        index + 1,
        'blank NDJSON records are not allowed',
      )
    }
  }

  const metadata = parseMetadata(parseJsonRecord(lines[0]!, 1))
  if (lines.length === 1) {
    throw new CanLogParseError('FRAME_REQUIRED', 2, 'at least one frame is required')
  }

  const sequences = new Set<number>()
  const frames = lines.slice(1).map((line, index) => {
    const lineNumber = index + 2
    const frame = parseFrame(parseJsonRecord(line, lineNumber), lineNumber, metadata)
    if (sequences.has(frame.seq)) {
      throw new CanLogParseError(
        'DUPLICATE_SEQ',
        lineNumber,
        `seq ${frame.seq} appears more than once`,
      )
    }
    sequences.add(frame.seq)
    return frame
  })

  frames.sort(
    (left, right) =>
      left.timestamp_us - right.timestamp_us || left.seq - right.seq,
  )

  return {
    metadata,
    frames,
    startTimeUs: frames[0]!.timestamp_us,
    endTimeUs: frames.at(-1)!.timestamp_us,
  }
}
