// @vitest-environment node

import { describe, expect, it } from 'vitest'

import type { DbcDatabase } from '../../../src/domain/dbc/index.ts'
import {
  PeriodMirrorError,
  calculateHealthMetrics,
  createExpectedPeriodCatalog,
  type HealthFrame,
} from '../../../src/domain/health/index.ts'

const database: DbcDatabase = {
  version: 'test',
  nodes: ['CANLAB'],
  messages: [
    {
      id: 0x100,
      rawId: 0x100,
      isExtended: false,
      name: 'Powertrain',
      dlc: 8,
      transmitter: 'CANLAB',
      cycleTimeUs: 100_000,
      signals: [],
    },
    {
      id: 0x200,
      rawId: 0x200,
      isExtended: false,
      name: 'WithoutPeriod',
      dlc: 8,
      transmitter: 'CANLAB',
      signals: [],
    },
  ],
}

const frame = (
  seq: number,
  timestampUs: number,
  canId = '0x100',
): HealthFrame => ({
  seq,
  timestamp_us: timestampUs,
  can_id: canId,
  is_extended: false,
  dlc: 8,
  data: '0000000000000000',
})

describe('DBC-owned expected period catalog', () => {
  it('uses DBC cycles as the canonical source and permits periodless messages', () => {
    expect(createExpectedPeriodCatalog(database, { '0x100': 100_000 })).toEqual({
      messages: [
        {
          canId: '0x100',
          isExtended: false,
          messageName: 'Powertrain',
          expectedPeriodUs: 100_000,
        },
        {
          canId: '0x200',
          isExtended: false,
          messageName: 'WithoutPeriod',
          expectedPeriodUs: null,
        },
      ],
    })
  })

  it.each([
    [{ '0x100': 200_000 }, '0x100'],
    [{}, '0x100'],
    [{ '0x100': 100_000, '0x200': 50_000 }, '0x200'],
    [{ '0x100': 100_000, '0x555': 50_000 }, '0x555'],
  ])('fails closed when the manifest is not an exact DBC mirror', (manifest, canId) => {
    try {
      createExpectedPeriodCatalog(database, manifest)
      throw new Error('expected period mirror validation to fail')
    } catch (error) {
      expect(error).toBeInstanceOf(PeriodMirrorError)
      expect(error).toMatchObject({
        code: 'PERIOD_MIRROR_MISMATCH',
        canId,
      })
    }
  })
})

describe('event-time HealthMetrics', () => {
  const catalog = createExpectedPeriodCatalog(database, { '0x100': 100_000 })

  it('applies strict stale, inferred-missing and frequency window boundaries', () => {
    const history = [
      frame(0, 100_000),
      frame(1, 200_000),
      frame(2, 400_000),
      frame(3, 1_100_000),
    ]

    expect(calculateHealthMetrics(catalog, history, 400_000)[0]).toEqual({
      canId: '0x100',
      messageName: 'Powertrain',
      expectedPeriodUs: 100_000,
      lastSeenUs: 400_000,
      stale: false,
      inferredMissingFrames: 1,
      frequencyHz: 3,
    })
    expect(calculateHealthMetrics(catalog, history, 600_000)[0]).toMatchObject({
      stale: false,
      lastSeenUs: 400_000,
    })
    expect(calculateHealthMetrics(catalog, history, 600_001)[0]).toMatchObject({
      stale: true,
      lastSeenUs: 400_000,
    })
    expect(calculateHealthMetrics(catalog, history, 1_100_000)[0]).toMatchObject({
      frequencyHz: 3,
    })
  })

  it('rebuilds only from history at or before seek time and reports N/A without P', () => {
    const history = [
      frame(3, 400_000),
      frame(1, 200_000),
      frame(0, 100_000),
      frame(2, 300_000, '0x200'),
    ]

    expect(calculateHealthMetrics(catalog, history, 250_000)).toEqual([
      {
        canId: '0x100',
        messageName: 'Powertrain',
        expectedPeriodUs: 100_000,
        lastSeenUs: 200_000,
        stale: false,
        inferredMissingFrames: 0,
        frequencyHz: 2,
      },
      {
        canId: '0x200',
        messageName: 'WithoutPeriod',
        expectedPeriodUs: null,
        lastSeenUs: null,
        stale: null,
        inferredMissingFrames: null,
        frequencyHz: 0,
      },
    ])
  })

  it('rejects fractional replay event time', () => {
    expect(() => calculateHealthMetrics(catalog, [], 1.5)).toThrow(
      'replayTimeUs must be a non-negative safe integer',
    )
  })
})
