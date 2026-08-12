import type { DbcDatabase } from '../dbc/index.ts'
import { decodeFrame, type DecodedSignal } from '../decode/index.ts'
import {
  calculateHealthMetrics,
  createExpectedPeriodCatalog,
  type HealthFrame,
  type HealthMetric,
} from '../health/index.ts'

export const DASHBOARD_GAUGE_SIGNALS = [
  'VehicleSpeed',
  'EngineRpm',
  'SelectedGear',
  'ThrottlePosition',
  'BrakePressure',
  'TurnIndicator',
] as const

export const DASHBOARD_TREND_SIGNALS = [
  'VehicleSpeed',
  'EngineRpm',
  'ThrottlePosition',
  'BrakePressure',
  'SteeringAngle',
  'SelectedGear',
] as const

export type DashboardGaugeSignal = (typeof DASHBOARD_GAUGE_SIGNALS)[number]
export type DashboardTrendSignal = (typeof DASHBOARD_TREND_SIGNALS)[number]
export type DashboardFrame = HealthFrame

export interface DashboardSample {
  readonly timestampUs: number
  readonly signalId: string
  readonly physicalValue: number
  readonly displayValue: string
  readonly unit: string
  readonly enumLabel?: string
}

export interface DashboardTrendPoint {
  readonly timestampUs: number
  readonly physicalValue: number
  readonly displayValue: string
}

export type DashboardGauges = Readonly<
  Record<DashboardGaugeSignal, DashboardSample | null>
>

export type DashboardTrends = Readonly<
  Record<DashboardTrendSignal, readonly DashboardTrendPoint[]>
>

export interface DashboardProjection {
  readonly replayTimeUs: number
  readonly gauges: DashboardGauges
  readonly trends: DashboardTrends
  readonly health: readonly HealthMetric[]
}

export interface DashboardHistory {
  readonly frames: readonly DashboardFrame[]
}

export interface DashboardProjectorOptions {
  readonly database: DbcDatabase
  readonly expectedPeriodUs: Readonly<Record<string, number>>
}

export interface DashboardProjector {
  readonly initialState: () => DashboardHistory
  readonly reduce: (
    history: DashboardHistory,
    frame: DashboardFrame,
  ) => DashboardHistory
  readonly project: (
    history: DashboardHistory,
    replayTimeUs: number,
  ) => DashboardProjection
}

export class DashboardProjectionError extends Error {
  readonly code = 'DASHBOARD_DECODE_FAILED'
  readonly seq: number

  constructor(seq: number, message: string) {
    super(`DASHBOARD_DECODE_FAILED at seq ${String(seq)}: ${message}`)
    this.name = 'DashboardProjectionError'
    this.seq = seq
  }
}

const isGaugeSignal = (name: string): name is DashboardGaugeSignal =>
  DASHBOARD_GAUGE_SIGNALS.some((signalName) => signalName === name)

const isTrendSignal = (name: string): name is DashboardTrendSignal =>
  DASHBOARD_TREND_SIGNALS.some((signalName) => signalName === name)

const emptyGauges = (): Record<DashboardGaugeSignal, DashboardSample | null> => ({
  VehicleSpeed: null,
  EngineRpm: null,
  SelectedGear: null,
  ThrottlePosition: null,
  BrakePressure: null,
  TurnIndicator: null,
})

const emptyTrends = (): Record<
  DashboardTrendSignal,
  DashboardTrendPoint[]
> => ({
  VehicleSpeed: [],
  EngineRpm: [],
  ThrottlePosition: [],
  BrakePressure: [],
  SteeringAngle: [],
  SelectedGear: [],
})

const gaugeSample = (
  signal: DecodedSignal,
  timestampUs: number,
): DashboardSample => ({
  timestampUs,
  signalId: signal.signalId,
  physicalValue: signal.physicalValue,
  displayValue: signal.displayValue,
  unit: signal.unit,
  ...(signal.enumLabel === undefined ? {} : { enumLabel: signal.enumLabel }),
})

const trendPoint = (
  signal: DecodedSignal,
  timestampUs: number,
): DashboardTrendPoint => ({
  timestampUs,
  physicalValue: signal.physicalValue,
  displayValue: signal.displayValue,
})

export const createDashboardProjector = (
  options: DashboardProjectorOptions,
): DashboardProjector => {
  const healthCatalog = createExpectedPeriodCatalog(
    options.database,
    options.expectedPeriodUs,
  )

  const initialState = (): DashboardHistory => ({ frames: [] })
  const reduce = (
    history: DashboardHistory,
    frame: DashboardFrame,
  ): DashboardHistory => ({ frames: [...history.frames, frame] })

  const project = (
    history: DashboardHistory,
    replayTimeUs: number,
  ): DashboardProjection => {
    const frames = history.frames
      .filter((frame) => frame.timestamp_us <= replayTimeUs)
      .sort(
        (left, right) =>
          left.timestamp_us - right.timestamp_us || left.seq - right.seq,
      )
    const gauges = emptyGauges()
    const trends = emptyTrends()

    for (const frame of frames) {
      const decoded = decodeFrame(options.database, frame)
      if (!decoded.ok) {
        if (decoded.error.code === 'UNKNOWN_MESSAGE') continue
        throw new DashboardProjectionError(frame.seq, decoded.error.message)
      }

      for (const signal of decoded.signals) {
        if (isGaugeSignal(signal.name)) {
          gauges[signal.name] = gaugeSample(signal, frame.timestamp_us)
        }
        if (isTrendSignal(signal.name)) {
          trends[signal.name].push(trendPoint(signal, frame.timestamp_us))
        }
      }
    }

    return {
      replayTimeUs,
      gauges,
      trends,
      health: calculateHealthMetrics(healthCatalog, frames, replayTimeUs),
    }
  }

  return { initialState, reduce, project }
}

export const buildDashboardProjection = (
  options: DashboardProjectorOptions,
  history: readonly DashboardFrame[],
  replayTimeUs: number,
): DashboardProjection => {
  const projector = createDashboardProjector(options)
  return projector.project({ frames: history }, replayTimeUs)
}
