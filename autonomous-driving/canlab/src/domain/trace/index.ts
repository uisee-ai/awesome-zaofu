import type { DbcByteOrder, DbcDatabase } from '../dbc/index.ts'
import {
  canonicalizeFrame,
  createSignalId,
  decodeFrame,
  formatCanId,
  type CanFrame,
  type DecodeErrorCode,
} from '../decode/index.ts'

export interface SignalTraceRequest {
  logHash: string
  dbcHash: string
  frameSeq: number
  timestampUs: number
  signalName: string
}

export interface TraceFrameIdentity {
  logHash: string
  dbcHash: string
  frameSeq: number
  timestampUs: number
  canId: string
  isExtended: boolean
  frameFormat: 'standard' | 'extended'
  dlc: number
  rawBytes: string
}

export interface KnownSignalTrace {
  kind: 'known'
  traceId: string
  frame: TraceFrameIdentity
  signal: {
    signalId: string
    messageName: string
    name: string
    startBit: number
    length: number
    byteOrder: DbcByteOrder
    signed: boolean
  }
  rawInteger: number
  conversion: {
    factor: number
    offset: number
    formula: string
  }
  value: {
    physicalValue: number
    unit: string
    enumLabel?: string
    displayValue: string
  }
}

export interface UnknownFrameTrace {
  kind: 'unknown'
  frame: TraceFrameIdentity
  reason: string
}

export type SignalTrace = KnownSignalTrace | UnknownFrameTrace

export type TraceErrorCode =
  | DecodeErrorCode
  | 'INVALID_PROVENANCE'
  | 'UNKNOWN_SIGNAL'

export type TraceResult =
  | { ok: true; trace: SignalTrace }
  | { ok: false; error: { code: TraceErrorCode; message: string } }

export const traceSignal = (
  database: DbcDatabase,
  frame: CanFrame,
  request: SignalTraceRequest,
): TraceResult => {
  if (
    request.logHash.length === 0 ||
    request.dbcHash.length === 0 ||
    !Number.isSafeInteger(request.frameSeq) ||
    request.frameSeq < 0 ||
    !Number.isSafeInteger(request.timestampUs) ||
    request.timestampUs < 0
  ) {
    return {
      ok: false,
      error: {
        code: 'INVALID_PROVENANCE',
        message:
          'Trace provenance requires DBC/log hashes plus non-negative frame sequence and timestamp',
      },
    }
  }

  const canonical = canonicalizeFrame(frame)
  if (!canonical.ok) return canonical
  const frameIdentity: TraceFrameIdentity = {
    logHash: request.logHash,
    dbcHash: request.dbcHash,
    frameSeq: request.frameSeq,
    timestampUs: request.timestampUs,
    canId: formatCanId(
      canonical.frame.canId,
      canonical.frame.isExtended,
    ),
    isExtended: canonical.frame.isExtended,
    frameFormat: canonical.frame.isExtended ? 'extended' : 'standard',
    dlc: canonical.frame.dlc,
    rawBytes: canonical.frame.dataHex,
  }

  const decoded = decodeFrame(database, frame)
  if (!decoded.ok) {
    return decoded.error.code === 'UNKNOWN_MESSAGE'
      ? {
          ok: true,
          trace: {
            kind: 'unknown',
            frame: frameIdentity,
            reason: decoded.error.message,
          },
        }
      : decoded
  }

  const message = database.messages.find(
    (candidate) =>
      candidate.id === decoded.message.id &&
      candidate.isExtended === decoded.message.isExtended,
  )
  const signal = message?.signals.find(
    (candidate) => candidate.name === request.signalName,
  )
  const decodedSignal = decoded.signals.find(
    (candidate) => candidate.name === request.signalName,
  )
  if (!message || !signal || !decodedSignal) {
    return {
      ok: false,
      error: {
        code: 'UNKNOWN_SIGNAL',
        message: `Signal ${request.signalName} not found in DBC message ${decoded.message.name}`,
      },
    }
  }

  const signalId = createSignalId(message, signal.name)
  return {
    ok: true,
    trace: {
      kind: 'known',
      traceId: `${request.logHash}/${request.dbcHash}/${request.frameSeq}/${signalId}`,
      frame: frameIdentity,
      signal: {
        signalId,
        messageName: message.name,
        name: signal.name,
        startBit: signal.startBit,
        length: signal.length,
        byteOrder: signal.byteOrder,
        signed: signal.signed,
      },
      rawInteger: decodedSignal.rawValue,
      conversion: {
        factor: signal.factor,
        offset: signal.offset,
        formula: `${String(decodedSignal.rawValue)} × ${String(signal.factor)} + ${String(signal.offset)} = ${String(decodedSignal.physicalValue)}`,
      },
      value: {
        physicalValue: decodedSignal.physicalValue,
        unit: decodedSignal.unit,
        ...(decodedSignal.enumLabel === undefined
          ? {}
          : { enumLabel: decodedSignal.enumLabel }),
        displayValue: decodedSignal.displayValue,
      },
    },
  }
}
