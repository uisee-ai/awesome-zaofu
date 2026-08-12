// @vitest-environment node

import { readFileSync } from 'node:fs'

import { describe, expect, it } from 'vitest'

import {
  CanLogParseError,
  parseCanLogNdjson,
} from '../../../src/domain/log/index.ts'

const bundledLog = readFileSync(
  new URL('../../../public/assets/drive-cycle-v1.ndjson', import.meta.url),
  'utf8',
)

const metadataRecord = {
  type: 'metadata',
  schema: 'canlab.drive-cycle',
  schema_version: '1.0.0',
  seed: 20260804,
  scenario: 'six-phase-demo',
  time_base: 'integer_microseconds',
  dbc_asset: 'canlab-demo-v1.0.0.dbc',
  dbc_version: '1.0.0',
  phases: [
    { name: 'start', start_us: 0, end_us: 999_999 },
    { name: 'acceleration', start_us: 1_000_000, end_us: 3_999_999 },
    { name: 'cruise', start_us: 4_000_000, end_us: 6_999_999 },
    { name: 'turn', start_us: 7_000_000, end_us: 8_999_999 },
    { name: 'deceleration', start_us: 9_000_000, end_us: 10_999_999 },
    { name: 'stop', start_us: 11_000_000, end_us: 12_000_000 },
  ],
  expected_period_us: {
    '0x100': 100_000,
    '0x200': 200_000,
    '0x00000300': 1_000_000,
  },
} as const

describe('parseCanLogNdjson', () => {
  it('loads the bundled log with exact metadata and frame boundaries', () => {
    const parsed = parseCanLogNdjson(bundledLog)

    expect(parsed.metadata).toEqual(metadataRecord)
    expect(parsed.frames).toHaveLength(195)
    expect(parsed.startTimeUs).toBe(0)
    expect(parsed.endTimeUs).toBe(12_000_000)
    expect(parsed.frames[0]).toEqual({
      type: 'frame',
      seq: 0,
      timestamp_us: 0,
      phase: 'start',
      can_id: '0x100',
      is_extended: false,
      dlc: 8,
      data: '600C000000280000',
    })
    expect(parsed.frames.at(-1)).toEqual({
      type: 'frame',
      seq: 194,
      timestamp_us: 12_000_000,
      phase: 'stop',
      can_id: '0x00000300',
      is_extended: true,
      dlc: 8,
      data: '3C7D000000000000',
    })
    expect(parsed.frames.find((frame) => frame.can_id === '0x555')).toEqual({
      type: 'frame',
      seq: 121,
      timestamp_us: 7_500_000,
      phase: 'turn',
      can_id: '0x555',
      is_extended: false,
      dlc: 8,
      data: 'DEADBEEF01020304',
    })
  })

  it('orders an equal-timestamp group by original seq without renumbering', () => {
    const records = [
      metadataRecord,
      {
        type: 'frame',
        seq: 9,
        timestamp_us: 10,
        phase: 'start',
        can_id: '0x101',
        is_extended: false,
        dlc: 1,
        data: '09',
      },
      {
        type: 'frame',
        seq: 3,
        timestamp_us: 10,
        phase: 'start',
        can_id: '0x101',
        is_extended: false,
        dlc: 1,
        data: '03',
      },
    ]

    const parsed = parseCanLogNdjson(
      `${records.map((record) => JSON.stringify(record)).join('\n')}\n`,
    )

    expect(parsed.frames.map((frame) => frame.seq)).toEqual([3, 9])
    expect(parsed.frames.map((frame) => frame.data)).toEqual(['03', '09'])
  })

  it.each([
    {
      name: 'requires metadata first',
      content: '{"type":"frame"}\n',
      code: 'METADATA_REQUIRED',
      line: 1,
    },
    {
      name: 'rejects duplicate sequence numbers',
      content: `${JSON.stringify(metadataRecord)}\n${JSON.stringify({ type: 'frame', seq: 1, timestamp_us: 0, phase: 'start', can_id: '0x100', is_extended: false, dlc: 1, data: '00' })}\n${JSON.stringify({ type: 'frame', seq: 1, timestamp_us: 1, phase: 'start', can_id: '0x100', is_extended: false, dlc: 1, data: '01' })}\n`,
      code: 'DUPLICATE_SEQ',
      line: 3,
    },
    {
      name: 'rejects fractional event time',
      content: `${JSON.stringify(metadataRecord)}\n${JSON.stringify({ type: 'frame', seq: 1, timestamp_us: 0.5, phase: 'start', can_id: '0x100', is_extended: false, dlc: 1, data: '00' })}\n`,
      code: 'INVALID_TIMESTAMP',
      line: 2,
    },
    {
      name: 'rejects data that does not match DLC',
      content: `${JSON.stringify(metadataRecord)}\n${JSON.stringify({ type: 'frame', seq: 1, timestamp_us: 0, phase: 'start', can_id: '0x100', is_extended: false, dlc: 2, data: '00' })}\n`,
      code: 'INVALID_DATA',
      line: 2,
    },
    {
      name: 'rejects interior blank records',
      content: `${JSON.stringify(metadataRecord)}\n\n`,
      code: 'BLANK_RECORD',
      line: 2,
    },
  ] as const)('$name with a stable error code', ({ content, code, line }) => {
    expect(() => parseCanLogNdjson(content)).toThrowError(
      expect.objectContaining<Partial<CanLogParseError>>({ code, line }),
    )
  })
})
