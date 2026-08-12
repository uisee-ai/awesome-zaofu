import { describe, expect, it } from 'vitest'

import {
  ReplayEngine,
  type ReplayScheduler,
} from '../../../src/domain/replay/index.ts'

interface TestFrame {
  readonly seq: number
  readonly timestamp_us: number
  readonly value: string
}

interface PendingCallback {
  readonly callback: () => void
  readonly delayMs: number
  cancelled: boolean
}

class ManualScheduler implements ReplayScheduler {
  private nextId = 1
  readonly pending = new Map<number, PendingCallback>()

  schedule(callback: () => void, delayMs: number): unknown {
    const id = this.nextId
    this.nextId += 1
    this.pending.set(id, { callback, delayMs, cancelled: false })
    return id
  }

  cancel(handle: unknown): void {
    const pending = this.pending.get(handle as number)
    if (pending !== undefined) {
      pending.cancelled = true
    }
  }

  latestId(): number {
    return Math.max(...this.pending.keys())
  }

  fire(id: number): void {
    const pending = this.pending.get(id)
    if (pending === undefined) {
      throw new Error(`No callback ${id}`)
    }
    pending.callback()
  }
}

const frames: readonly TestFrame[] = [
  { seq: 2, timestamp_us: 100, value: 'B' },
  { seq: 1, timestamp_us: 100, value: 'A' },
  { seq: 3, timestamp_us: 200, value: 'C' },
  { seq: 4, timestamp_us: 400, value: 'D' },
]

const createEngine = (scheduler = new ManualScheduler()) => ({
  scheduler,
  engine: new ReplayEngine({
    frames,
    scheduler,
    initialState: () => ({ values: [] as string[] }),
    reduce: (state, frame) => ({ values: [...state.values, frame.value] }),
  }),
})

describe('ReplayEngine', () => {
  it('steps the next timestamp group atomically in original seq order', () => {
    const { engine } = createEngine()

    expect(engine.getSnapshot()).toEqual({
      status: 'paused',
      speed: 1,
      loopEnabled: false,
      replayTimeUs: 100,
      processedFrameCount: 0,
      totalFrameCount: 4,
      currentGroupSize: 0,
      state: { values: [] },
    })

    expect(engine.step()).toEqual({
      timestampUs: 100,
      startIndex: 0,
      endIndexExclusive: 2,
      frames: [
        { seq: 1, timestamp_us: 100, value: 'A' },
        { seq: 2, timestamp_us: 100, value: 'B' },
      ],
    })
    expect(engine.getSnapshot()).toMatchObject({
      status: 'paused',
      replayTimeUs: 100,
      processedFrameCount: 2,
      currentGroupSize: 2,
      state: { values: ['A', 'B'] },
    })

    expect(engine.step()?.frames.map((frame) => frame.value)).toEqual(['C'])
  })

  it('seek rebuilds every frame at or before T and pauses', () => {
    const { engine, scheduler } = createEngine()
    engine.play()
    const staleCallback = scheduler.latestId()

    engine.seek(200)

    expect(engine.getSnapshot()).toEqual({
      status: 'paused',
      speed: 1,
      loopEnabled: false,
      replayTimeUs: 200,
      processedFrameCount: 3,
      totalFrameCount: 4,
      currentGroupSize: 1,
      state: { values: ['A', 'B', 'C'] },
    })

    scheduler.fire(staleCallback)
    expect(engine.getSnapshot().state.values).toEqual(['A', 'B', 'C'])

    engine.seek(99)
    expect(engine.getSnapshot()).toMatchObject({
      status: 'paused',
      replayTimeUs: 99,
      processedFrameCount: 0,
      currentGroupSize: 0,
      state: { values: [] },
    })
  })

  it('loop clears prior state before rebuilding from the first group', () => {
    const { engine, scheduler } = createEngine()
    engine.setLoopEnabled(true)
    engine.play()

    scheduler.fire(scheduler.latestId())
    scheduler.fire(scheduler.latestId())
    scheduler.fire(scheduler.latestId())
    expect(engine.getSnapshot().state.values).toEqual(['A', 'B', 'C', 'D'])

    scheduler.fire(scheduler.latestId())
    expect(engine.getSnapshot()).toMatchObject({
      status: 'playing',
      replayTimeUs: 100,
      processedFrameCount: 2,
      currentGroupSize: 2,
      state: { values: ['A', 'B'] },
    })
  })

  it('ignores superseded wall-clock callbacks after speed or pause changes', () => {
    const { engine, scheduler } = createEngine()
    engine.play()
    const oneXCallback = scheduler.latestId()

    engine.setSpeed(2)
    const twoXCallback = scheduler.latestId()
    expect(twoXCallback).not.toBe(oneXCallback)
    expect(scheduler.pending.get(oneXCallback)?.cancelled).toBe(true)

    scheduler.fire(oneXCallback)
    expect(engine.getSnapshot().state.values).toEqual([])

    scheduler.fire(twoXCallback)
    expect(engine.getSnapshot().state.values).toEqual(['A', 'B'])
    expect(scheduler.pending.get(scheduler.latestId())?.delayMs).toBe(0.05)

    const pendingAfterFirstGroup = scheduler.latestId()
    engine.pause()
    scheduler.fire(pendingAfterFirstGroup)
    expect(engine.getSnapshot()).toMatchObject({
      status: 'paused',
      processedFrameCount: 2,
      state: { values: ['A', 'B'] },
    })
  })

  it('rejects fractional event time and unsupported playback speed', () => {
    const { engine } = createEngine()

    expect(() => engine.seek(1.5)).toThrow('timestampUs must be a non-negative safe integer')
    expect(() => engine.setSpeed(3)).toThrow('Unsupported replay speed: 3')
  })
})
