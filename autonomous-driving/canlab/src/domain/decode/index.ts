import type { DbcDatabase, DbcMessage, DbcSignal } from '../dbc/index.ts'

export interface CamelCaseCanFrame {
  canId: number | string
  isExtended: boolean
  dlc: number
  data: string | Uint8Array
}

export interface SnakeCaseCanFrame {
  can_id: number | string
  is_extended: boolean
  dlc: number
  data: string | Uint8Array
}

export type CanFrame = CamelCaseCanFrame | SnakeCaseCanFrame

export interface DecodedSignal {
  signalId: string
  name: string
  rawValue: number
  physicalValue: number
  unit: string
  enumLabel?: string
  displayValue: string
}

export interface DecodedMessageIdentity {
  id: number
  canId: string
  isExtended: boolean
  name: string
  dlc: number
}

export interface DecodedFrame {
  ok: true
  message: DecodedMessageIdentity
  dataHex: string
  signals: DecodedSignal[]
}

export type DecodeErrorCode =
  | 'INVALID_FRAME'
  | 'UNKNOWN_MESSAGE'
  | 'UNSAFE_NUMERIC_VALUE'

export interface DecodeError {
  code: DecodeErrorCode
  message: string
}

export type DecodeResult = DecodedFrame | { ok: false; error: DecodeError }

export interface CanonicalCanFrame {
  canId: number
  isExtended: boolean
  dlc: number
  bytes: Uint8Array
  dataHex: string
}

const MAX_STANDARD_ID = 0x7ff
const MAX_EXTENDED_ID = 0x1fffffff
const MAX_SAFE_BIGINT = BigInt(Number.MAX_SAFE_INTEGER)
const MIN_SAFE_BIGINT = BigInt(Number.MIN_SAFE_INTEGER)

const failure = (code: DecodeErrorCode, message: string): DecodeResult => ({
  ok: false,
  error: { code, message },
})

export const formatCanId = (canId: number, isExtended: boolean): string =>
  `0x${canId
    .toString(16)
    .toUpperCase()
    .padStart(isExtended ? 8 : 1, '0')}`

export const createSignalId = (
  message: Pick<DbcMessage, 'id' | 'isExtended'>,
  signalName: string,
): string => `${formatCanId(message.id, message.isExtended)}/${signalName}`

const numericCanId = (value: number | string): number | undefined => {
  if (typeof value === 'number') {
    return Number.isSafeInteger(value) ? value : undefined
  }
  if (!/^0x[\da-f]+$/i.test(value)) return undefined
  const parsed = Number.parseInt(value.slice(2), 16)
  return Number.isSafeInteger(parsed) ? parsed : undefined
}

const frameBytes = (data: string | Uint8Array): Uint8Array | undefined => {
  if (data instanceof Uint8Array) return Uint8Array.from(data)
  if (data.length % 2 !== 0 || !/^[\da-f]*$/i.test(data)) return undefined
  return Uint8Array.from(
    Array.from({ length: data.length / 2 }, (_, index) =>
      Number.parseInt(data.slice(index * 2, index * 2 + 2), 16),
    ),
  )
}

const normalizeFrame = (
  frame: CanFrame,
): CanonicalCanFrame | { message: string } => {
  const isSnakeCase = 'can_id' in frame
  const rawCanId = isSnakeCase ? frame.can_id : frame.canId
  const isExtended = isSnakeCase ? frame.is_extended : frame.isExtended
  const canId = numericCanId(rawCanId)
  if (
    canId === undefined ||
    canId < 0 ||
    canId > (isExtended ? MAX_EXTENDED_ID : MAX_STANDARD_ID)
  ) {
    return { message: `Frame has invalid ${isExtended ? 'extended' : 'standard'} CAN identifier ${String(rawCanId)}` }
  }
  if (!Number.isInteger(frame.dlc) || frame.dlc < 0 || frame.dlc > 8) {
    return { message: `Frame ${formatCanId(canId, isExtended)} has invalid DLC ${String(frame.dlc)}` }
  }
  const bytes = frameBytes(frame.data)
  if (!bytes) {
    return {
      message: `Frame ${formatCanId(canId, isExtended)} data is not an even-length hexadecimal byte string`,
    }
  }
  if (bytes.length !== frame.dlc) {
    return {
      message: `Frame ${formatCanId(canId, isExtended)} declares DLC ${frame.dlc} but contains ${bytes.length} bytes`,
    }
  }
  return {
    canId,
    isExtended,
    dlc: frame.dlc,
    bytes,
    dataHex: Array.from(bytes, (byte) =>
      byte.toString(16).toUpperCase().padStart(2, '0'),
    ).join(''),
  }
}

export type CanonicalFrameResult =
  | { ok: true; frame: CanonicalCanFrame }
  | { ok: false; error: DecodeError }

export const canonicalizeFrame = (frame: CanFrame): CanonicalFrameResult => {
  const normalized = normalizeFrame(frame)
  return 'message' in normalized
    ? {
        ok: false,
        error: { code: 'INVALID_FRAME', message: normalized.message },
      }
    : { ok: true, frame: normalized }
}

const unsignedRawValue = (signal: DbcSignal, bytes: Uint8Array): bigint => {
  let value = 0n
  if (signal.byteOrder === 'intel') {
    for (let index = 0; index < signal.length; index += 1) {
      const bit = signal.startBit + index
      const set = (bytes[Math.floor(bit / 8)] >> (bit % 8)) & 1
      value |= BigInt(set) << BigInt(index)
    }
    return value
  }

  let bit = signal.startBit
  for (let index = 0; index < signal.length; index += 1) {
    const set = (bytes[Math.floor(bit / 8)] >> (bit % 8)) & 1
    value = (value << 1n) | BigInt(set)
    bit = bit % 8 === 0 ? bit + 15 : bit - 1
  }
  return value
}

const signedRawValue = (signal: DbcSignal, unsigned: bigint): bigint => {
  if (!signal.signed) return unsigned
  const signBit = 1n << BigInt(signal.length - 1)
  return unsigned & signBit ? unsigned - (1n << BigInt(signal.length)) : unsigned
}

const decodeSignal = (
  message: DbcMessage,
  signal: DbcSignal,
  bytes: Uint8Array,
): DecodedSignal | DecodeError => {
  const raw = signedRawValue(signal, unsignedRawValue(signal, bytes))
  if (raw > MAX_SAFE_BIGINT || raw < MIN_SAFE_BIGINT) {
    return {
      code: 'UNSAFE_NUMERIC_VALUE',
      message: `Signal ${createSignalId(message, signal.name)} exceeds JavaScript safe integer range`,
    }
  }
  const rawValue = Number(raw)
  const physicalValue = rawValue * signal.factor + signal.offset
  if (!Number.isFinite(physicalValue)) {
    return {
      code: 'UNSAFE_NUMERIC_VALUE',
      message: `Signal ${createSignalId(message, signal.name)} has a non-finite physical value`,
    }
  }

  const enumLabel = signal.values[String(rawValue)]
  const displayValue =
    enumLabel ??
    (signal.unit.length > 0
      ? `${String(physicalValue)} ${signal.unit}`
      : String(physicalValue))
  return {
    signalId: createSignalId(message, signal.name),
    name: signal.name,
    rawValue,
    physicalValue,
    unit: signal.unit,
    ...(enumLabel === undefined ? {} : { enumLabel }),
    displayValue,
  }
}

export const decodeFrame = (
  database: DbcDatabase,
  frame: CanFrame,
): DecodeResult => {
  const canonical = canonicalizeFrame(frame)
  if (!canonical.ok) return canonical
  const normalized = canonical.frame

  const message = database.messages.find(
    (candidate) =>
      candidate.id === normalized.canId &&
      candidate.isExtended === normalized.isExtended,
  )
  if (!message) {
    return failure(
      'UNKNOWN_MESSAGE',
      `No ${normalized.isExtended ? 'extended' : 'standard'} DBC message for ${formatCanId(normalized.canId, normalized.isExtended)}`,
    )
  }
  if (message.dlc !== normalized.dlc) {
    return failure(
      'INVALID_FRAME',
      `Frame ${formatCanId(normalized.canId, normalized.isExtended)} DLC ${normalized.dlc} does not match DBC message DLC ${message.dlc}`,
    )
  }

  const signals: DecodedSignal[] = []
  for (const signal of message.signals) {
    const decoded = decodeSignal(message, signal, normalized.bytes)
    if ('code' in decoded) return { ok: false, error: decoded }
    signals.push(decoded)
  }

  return {
    ok: true,
    message: {
      id: message.id,
      canId: formatCanId(message.id, message.isExtended),
      isExtended: message.isExtended,
      name: message.name,
      dlc: message.dlc,
    },
    dataHex: normalized.dataHex,
    signals,
  }
}
