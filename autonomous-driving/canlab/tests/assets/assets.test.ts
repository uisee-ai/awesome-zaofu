// @vitest-environment node

import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'

import { describe, expect, it } from 'vitest'

import {
  DEFAULT_DRIVE_CYCLE_CONFIG,
  generateDriveCycle,
} from '../../tools/generate-fixture.ts'

const assetUrl = (name: string) =>
  new URL(`../../public/assets/${name}`, import.meta.url)

const readAsset = (name: string) => readFileSync(assetUrl(name), 'utf8')

const sha256 = (content: string) =>
  createHash('sha256').update(content, 'utf8').digest('hex')

const phases = [
  'start',
  'acceleration',
  'cruise',
  'turn',
  'deceleration',
  'stop',
]

describe('CAN Lab synthetic asset contract', () => {
  it('generates byte-identical NDJSON and SHA-256 for the canonical inputs', () => {
    const first = generateDriveCycle(DEFAULT_DRIVE_CYCLE_CONFIG)
    const second = generateDriveCycle({ ...DEFAULT_DRIVE_CYCLE_CONFIG })
    const bundled = readAsset('drive-cycle-v1.ndjson')

    expect(second).toEqual(first)
    expect(first.content).toBe(bundled)
    expect(first.sha256).toBe(sha256(bundled))
    expect(first.sha256).toBe(
      '31e49897877e494e147cac0564d2a4f9c09d25ecb5c1fc6cf3d3603e3edc1110',
    )
    expect(
      generateDriveCycle({ ...DEFAULT_DRIVE_CYCLE_CONFIG, seed: 20260805 })
        .sha256,
    ).not.toBe(first.sha256)
    expect(bundled.endsWith('\n')).toBe(true)
  })

  it('publishes the exact metadata record and all six phase windows', () => {
    const [metadataLine] = readAsset('drive-cycle-v1.ndjson').trimEnd().split('\n')
    const metadata = JSON.parse(metadataLine) as unknown

    expect(metadata).toEqual({
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
    })
  })

  it('emits complete, ordered Classical CAN frames with controlled anomalies', () => {
    const [, ...frameLines] = readAsset('drive-cycle-v1.ndjson')
      .trimEnd()
      .split('\n')
    const frames = frameLines.map((line) => JSON.parse(line)) as Array<{
      type: string
      seq: number
      timestamp_us: number
      phase: string
      can_id: string
      is_extended: boolean
      dlc: number
      data: string
    }>

    expect(frames).toHaveLength(195)
    expect(frames.map((frame) => frame.seq)).toEqual(
      Array.from({ length: 195 }, (_, index) => index),
    )
    expect(frames.map((frame) => frame.phase).filter((phase, index, all) =>
      index === 0 || phase !== all[index - 1],
    )).toEqual(phases)

    for (const frame of frames) {
      expect(Object.keys(frame)).toEqual([
        'type',
        'seq',
        'timestamp_us',
        'phase',
        'can_id',
        'is_extended',
        'dlc',
        'data',
      ])
      expect(frame.type).toBe('frame')
      expect(Number.isSafeInteger(frame.timestamp_us)).toBe(true)
      expect(frame.dlc).toBe(8)
      expect(frame.data).toMatch(/^[0-9A-F]{16}$/)
    }

    expect(
      frames.some(
        (frame) => frame.can_id === '0x100' && frame.timestamp_us === 2_500_000,
      ),
    ).toBe(false)
    expect(frames.filter((frame) => frame.can_id === '0x555')).toEqual([
      {
        type: 'frame',
        seq: 121,
        timestamp_us: 7_500_000,
        phase: 'turn',
        can_id: '0x555',
        is_extended: false,
        dlc: 8,
        data: 'DEADBEEF01020304',
      },
    ])
    expect(
      frames.find((frame) => frame.can_id === '0x00000300'),
    ).toMatchObject({ is_extended: true })
  })

  it('binds provenance metadata to the exact DBC, vectors and drive cycle bytes', () => {
    const dbc = readAsset('canlab-demo-v1.0.0.dbc')
    const vectors = readAsset('canlab-demo-v1.0.0.vectors.json')
    const driveCycle = readAsset('drive-cycle-v1.ndjson')
    const metadata = JSON.parse(
      readAsset('canlab-demo-v1.0.0.metadata.json'),
    ) as unknown

    expect(metadata).toEqual({
      schema_version: '1.0.0',
      asset: {
        name: 'CAN Lab Demo',
        file: 'canlab-demo-v1.0.0.dbc',
        version: '1.0.0',
        source: 'project-authored synthetic fixture',
        license: 'CC0-1.0',
        sha256: sha256(dbc),
      },
      validation_vectors: {
        file: 'canlab-demo-v1.0.0.vectors.json',
        version: '1.0.0',
        sha256: sha256(vectors),
      },
      drive_cycle: {
        file: 'drive-cycle-v1.ndjson',
        schema: 'canlab.drive-cycle',
        schema_version: '1.0.0',
        seed: 20260804,
        scenario: 'six-phase-demo',
        sha256: sha256(driveCycle),
        phases,
        expected_period_us: {
          '0x100': 100_000,
          '0x200': 200_000,
          '0x00000300': 1_000_000,
        },
      },
    })
  })

  it('contains the complete supported DBC subset and exact golden vectors', () => {
    const dbc = readAsset('canlab-demo-v1.0.0.dbc')
    const vectorsContent = readAsset('canlab-demo-v1.0.0.vectors.json')
    const vectors = JSON.parse(vectorsContent) as {
      schema_version: string
      vector_version: string
      dbc: unknown
      vectors: unknown[]
    }
    const license = readAsset('canlab-demo-v1.0.0.license.txt')

    expect(sha256(dbc)).toBe(
      'd5e6ab74ba4fccb17493cdfae79ae115e0b9b64c3153033531a3d3c74a1d23f7',
    )
    expect(sha256(vectorsContent)).toBe(
      '9ca0fb7a52ed9307337b23b6bc7bf5556e50ad6cc83f637ffeffed3c8d3436b4',
    )

    expect(dbc).toContain('BO_ 256 Powertrain: 8 CANLAB')
    expect(dbc).toContain('BO_ 512 Chassis: 8 CANLAB')
    expect(dbc).toContain('BO_ 2147484416 EnvironmentExtended: 8 CANLAB')
    expect(dbc).toContain('SG_ EngineRpm : 0|16@1+ (0.25,0)')
    expect(dbc).toContain('SG_ SteeringAngle : 7|16@0- (0.1,0)')
    expect(dbc).toContain('SG_ AmbientTemperature : 0|8@1- (1,-40)')
    expect(dbc).toContain('VAL_ 256 SelectedGear 0 "Park" 1 "Reverse" 2 "Neutral" 3 "Drive" ;')
    expect(dbc).toContain('VAL_ 256 TurnIndicator 0 "Off" 1 "Left" 2 "Right" 3 "Hazard" ;')
    expect(dbc).toContain('BA_ "GenMsgCycleTime" BO_ 256 100;')
    expect(dbc).toContain('BA_ "GenMsgCycleTime" BO_ 512 200;')
    expect(dbc).toContain('BA_ "GenMsgCycleTime" BO_ 2147484416 1000;')

    expect(Object.keys(vectors)).toEqual([
      'schema_version',
      'vector_version',
      'dbc',
      'vectors',
    ])
    expect(vectors.schema_version).toBe('1.0.0')
    expect(vectors.vector_version).toBe('1.0.0')
    expect(vectors.dbc).toEqual({
      file: 'canlab-demo-v1.0.0.dbc',
      version: '1.0.0',
      sha256: 'd5e6ab74ba4fccb17493cdfae79ae115e0b9b64c3153033531a3d3c74a1d23f7',
    })
    expect(vectors.vectors).toEqual([
      {
        name: 'powertrain-drive',
        frame: {
          can_id: '0x100',
          is_extended: false,
          dlc: 8,
          data: '803E881364320302',
        },
        signals: [
          { signal: 'EngineRpm', raw: 16000, physical: 4000, display: '4000 rpm' },
          { signal: 'VehicleSpeed', raw: 5000, physical: 50, display: '50 km/h' },
          { signal: 'ThrottlePosition', raw: 100, physical: 40, display: '40 %' },
          { signal: 'BrakePressure', raw: 50, physical: 25, display: '25 bar' },
          { signal: 'SelectedGear', raw: 3, physical: 3, display: 'Drive' },
          { signal: 'TurnIndicator', raw: 2, physical: 2, display: 'Right' },
        ],
      },
      {
        name: 'chassis-left',
        frame: {
          can_id: '0x200',
          is_extended: false,
          dlc: 8,
          data: 'FB1E000000000000',
        },
        signals: [
          { signal: 'SteeringAngle', raw: -1250, physical: -125, display: '-125 deg' },
        ],
      },
      {
        name: 'environment-extended',
        frame: {
          can_id: '0x00000300',
          is_extended: true,
          dlc: 8,
          data: '3C7D000000000000',
        },
        signals: [
          { signal: 'AmbientTemperature', raw: 60, physical: 20, display: '20 deg C' },
          { signal: 'BatteryVoltage', raw: 125, physical: 12.5, display: '12.5 V' },
        ],
      },
    ])
    expect(license).toContain('SPDX-License-Identifier: CC0-1.0')
    expect(license).toContain('project-authored synthetic fixture')
  })
})
