export const REPLAY_SPEEDS = [0.25, 0.5, 1, 2, 4] as const

export type ReplaySpeed = (typeof REPLAY_SPEEDS)[number]
export type ReplayStatus = 'paused' | 'playing' | 'ended'

export interface ReplayFrame {
  readonly seq: number
  readonly timestamp_us: number
}

export interface ReplayScheduler {
  schedule(callback: () => void, delayMs: number): unknown
  cancel(handle: unknown): void
}

export interface ReplayGroup<Frame extends ReplayFrame> {
  readonly timestampUs: number
  readonly startIndex: number
  readonly endIndexExclusive: number
  readonly frames: readonly Frame[]
}

export interface ReplaySnapshot<State> {
  readonly status: ReplayStatus
  readonly speed: ReplaySpeed
  readonly loopEnabled: boolean
  readonly replayTimeUs: number
  readonly processedFrameCount: number
  readonly totalFrameCount: number
  readonly currentGroupSize: number
  readonly state: State
}

export interface ReplayEngineOptions<
  State,
  Frame extends ReplayFrame,
> {
  readonly frames: readonly Frame[]
  readonly initialState: () => State
  readonly reduce: (state: State, frame: Frame) => State
  readonly scheduler?: ReplayScheduler
  readonly speed?: ReplaySpeed
  readonly loopEnabled?: boolean
}

const systemScheduler: ReplayScheduler = {
  schedule: (callback, delayMs) => globalThis.setTimeout(callback, delayMs),
  cancel: (handle) =>
    globalThis.clearTimeout(handle as ReturnType<typeof globalThis.setTimeout>),
}

const isNonNegativeSafeInteger = (value: number) =>
  Number.isSafeInteger(value) && value >= 0

export class ReplayEngine<State, Frame extends ReplayFrame> {
  private readonly frames: readonly Frame[]
  private readonly initialState: () => State
  private readonly reduce: (state: State, frame: Frame) => State
  private readonly scheduler: ReplayScheduler
  private readonly listeners = new Set<(snapshot: ReplaySnapshot<State>) => void>()

  private state: State
  private status: ReplayStatus = 'paused'
  private speed: ReplaySpeed
  private loopEnabled: boolean
  private replayTimeUs: number
  private cursor = 0
  private currentGroupSize = 0
  private callbackGeneration = 0
  private pendingHandle: unknown | undefined

  constructor(options: ReplayEngineOptions<State, Frame>) {
    const sequences = new Set<number>()
    for (const frame of options.frames) {
      if (
        !isNonNegativeSafeInteger(frame.seq) ||
        !isNonNegativeSafeInteger(frame.timestamp_us) ||
        sequences.has(frame.seq)
      ) {
        throw new TypeError(
          'Replay frames require unique non-negative integer seq and timestamp_us',
        )
      }
      sequences.add(frame.seq)
    }
    this.frames = [...options.frames].sort(
      (left, right) =>
        left.timestamp_us - right.timestamp_us || left.seq - right.seq,
    )
    this.initialState = options.initialState
    this.reduce = options.reduce
    this.scheduler = options.scheduler ?? systemScheduler
    this.speed = options.speed ?? 1
    this.loopEnabled = options.loopEnabled ?? false
    this.state = this.initialState()
    this.replayTimeUs = this.frames[0]?.timestamp_us ?? 0
  }

  getSnapshot(): ReplaySnapshot<State> {
    return {
      status: this.status,
      speed: this.speed,
      loopEnabled: this.loopEnabled,
      replayTimeUs: this.replayTimeUs,
      processedFrameCount: this.cursor,
      totalFrameCount: this.frames.length,
      currentGroupSize: this.currentGroupSize,
      state: this.state,
    }
  }

  subscribe(listener: (snapshot: ReplaySnapshot<State>) => void): () => void {
    this.listeners.add(listener)
    return () => {
      this.listeners.delete(listener)
    }
  }

  play(): void {
    if (this.status === 'playing') {
      return
    }
    if (this.frames.length === 0) {
      this.status = 'ended'
      this.notify()
      return
    }
    if (this.cursor >= this.frames.length) {
      if (!this.loopEnabled) {
        this.status = 'ended'
        this.notify()
        return
      }
      this.resetProjection()
    }
    this.status = 'playing'
    this.notify()
    this.scheduleNext()
  }

  pause(): void {
    this.invalidatePendingCallback()
    this.status = 'paused'
    this.notify()
  }

  setSpeed(speed: number): void {
    if (!REPLAY_SPEEDS.includes(speed as ReplaySpeed)) {
      throw new RangeError(`Unsupported replay speed: ${speed}`)
    }
    if (this.speed === speed) {
      return
    }
    this.speed = speed as ReplaySpeed
    this.notify()
    if (this.status === 'playing') {
      this.scheduleNext()
    }
  }

  setLoopEnabled(enabled: boolean): void {
    if (this.loopEnabled === enabled) {
      return
    }
    this.loopEnabled = enabled
    this.notify()
    if (!enabled && this.status === 'playing' && this.cursor >= this.frames.length) {
      this.invalidatePendingCallback()
      this.status = 'ended'
      this.notify()
    }
  }

  step(): ReplayGroup<Frame> | null {
    this.invalidatePendingCallback()
    this.status = 'paused'
    const group = this.consumeNextGroup()
    this.notify()
    return group
  }

  seek(timestampUs: number): void {
    if (!isNonNegativeSafeInteger(timestampUs)) {
      throw new RangeError('timestampUs must be a non-negative safe integer')
    }
    this.invalidatePendingCallback()
    this.resetProjection()

    let lastTimestamp: number | undefined
    let lastGroupSize = 0
    while (
      this.cursor < this.frames.length &&
      this.frames[this.cursor]!.timestamp_us <= timestampUs
    ) {
      const frame = this.frames[this.cursor]!
      this.state = this.reduce(this.state, frame)
      this.cursor += 1
      if (frame.timestamp_us === lastTimestamp) {
        lastGroupSize += 1
      } else {
        lastTimestamp = frame.timestamp_us
        lastGroupSize = 1
      }
    }

    this.replayTimeUs = timestampUs
    this.currentGroupSize = this.cursor === 0 ? 0 : lastGroupSize
    this.status = 'paused'
    this.notify()
  }

  private resetProjection(): void {
    this.state = this.initialState()
    this.cursor = 0
    this.currentGroupSize = 0
    this.replayTimeUs = this.frames[0]?.timestamp_us ?? 0
  }

  private consumeNextGroup(): ReplayGroup<Frame> | null {
    if (this.cursor >= this.frames.length) {
      return null
    }
    const startIndex = this.cursor
    const timestampUs = this.frames[startIndex]!.timestamp_us
    while (
      this.cursor < this.frames.length &&
      this.frames[this.cursor]!.timestamp_us === timestampUs
    ) {
      this.state = this.reduce(this.state, this.frames[this.cursor]!)
      this.cursor += 1
    }
    const groupFrames = this.frames.slice(startIndex, this.cursor)
    this.replayTimeUs = timestampUs
    this.currentGroupSize = groupFrames.length
    return {
      timestampUs,
      startIndex,
      endIndexExclusive: this.cursor,
      frames: groupFrames,
    }
  }

  private scheduleNext(): void {
    if (this.cursor >= this.frames.length) {
      if (this.loopEnabled) {
        this.armCallback(() => this.advanceScheduled(), 0)
      } else {
        this.invalidatePendingCallback()
        this.status = 'ended'
        this.notify()
      }
      return
    }
    const nextTimestampUs = this.frames[this.cursor]!.timestamp_us
    const delayMs = Math.max(
      0,
      (nextTimestampUs - this.replayTimeUs) / this.speed / 1_000,
    )
    this.armCallback(() => this.advanceScheduled(), delayMs)
  }

  private advanceScheduled(): void {
    if (this.status !== 'playing') {
      return
    }
    if (this.cursor >= this.frames.length) {
      if (!this.loopEnabled) {
        this.status = 'ended'
        this.notify()
        return
      }
      this.resetProjection()
    }
    this.consumeNextGroup()
    this.notify()
    this.scheduleNext()
  }

  private armCallback(callback: () => void, delayMs: number): void {
    this.invalidatePendingCallback()
    const generation = this.callbackGeneration
    const handle = this.scheduler.schedule(() => {
      if (
        generation !== this.callbackGeneration ||
        this.status !== 'playing'
      ) {
        return
      }
      this.pendingHandle = undefined
      callback()
    }, delayMs)
    this.pendingHandle = handle
  }

  private invalidatePendingCallback(): void {
    if (this.pendingHandle !== undefined) {
      this.scheduler.cancel(this.pendingHandle)
      this.pendingHandle = undefined
    }
    this.callbackGeneration += 1
  }

  private notify(): void {
    const snapshot = this.getSnapshot()
    for (const listener of this.listeners) {
      listener(snapshot)
    }
  }
}
