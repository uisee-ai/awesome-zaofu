// @vitest-environment node

import { readFileSync } from 'node:fs'

import { describe, expect, it } from 'vitest'

import { parseDbc } from '../../../src/domain/dbc/index.ts'
import {
  DASHBOARD_GAUGE_SIGNALS,
  DASHBOARD_TREND_SIGNALS,
  createDashboardProjector,
  type DashboardFrame,
} from '../../../src/domain/dashboard/index.ts'

const parsed = parseDbc(
  readFileSync(
    new URL('../../../public/assets/canlab-demo-v1.0.0.dbc', import.meta.url),
    'utf8',
  ),
)
if (!parsed.ok) throw new Error(parsed.error.message)

const expectedPeriodUs = {
  '0x100': 100_000,
  '0x200': 200_000,
  '0x00000300': 1_000_000,
}

const frames: readonly DashboardFrame[] = [
  {
    seq: 1,
    timestamp_us: 0,
    can_id: '0x200',
    is_extended: false,
    dlc: 8,
    data: 'FB1E000000000000',
  },
  {
    seq: 0,
    timestamp_us: 0,
    can_id: '0x100',
    is_extended: false,
    dlc: 8,
    data: '803E881364320302',
  },
  {
    seq: 2,
    timestamp_us: 100_000,
    can_id: '0x100',
    is_extended: false,
    dlc: 8,
    data: '803E881364320302',
  },
  {
    seq: 3,
    timestamp_us: 100_000,
    can_id: '0x555',
    is_extended: false,
    dlc: 8,
    data: 'DEADBEEF01020304',
  },
]

describe('unified DashboardProjection', () => {
  it('publishes the fixed gauge and six-trend contract from one history', () => {
    expect(DASHBOARD_GAUGE_SIGNALS).toEqual([
      'VehicleSpeed',
      'EngineRpm',
      'SelectedGear',
      'ThrottlePosition',
      'BrakePressure',
      'TurnIndicator',
    ])
    expect(DASHBOARD_TREND_SIGNALS).toEqual([
      'VehicleSpeed',
      'EngineRpm',
      'ThrottlePosition',
      'BrakePressure',
      'SteeringAngle',
      'SelectedGear',
    ])

    const projector = createDashboardProjector({
      database: parsed.database,
      expectedPeriodUs,
    })
    const history = frames.reduce(projector.reduce, projector.initialState())
    const projection = projector.project(history, 100_000)

    expect(projection.replayTimeUs).toBe(100_000)
    expect(Object.keys(projection.gauges)).toEqual(DASHBOARD_GAUGE_SIGNALS)
    expect(projection.gauges).toMatchObject({
      VehicleSpeed: { physicalValue: 50, displayValue: '50 km/h', timestampUs: 100_000 },
      EngineRpm: { physicalValue: 4_000, displayValue: '4000 rpm', timestampUs: 100_000 },
      SelectedGear: { physicalValue: 3, displayValue: 'Drive', timestampUs: 100_000 },
      ThrottlePosition: { physicalValue: 40, displayValue: '40 %', timestampUs: 100_000 },
      BrakePressure: { physicalValue: 25, displayValue: '25 bar', timestampUs: 100_000 },
      TurnIndicator: { physicalValue: 2, displayValue: 'Right', timestampUs: 100_000 },
    })
    expect(Object.keys(projection.trends)).toEqual(DASHBOARD_TREND_SIGNALS)
    expect(projection.trends.VehicleSpeed).toEqual([
      { timestampUs: 0, physicalValue: 50, displayValue: '50 km/h' },
      { timestampUs: 100_000, physicalValue: 50, displayValue: '50 km/h' },
    ])
    expect(projection.trends.SteeringAngle).toEqual([
      { timestampUs: 0, physicalValue: -125, displayValue: '-125 deg' },
    ])
    expect(projection.trends.SelectedGear).toEqual([
      { timestampUs: 0, physicalValue: 3, displayValue: 'Drive' },
      { timestampUs: 100_000, physicalValue: 3, displayValue: 'Drive' },
    ])
    expect(projection.health.find((metric) => metric.canId === '0x100')).toMatchObject({
      frequencyHz: 2,
      inferredMissingFrames: 0,
      stale: false,
    })
  })

  it('reconstructs gauges and trends at seek time and clears them for loop state', () => {
    const projector = createDashboardProjector({
      database: parsed.database,
      expectedPeriodUs,
    })
    const history = frames.reduce(projector.reduce, projector.initialState())

    const sought = projector.project(history, 0)
    expect(sought.gauges.VehicleSpeed?.timestampUs).toBe(0)
    expect(sought.trends.VehicleSpeed).toHaveLength(1)

    const looped = projector.project(projector.initialState(), 0)
    expect(Object.values(looped.gauges)).toEqual([null, null, null, null, null, null])
    expect(Object.values(looped.trends).every((points) => points.length === 0)).toBe(true)
    expect(looped.health.every((metric) => metric.lastSeenUs === null)).toBe(true)
  })
})
