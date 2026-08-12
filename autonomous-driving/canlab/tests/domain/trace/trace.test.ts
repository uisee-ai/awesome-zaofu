// @vitest-environment node

import { readFileSync } from 'node:fs'

import { describe, expect, it } from 'vitest'

import { parseDbc } from '../../../src/domain/dbc/index.ts'
import { traceSignal } from '../../../src/domain/trace/index.ts'

const parsed = parseDbc(
  readFileSync(
    new URL('../../../public/assets/canlab-demo-v1.0.0.dbc', import.meta.url),
    'utf8',
  ),
)
if (!parsed.ok) throw new Error(parsed.error.message)
const database = parsed.database

describe('stable signal trace', () => {
  it('traces raw bytes through the exact bitfield and scaling formula', () => {
    const result = traceSignal(
      database,
      {
        can_id: '0x100',
        is_extended: false,
        dlc: 8,
        data: '803E881364320302',
      },
      {
        dbcHash: 'dbc-def456',
        logHash: 'log-abc123',
        frameSeq: 42,
        timestampUs: 1_000,
        signalName: 'EngineRpm',
      },
    )

    expect(result).toEqual({
      ok: true,
      trace: {
        kind: 'known',
        traceId: 'log-abc123/dbc-def456/42/0x100/EngineRpm',
        frame: {
          dbcHash: 'dbc-def456',
          logHash: 'log-abc123',
          frameSeq: 42,
          timestampUs: 1_000,
          canId: '0x100',
          isExtended: false,
          frameFormat: 'standard',
          dlc: 8,
          rawBytes: '803E881364320302',
        },
        signal: {
          signalId: '0x100/EngineRpm',
          messageName: 'Powertrain',
          name: 'EngineRpm',
          startBit: 0,
          length: 16,
          byteOrder: 'intel',
          signed: false,
        },
        rawInteger: 16_000,
        conversion: {
          factor: 0.25,
          offset: 0,
          formula: '16000 × 0.25 + 0 = 4000',
        },
        value: {
          physicalValue: 4_000,
          unit: 'rpm',
          displayValue: '4000 rpm',
        },
      },
    })
    expect(
      traceSignal(
        database,
        {
          can_id: '0x100',
          is_extended: false,
          dlc: 8,
          data: '803E881364320302',
        },
        {
          dbcHash: 'dbc-def456',
          logHash: 'log-abc123',
          frameSeq: 42,
          timestampUs: 1_000,
          signalName: 'EngineRpm',
        },
      ),
    ).toEqual(result)
  })

  it('preserves the enum label while retaining raw and physical values', () => {
    expect(
      traceSignal(
        database,
        {
          canId: 0x100,
          isExtended: false,
          dlc: 8,
          data: '803E881364320302',
        },
        {
          dbcHash: 'dbc-def456',
          logHash: 'log-abc123',
          frameSeq: 43,
          timestampUs: 2_000,
          signalName: 'SelectedGear',
        },
      ),
    ).toMatchObject({
      ok: true,
      trace: {
        kind: 'known',
        traceId: 'log-abc123/dbc-def456/43/0x100/SelectedGear',
        rawInteger: 3,
        conversion: {
          factor: 1,
          offset: 0,
          formula: '3 × 1 + 0 = 3',
        },
        value: {
          physicalValue: 3,
          unit: '',
          enumLabel: 'Drive',
          displayValue: 'Drive',
        },
      },
    })
  })

  it('returns an unknown-frame trace without constructing a signal chain', () => {
    const result = traceSignal(
      database,
      {
        can_id: '0x555',
        is_extended: false,
        dlc: 8,
        data: 'DEADBEEF01020304',
      },
      {
        dbcHash: 'dbc-def456',
        logHash: 'log-abc123',
        frameSeq: 121,
        timestampUs: 7_500_000,
        signalName: 'ImaginarySignal',
      },
    )

    expect(result).toEqual({
      ok: true,
      trace: {
        kind: 'unknown',
        frame: {
          dbcHash: 'dbc-def456',
          logHash: 'log-abc123',
          frameSeq: 121,
          timestampUs: 7_500_000,
          canId: '0x555',
          isExtended: false,
          frameFormat: 'standard',
          dlc: 8,
          rawBytes: 'DEADBEEF01020304',
        },
        reason: 'No standard DBC message for 0x555',
      },
    })
    if (!result.ok) throw new Error(result.error.message)
    expect(Object.keys(result.trace)).toEqual(['kind', 'frame', 'reason'])
  })
})
