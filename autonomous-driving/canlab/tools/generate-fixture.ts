import { createHash } from 'node:crypto'
import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

export interface DriveCycleConfig {
  readonly schemaVersion: '1.0.0'
  readonly dbcVersion: '1.0.0'
  readonly seed: number
}

export interface GeneratedDriveCycle {
  readonly content: string
  readonly sha256: string
}

export const DEFAULT_DRIVE_CYCLE_CONFIG: DriveCycleConfig = {
  schemaVersion: '1.0.0',
  dbcVersion: '1.0.0',
  seed: 20260804,
}

const PHASE_WINDOWS = [
  { name: 'start', start_us: 0, end_us: 999_999 },
  { name: 'acceleration', start_us: 1_000_000, end_us: 3_999_999 },
  { name: 'cruise', start_us: 4_000_000, end_us: 6_999_999 },
  { name: 'turn', start_us: 7_000_000, end_us: 8_999_999 },
  { name: 'deceleration', start_us: 9_000_000, end_us: 10_999_999 },
  { name: 'stop', start_us: 11_000_000, end_us: 12_000_000 },
] as const

type Phase = (typeof PHASE_WINDOWS)[number]['name']

interface FrameDraft {
  readonly timestamp_us: number
  readonly phase: Phase
  readonly can_id: string
  readonly is_extended: boolean
  readonly dlc: 8
  readonly data: string
}

const EXPECTED_PERIOD_US = {
  '0x100': 100_000,
  '0x200': 200_000,
  '0x00000300': 1_000_000,
} as const

const clamp = (value: number, minimum: number, maximum: number) =>
  Math.min(maximum, Math.max(minimum, value))

const encodeUnsigned16Le = (value: number) => {
  const integer = clamp(Math.round(value), 0, 0xffff)
  return [integer & 0xff, (integer >>> 8) & 0xff]
}

const encodeSigned16Be = (value: number) => {
  const integer = clamp(Math.round(value), -0x8000, 0x7fff)
  const encoded = integer < 0 ? 0x10000 + integer : integer
  return [(encoded >>> 8) & 0xff, encoded & 0xff]
}

const toHex = (bytes: readonly number[]) =>
  bytes.map((byte) => byte.toString(16).padStart(2, '0')).join('').toUpperCase()

const createPrng = (seed: number) => {
  let state = seed >>> 0
  return () => {
    state ^= state << 13
    state ^= state >>> 17
    state ^= state << 5
    return (state >>> 0) / 0x1_0000_0000
  }
}

const phaseAt = (timestampUs: number): Phase => {
  const window = PHASE_WINDOWS.find(
    ({ start_us, end_us }) => timestampUs >= start_us && timestampUs <= end_us,
  )
  if (window === undefined) {
    throw new RangeError(`timestamp_us ${timestampUs} is outside the scenario`)
  }
  return window.name
}

const stateAt = (timestampUs: number, random: () => number) => {
  const phase = phaseAt(timestampUs)
  const noise = random() - 0.5

  switch (phase) {
    case 'start':
      return {
        speed: 0,
        rpm: 800 + Math.round(noise * 20),
        throttle: 0,
        brake: timestampUs < 500_000 ? 20 : 0,
        gear: timestampUs < 500_000 ? 0 : 3,
        turn: 0,
        steering: 0,
      }
    case 'acceleration': {
      const progress = (timestampUs - 1_000_000) / 2_900_000
      return {
        speed: 5 + 65 * progress,
        rpm: 1_200 + 2_000 * progress,
        throttle: 55 + noise * 4,
        brake: 0,
        gear: 3,
        turn: 0,
        steering: 0,
      }
    }
    case 'cruise':
      return {
        speed: 70 + noise,
        rpm: 2_400 + noise * 30,
        throttle: 25 + noise * 2,
        brake: 0,
        gear: 3,
        turn: 0,
        steering: 0,
      }
    case 'turn':
      return {
        speed: 45,
        rpm: 1_900,
        throttle: 20,
        brake: 0,
        gear: 3,
        turn: timestampUs < 8_000_000 ? 1 : 2,
        steering: timestampUs < 8_000_000 ? -125 : 125,
      }
    case 'deceleration': {
      const progress = (timestampUs - 9_000_000) / 1_900_000
      return {
        speed: 45 * (1 - progress),
        rpm: 1_900 - 1_000 * progress,
        throttle: 0,
        brake: 50,
        gear: 3,
        turn: 0,
        steering: 0,
      }
    }
    case 'stop':
      return {
        speed: 0,
        rpm: 800,
        throttle: 0,
        brake: 20,
        gear: 0,
        turn: 0,
        steering: 0,
      }
  }
}

const powertrainData = (state: ReturnType<typeof stateAt>) => {
  const rpm = encodeUnsigned16Le(state.rpm / 0.25)
  const speed = encodeUnsigned16Le(state.speed / 0.01)
  return toHex([
    ...rpm,
    ...speed,
    clamp(Math.round(state.throttle / 0.4), 0, 0xff),
    clamp(Math.round(state.brake / 0.5), 0, 0xff),
    state.gear,
    state.turn,
  ])
}

const chassisData = (state: ReturnType<typeof stateAt>) =>
  toHex([...encodeSigned16Be(state.steering / 0.1), 0, 0, 0, 0, 0, 0])

const buildFrames = (seed: number): FrameDraft[] => {
  const random = createPrng(seed)
  const frames: FrameDraft[] = []

  for (let tick = 0; tick <= 120; tick += 1) {
    const timestamp_us = tick * 100_000
    const phase = phaseAt(timestamp_us)
    const state = stateAt(timestamp_us, random)

    // The missing 0x100 frame at 2.5 s is an intentional, deterministic gap.
    if (timestamp_us !== 2_500_000) {
      frames.push({
        timestamp_us,
        phase,
        can_id: '0x100',
        is_extended: false,
        dlc: 8,
        data: powertrainData(state),
      })
    }

    if (tick % 2 === 0) {
      frames.push({
        timestamp_us,
        phase,
        can_id: '0x200',
        is_extended: false,
        dlc: 8,
        data: chassisData(state),
      })
    }

    if (tick % 10 === 0) {
      frames.push({
        timestamp_us,
        phase,
        can_id: '0x00000300',
        is_extended: true,
        dlc: 8,
        data: '3C7D000000000000',
      })
    }

    if (timestamp_us === 7_500_000) {
      frames.push({
        timestamp_us,
        phase,
        can_id: '0x555',
        is_extended: false,
        dlc: 8,
        data: 'DEADBEEF01020304',
      })
    }
  }

  return frames
}

export const generateDriveCycle = (
  config: DriveCycleConfig,
): GeneratedDriveCycle => {
  const metadata = {
    type: 'metadata',
    schema: 'canlab.drive-cycle',
    schema_version: config.schemaVersion,
    seed: config.seed,
    scenario: 'six-phase-demo',
    time_base: 'integer_microseconds',
    dbc_asset: `canlab-demo-v${config.dbcVersion}.dbc`,
    dbc_version: config.dbcVersion,
    phases: PHASE_WINDOWS,
    expected_period_us: EXPECTED_PERIOD_US,
  }
  const frames = buildFrames(config.seed).map((frame, seq) => ({
    type: 'frame',
    seq,
    ...frame,
  }))
  const content = `${[metadata, ...frames].map((record) => JSON.stringify(record)).join('\n')}\n`

  return {
    content,
    sha256: createHash('sha256').update(content, 'utf8').digest('hex'),
  }
}

const outputUrl = new URL('../public/assets/drive-cycle-v1.ndjson', import.meta.url)
const isDirectRun =
  process.argv[1] !== undefined &&
  resolve(process.argv[1]) === fileURLToPath(import.meta.url)

if (isDirectRun) {
  const generated = generateDriveCycle(DEFAULT_DRIVE_CYCLE_CONFIG)
  mkdirSync(dirname(fileURLToPath(outputUrl)), { recursive: true })
  writeFileSync(outputUrl, generated.content, 'utf8')
  process.stdout.write(`${generated.sha256}  drive-cycle-v1.ndjson\n`)
}
