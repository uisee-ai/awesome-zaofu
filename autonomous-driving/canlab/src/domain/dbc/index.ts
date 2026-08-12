export type DbcByteOrder = 'intel' | 'motorola'

export interface DbcSignal {
  name: string
  startBit: number
  length: number
  byteOrder: DbcByteOrder
  signed: boolean
  factor: number
  offset: number
  min: number
  max: number
  unit: string
  receivers: string[]
  values: Record<string, string>
}

export interface DbcMessage {
  id: number
  rawId: number
  isExtended: boolean
  name: string
  dlc: number
  transmitter: string
  cycleTimeUs?: number
  signals: DbcSignal[]
}

export interface DbcDatabase {
  version: string
  nodes: string[]
  comment?: string
  messages: DbcMessage[]
}

export type DbcParseErrorCode =
  | 'DUPLICATE_MESSAGE'
  | 'DUPLICATE_SIGNAL'
  | 'INVALID_IDENTIFIER'
  | 'INVALID_SIGNAL_LAYOUT'
  | 'INVALID_SYNTAX'
  | 'UNKNOWN_REFERENCE'
  | 'UNSUPPORTED_CONSTRUCT'

export interface DbcParseError {
  code: DbcParseErrorCode
  line: number
  message: string
}

export type DbcParseResult =
  | { ok: true; database: DbcDatabase }
  | { ok: false; error: DbcParseError }

interface PendingValues {
  rawId: number
  signalName: string
  values: Record<string, string>
  line: number
}

interface PendingCycleTime {
  rawId: number
  milliseconds: number
  line: number
}

const MAX_STANDARD_ID = 0x7ff
const EXTENDED_FLAG = 0x80000000
const MAX_EXTENDED_ID = 0x1fffffff

const fail = (
  code: DbcParseErrorCode,
  line: number,
  message: string,
): DbcParseResult => ({ ok: false, error: { code, line, message } })

const finiteNumber = (value: string): number | undefined => {
  const parsed = Number(value.trim())
  return Number.isFinite(parsed) ? parsed : undefined
}

const signalBitPositions = (
  startBit: number,
  length: number,
  byteOrder: DbcByteOrder,
): number[] => {
  if (byteOrder === 'intel') {
    return Array.from({ length }, (_, index) => startBit + index)
  }

  const positions: number[] = []
  let bit = startBit
  for (let index = 0; index < length; index += 1) {
    positions.push(bit)
    bit = bit % 8 === 0 ? bit + 15 : bit - 1
  }
  return positions
}

const normalizedIdentifier = (
  rawId: number,
): { id: number; isExtended: boolean } | undefined => {
  if (!Number.isSafeInteger(rawId) || rawId < 0 || rawId > 0xffffffff) {
    return undefined
  }
  if (rawId >= EXTENDED_FLAG) {
    const id = rawId - EXTENDED_FLAG
    return id <= MAX_EXTENDED_ID ? { id, isExtended: true } : undefined
  }
  return rawId <= MAX_STANDARD_ID
    ? { id: rawId, isExtended: false }
    : undefined
}

const parseValueDescriptions = (
  body: string,
): Record<string, string> | undefined => {
  const values: Record<string, string> = {}
  let remaining = body.trim()
  while (remaining.length > 0) {
    const match = remaining.match(/^(-?\d+)\s+"([^"]*)"\s*/)
    if (!match) return undefined
    values[match[1]] = match[2]
    remaining = remaining.slice(match[0].length)
  }
  return values
}

export const parseDbc = (source: string): DbcParseResult => {
  const database: DbcDatabase = {
    version: '',
    nodes: [],
    messages: [],
  }
  const pendingValues: PendingValues[] = []
  const pendingCycleTimes: PendingCycleTime[] = []
  let currentMessage: DbcMessage | undefined

  const lines = source.split(/\r?\n/)
  for (const [index, originalLine] of lines.entries()) {
    const lineNumber = index + 1
    const line = originalLine.trim()
    if (line.length === 0) continue

    const versionMatch = line.match(/^VERSION\s+"([^"]*)"$/)
    if (versionMatch) {
      database.version = versionMatch[1]
      continue
    }

    if (
      line === 'NS_ :' ||
      line === 'NS_DESC_' ||
      line === 'CM_' ||
      line === 'BA_DEF_' ||
      line === 'BA_' ||
      line === 'VAL_' ||
      line === 'BS_:'
    ) {
      continue
    }

    const nodesMatch = line.match(/^BU_:\s*(.*)$/)
    if (nodesMatch) {
      database.nodes = nodesMatch[1]
        .trim()
        .split(/\s+/)
        .filter(Boolean)
      continue
    }

    const messageMatch = line.match(
      /^BO_\s+(\d+)\s+([A-Za-z_][A-Za-z0-9_]*):\s+(\d+)\s+(\S+)$/,
    )
    if (messageMatch) {
      const rawId = Number(messageMatch[1])
      const identifier = normalizedIdentifier(rawId)
      if (!identifier) {
        return fail(
          'INVALID_IDENTIFIER',
          lineNumber,
          `Message identifier ${messageMatch[1]} is not a valid DBC CAN identifier`,
        )
      }
      const dlc = Number(messageMatch[3])
      if (!Number.isInteger(dlc) || dlc < 0 || dlc > 8) {
        return fail(
          'INVALID_SYNTAX',
          lineNumber,
          `Message ${messageMatch[2]} has invalid Classical CAN DLC ${messageMatch[3]}`,
        )
      }
      if (
        database.messages.some(
          (message) =>
            message.id === identifier.id &&
            message.isExtended === identifier.isExtended,
        )
      ) {
        return fail(
          'DUPLICATE_MESSAGE',
          lineNumber,
          `Message identifier ${messageMatch[1]} is duplicated`,
        )
      }
      currentMessage = {
        ...identifier,
        rawId,
        name: messageMatch[2],
        dlc,
        transmitter: messageMatch[4],
        signals: [],
      }
      database.messages.push(currentMessage)
      continue
    }

    if (line.startsWith('SG_')) {
      if (!currentMessage) {
        return fail(
          'INVALID_SYNTAX',
          lineNumber,
          'Signal declared before a message',
        )
      }
      const signalMatch = line.match(
        /^SG_\s+([A-Za-z_][A-Za-z0-9_]*)\s*(?:(M|m\d+)\s*)?:\s*(\d+)\|(\d+)@([01])([+-])\s+\(\s*([^,]+)\s*,\s*([^)]+)\s*\)\s+\[\s*([^|]+)\s*\|\s*([^\]]+)\s*\]\s+"([^"]*)"\s+(.+)$/,
      )
      if (!signalMatch) {
        return fail(
          'INVALID_SYNTAX',
          lineNumber,
          'Signal declaration does not match the supported DBC subset',
        )
      }
      if (signalMatch[2]) {
        return fail(
          'UNSUPPORTED_CONSTRUCT',
          lineNumber,
          'Multiplexed signals are not supported',
        )
      }

      const startBit = Number(signalMatch[3])
      const length = Number(signalMatch[4])
      const factor = finiteNumber(signalMatch[7])
      const offset = finiteNumber(signalMatch[8])
      const min = finiteNumber(signalMatch[9])
      const max = finiteNumber(signalMatch[10])
      if (
        factor === undefined ||
        offset === undefined ||
        min === undefined ||
        max === undefined ||
        !Number.isInteger(startBit) ||
        !Number.isInteger(length) ||
        length < 1 ||
        length > 64 ||
        min > max
      ) {
        return fail(
          'INVALID_SYNTAX',
          lineNumber,
          `Signal ${signalMatch[1]} has invalid numeric metadata`,
        )
      }

      const byteOrder: DbcByteOrder =
        signalMatch[5] === '1' ? 'intel' : 'motorola'
      const positions = signalBitPositions(startBit, length, byteOrder)
      const payloadBits = currentMessage.dlc * 8
      if (positions.some((bit) => bit < 0 || bit >= payloadBits)) {
        return fail(
          'INVALID_SIGNAL_LAYOUT',
          lineNumber,
          `Signal ${signalMatch[1]} uses bits outside the ${currentMessage.dlc}-byte message payload`,
        )
      }
      if (
        currentMessage.signals.some((signal) =>
          signalBitPositions(
            signal.startBit,
            signal.length,
            signal.byteOrder,
          ).some((bit) => positions.includes(bit)),
        )
      ) {
        return fail(
          'INVALID_SIGNAL_LAYOUT',
          lineNumber,
          `Signal ${signalMatch[1]} overlaps another signal`,
        )
      }
      if (
        currentMessage.signals.some(
          (signal) => signal.name === signalMatch[1],
        )
      ) {
        return fail(
          'DUPLICATE_SIGNAL',
          lineNumber,
          `Signal ${signalMatch[1]} is duplicated in message ${currentMessage.name}`,
        )
      }

      currentMessage.signals.push({
        name: signalMatch[1],
        startBit,
        length,
        byteOrder,
        signed: signalMatch[6] === '-',
        factor,
        offset,
        min,
        max,
        unit: signalMatch[11],
        receivers: signalMatch[12]
          .split(',')
          .map((receiver) => receiver.trim())
          .filter(Boolean),
        values: {},
      })
      continue
    }

    const valuesMatch = line.match(
      /^VAL_\s+(\d+)\s+([A-Za-z_][A-Za-z0-9_]*)\s+(.+)\s*;$/,
    )
    if (valuesMatch) {
      const values = parseValueDescriptions(valuesMatch[3])
      if (!values) {
        return fail(
          'INVALID_SYNTAX',
          lineNumber,
          'Value description does not match the supported DBC subset',
        )
      }
      pendingValues.push({
        rawId: Number(valuesMatch[1]),
        signalName: valuesMatch[2],
        values,
        line: lineNumber,
      })
      continue
    }

    if (
      /^BA_DEF_\s+BO_\s+"GenMsgCycleTime"\s+INT\s+\d+\s+\d+;$/.test(
        line,
      ) ||
      /^BA_DEF_DEF_\s+"GenMsgCycleTime"\s+\d+;$/.test(line)
    ) {
      continue
    }

    const cycleMatch = line.match(
      /^BA_\s+"GenMsgCycleTime"\s+BO_\s+(\d+)\s+(\d+);$/,
    )
    if (cycleMatch) {
      pendingCycleTimes.push({
        rawId: Number(cycleMatch[1]),
        milliseconds: Number(cycleMatch[2]),
        line: lineNumber,
      })
      continue
    }

    const commentMatch = line.match(/^CM_\s+"([^"]*)";$/)
    if (commentMatch) {
      database.comment = commentMatch[1]
      continue
    }

    return fail(
      'UNSUPPORTED_CONSTRUCT',
      lineNumber,
      `Unsupported DBC statement: ${line.split(/\s+/)[0]}`,
    )
  }

  for (const pending of pendingValues) {
    const message = database.messages.find(
      (candidate) => candidate.rawId === pending.rawId,
    )
    const signal = message?.signals.find(
      (candidate) => candidate.name === pending.signalName,
    )
    if (!message || !signal) {
      return fail(
        'UNKNOWN_REFERENCE',
        pending.line,
        `Value description references unknown signal ${pending.rawId}:${pending.signalName}`,
      )
    }
    signal.values = pending.values
  }

  for (const pending of pendingCycleTimes) {
    const message = database.messages.find(
      (candidate) => candidate.rawId === pending.rawId,
    )
    if (!message) {
      return fail(
        'UNKNOWN_REFERENCE',
        pending.line,
        `Cycle time references unknown message ${pending.rawId}`,
      )
    }
    message.cycleTimeUs = pending.milliseconds * 1_000
  }

  return { ok: true, database }
}
