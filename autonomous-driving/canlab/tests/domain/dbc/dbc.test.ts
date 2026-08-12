// @vitest-environment node

import { readFileSync } from 'node:fs'

import { describe, expect, it } from 'vitest'

import { parseDbc } from '../../../src/domain/dbc/index.ts'

const canonicalDbc = readFileSync(
  new URL('../../../public/assets/canlab-demo-v1.0.0.dbc', import.meta.url),
  'utf8',
)

describe('DBC subset parser', () => {
  it('parses the complete canonical DBC into a normalized, exact AST', () => {
    expect(parseDbc(canonicalDbc)).toEqual({
      ok: true,
      database: {
        version: '1.0.0',
        nodes: ['CANLAB'],
        comment:
          'Project-authored synthetic fixture for offline CAN protocol exploration.',
        messages: [
          {
            id: 0x100,
            rawId: 256,
            isExtended: false,
            name: 'Powertrain',
            dlc: 8,
            transmitter: 'CANLAB',
            cycleTimeUs: 100_000,
            signals: [
              {
                name: 'EngineRpm',
                startBit: 0,
                length: 16,
                byteOrder: 'intel',
                signed: false,
                factor: 0.25,
                offset: 0,
                min: 0,
                max: 16_000,
                unit: 'rpm',
                receivers: ['CANLAB'],
                values: {},
              },
              {
                name: 'VehicleSpeed',
                startBit: 16,
                length: 16,
                byteOrder: 'intel',
                signed: false,
                factor: 0.01,
                offset: 0,
                min: 0,
                max: 655.35,
                unit: 'km/h',
                receivers: ['CANLAB'],
                values: {},
              },
              {
                name: 'ThrottlePosition',
                startBit: 32,
                length: 8,
                byteOrder: 'intel',
                signed: false,
                factor: 0.4,
                offset: 0,
                min: 0,
                max: 100,
                unit: '%',
                receivers: ['CANLAB'],
                values: {},
              },
              {
                name: 'BrakePressure',
                startBit: 40,
                length: 8,
                byteOrder: 'intel',
                signed: false,
                factor: 0.5,
                offset: 0,
                min: 0,
                max: 127.5,
                unit: 'bar',
                receivers: ['CANLAB'],
                values: {},
              },
              {
                name: 'SelectedGear',
                startBit: 48,
                length: 8,
                byteOrder: 'intel',
                signed: false,
                factor: 1,
                offset: 0,
                min: 0,
                max: 3,
                unit: '',
                receivers: ['CANLAB'],
                values: {
                  '0': 'Park',
                  '1': 'Reverse',
                  '2': 'Neutral',
                  '3': 'Drive',
                },
              },
              {
                name: 'TurnIndicator',
                startBit: 56,
                length: 8,
                byteOrder: 'intel',
                signed: false,
                factor: 1,
                offset: 0,
                min: 0,
                max: 3,
                unit: '',
                receivers: ['CANLAB'],
                values: {
                  '0': 'Off',
                  '1': 'Left',
                  '2': 'Right',
                  '3': 'Hazard',
                },
              },
            ],
          },
          {
            id: 0x200,
            rawId: 512,
            isExtended: false,
            name: 'Chassis',
            dlc: 8,
            transmitter: 'CANLAB',
            cycleTimeUs: 200_000,
            signals: [
              {
                name: 'SteeringAngle',
                startBit: 7,
                length: 16,
                byteOrder: 'motorola',
                signed: true,
                factor: 0.1,
                offset: 0,
                min: -780,
                max: 780,
                unit: 'deg',
                receivers: ['CANLAB'],
                values: {},
              },
            ],
          },
          {
            id: 0x300,
            rawId: 2_147_484_416,
            isExtended: true,
            name: 'EnvironmentExtended',
            dlc: 8,
            transmitter: 'CANLAB',
            cycleTimeUs: 1_000_000,
            signals: [
              {
                name: 'AmbientTemperature',
                startBit: 0,
                length: 8,
                byteOrder: 'intel',
                signed: true,
                factor: 1,
                offset: -40,
                min: -40,
                max: 215,
                unit: 'deg C',
                receivers: ['CANLAB'],
                values: {},
              },
              {
                name: 'BatteryVoltage',
                startBit: 8,
                length: 8,
                byteOrder: 'intel',
                signed: false,
                factor: 0.1,
                offset: 0,
                min: 0,
                max: 25.5,
                unit: 'V',
                receivers: ['CANLAB'],
                values: {},
              },
            ],
          },
        ],
      },
    })
  })

  it('rejects multiplexing with a stable error and no partial database', () => {
    const result = parseDbc(
      'BO_ 100 Multiplexed: 8 ECU\n SG_ Mode M : 0|8@1+ (1,0) [0|255] "" ECU\n',
    )

    expect(result).toEqual({
      ok: false,
      error: {
        code: 'UNSUPPORTED_CONSTRUCT',
        line: 2,
        message: 'Multiplexed signals are not supported',
      },
    })
    expect(Object.keys(result)).toEqual(['ok', 'error'])
  })

  it('rejects a signal outside the message payload atomically', () => {
    const result = parseDbc(
      'BO_ 100 TooSmall: 8 ECU\n SG_ TooWide : 60|8@1+ (1,0) [0|255] "" ECU\n',
    )

    expect(result).toEqual({
      ok: false,
      error: {
        code: 'INVALID_SIGNAL_LAYOUT',
        line: 2,
        message: 'Signal TooWide uses bits outside the 8-byte message payload',
      },
    })
    expect(Object.keys(result)).toEqual(['ok', 'error'])
  })
})
