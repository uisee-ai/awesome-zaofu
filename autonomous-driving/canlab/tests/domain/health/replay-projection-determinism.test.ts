// @vitest-environment node

import { readFileSync } from 'node:fs'

import { describe, expect, it } from 'vitest'

import { createDashboardProjector, type DashboardFrame } from '../../../src/domain/dashboard/index.ts'
import { parseDbc } from '../../../src/domain/dbc/index.ts'
import { ReplayEngine, type ReplayScheduler } from '../../../src/domain/replay/index.ts'

interface PendingCallback {
  readonly callback: () => void
  cancelled: boolean
}

class JitterScheduler implements ReplayScheduler {
  private nextId = 1
  readonly pending = new Map<number, PendingCallback>()

  schedule(callback: () => void): unknown {
    const id = this.nextId
    this.nextId += 1
    this.pending.set(id, { callback, cancelled: false })
    return id
  }

  cancel(handle: unknown): void {
    const pending = this.pending.get(handle as number)
    if (pending !== undefined) pending.cancelled = true
  }

  latestId(): number {
    return Math.max(...this.pending.keys())
  }

  fire(id: number): void {
    this.pending.get(id)?.callback()
  }
}

const parsed = parseDbc(
  readFileSync(
    new URL('../../../public/assets/canlab-demo-v1.0.0.dbc', import.meta.url),
    'utf8',
  ),
)
if (!parsed.ok) throw new Error(parsed.error.message)

const projector = createDashboardProjector({
  database: parsed.database,
  expectedPeriodUs: {
    '0x100': 100_000,
    '0x200': 200_000,
    '0x00000300': 1_000_000,
  },
})

const frames: readonly DashboardFrame[] = [
  { seq: 1, timestamp_us: 0, can_id: '0x200', is_extended: false, dlc: 8, data: 'FB1E000000000000' },
  { seq: 0, timestamp_us: 0, can_id: '0x100', is_extended: false, dlc: 8, data: '803E881364320302' },
  { seq: 2, timestamp_us: 100_000, can_id: '0x100', is_extended: false, dlc: 8, data: '803E881364320302' },
  { seq: 3, timestamp_us: 300_000, can_id: '0x100', is_extended: false, dlc: 8, data: '803E881364320302' },
]

const createEngine = (scheduler: ReplayScheduler) =>
  new ReplayEngine({
    frames,
    scheduler,
    initialState: projector.initialState,
    reduce: projector.reduce,
  })

describe('Replay-to-Health/Dashboard event-time determinism', () => {
  it('wall-clock callback jitter, pause and speed changes cannot alter projection state', () => {
    const jitteredScheduler = new JitterScheduler()
    const jittered = createEngine(jitteredScheduler)
    jittered.play()
    const superseded = jitteredScheduler.latestId()
    jittered.setSpeed(4)
    jitteredScheduler.fire(superseded)
    jitteredScheduler.fire(jitteredScheduler.latestId())
    const pausedCallback = jitteredScheduler.latestId()
    jittered.pause()
    jitteredScheduler.fire(pausedCallback)
    jittered.play()
    while (jittered.getSnapshot().status === 'playing') {
      jitteredScheduler.fire(jitteredScheduler.latestId())
    }

    const stepped = createEngine(new JitterScheduler())
    while (stepped.step() !== null) {
      // Consume canonical equal-timestamp groups without wall-clock scheduling.
    }

    const jitteredSnapshot = jittered.getSnapshot()
    const steppedSnapshot = stepped.getSnapshot()
    expect(jitteredSnapshot.state.frames.map(({ seq }) => seq)).toEqual([0, 1, 2, 3])
    expect(
      projector.project(jitteredSnapshot.state, jitteredSnapshot.replayTimeUs),
    ).toEqual(projector.project(steppedSnapshot.state, steppedSnapshot.replayTimeUs))
  })

  it('seek and loop rebuild projections exclusively from canonical event history', () => {
    const scheduler = new JitterScheduler()
    const engine = createEngine(scheduler)
    engine.seek(300_000)
    const sought = projector.project(engine.getSnapshot().state, 300_000)
    expect(sought.trends.VehicleSpeed.map(({ timestampUs }) => timestampUs)).toEqual([
      0,
      100_000,
      300_000,
    ])
    expect(sought.health.find(({ canId }) => canId === '0x100')).toMatchObject({
      inferredMissingFrames: 1,
      frequencyHz: 3,
    })

    engine.setLoopEnabled(true)
    engine.play()
    scheduler.fire(scheduler.latestId())
    const loopedSnapshot = engine.getSnapshot()
    const looped = projector.project(loopedSnapshot.state, loopedSnapshot.replayTimeUs)
    expect(loopedSnapshot.state.frames.map(({ seq }) => seq)).toEqual([0, 1])
    expect(looped.trends.VehicleSpeed.map(({ timestampUs }) => timestampUs)).toEqual([0])
    expect(looped.health.find(({ canId }) => canId === '0x100')).toMatchObject({
      inferredMissingFrames: 0,
      frequencyHz: 1,
    })
  })
})
