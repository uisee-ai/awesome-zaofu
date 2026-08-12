// @vitest-environment node

import { readFileSync } from 'node:fs'

import { describe, expect, it } from 'vitest'

import { parseDbc } from '../../../src/domain/dbc/index.ts'
import { decodeFrame } from '../../../src/domain/decode/index.ts'

const dbcSource = readFileSync(
  new URL('../../../public/assets/canlab-demo-v1.0.0.dbc', import.meta.url),
  'utf8',
)
const parsed = parseDbc(dbcSource)
if (!parsed.ok) throw new Error(parsed.error.message)
const database = parsed.database

describe('atomic CAN frame decoder', () => {
  it('decodes the complete Intel powertrain golden vector including enums', () => {
    expect(
      decodeFrame(database, {
        can_id: '0x100',
        is_extended: false,
        dlc: 8,
        data: '803E881364320302',
      }),
    ).toEqual({
      ok: true,
      message: {
        id: 0x100,
        canId: '0x100',
        isExtended: false,
        name: 'Powertrain',
        dlc: 8,
      },
      dataHex: '803E881364320302',
      signals: [
        {
          signalId: '0x100/EngineRpm',
          name: 'EngineRpm',
          rawValue: 16_000,
          physicalValue: 4_000,
          unit: 'rpm',
          displayValue: '4000 rpm',
        },
        {
          signalId: '0x100/VehicleSpeed',
          name: 'VehicleSpeed',
          rawValue: 5_000,
          physicalValue: 50,
          unit: 'km/h',
          displayValue: '50 km/h',
        },
        {
          signalId: '0x100/ThrottlePosition',
          name: 'ThrottlePosition',
          rawValue: 100,
          physicalValue: 40,
          unit: '%',
          displayValue: '40 %',
        },
        {
          signalId: '0x100/BrakePressure',
          name: 'BrakePressure',
          rawValue: 50,
          physicalValue: 25,
          unit: 'bar',
          displayValue: '25 bar',
        },
        {
          signalId: '0x100/SelectedGear',
          name: 'SelectedGear',
          rawValue: 3,
          physicalValue: 3,
          unit: '',
          enumLabel: 'Drive',
          displayValue: 'Drive',
        },
        {
          signalId: '0x100/TurnIndicator',
          name: 'TurnIndicator',
          rawValue: 2,
          physicalValue: 2,
          unit: '',
          enumLabel: 'Right',
          displayValue: 'Right',
        },
      ],
    })
  })

  it('decodes signed Motorola bits from the chassis golden vector', () => {
    expect(
      decodeFrame(database, {
        canId: 0x200,
        isExtended: false,
        dlc: 8,
        data: Uint8Array.from([0xfb, 0x1e, 0, 0, 0, 0, 0, 0]),
      }),
    ).toEqual({
      ok: true,
      message: {
        id: 0x200,
        canId: '0x200',
        isExtended: false,
        name: 'Chassis',
        dlc: 8,
      },
      dataHex: 'FB1E000000000000',
      signals: [
        {
          signalId: '0x200/SteeringAngle',
          name: 'SteeringAngle',
          rawValue: -1_250,
          physicalValue: -125,
          unit: 'deg',
          displayValue: '-125 deg',
        },
      ],
    })
  })

  it('distinguishes an extended ID and applies signed offset conversion', () => {
    expect(
      decodeFrame(database, {
        can_id: '0x00000300',
        is_extended: true,
        dlc: 8,
        data: '3C7D000000000000',
      }),
    ).toEqual({
      ok: true,
      message: {
        id: 0x300,
        canId: '0x00000300',
        isExtended: true,
        name: 'EnvironmentExtended',
        dlc: 8,
      },
      dataHex: '3C7D000000000000',
      signals: [
        {
          signalId: '0x00000300/AmbientTemperature',
          name: 'AmbientTemperature',
          rawValue: 60,
          physicalValue: 20,
          unit: 'deg C',
          displayValue: '20 deg C',
        },
        {
          signalId: '0x00000300/BatteryVoltage',
          name: 'BatteryVoltage',
          rawValue: 125,
          physicalValue: 12.5,
          unit: 'V',
          displayValue: '12.5 V',
        },
      ],
    })
  })

  it('returns a stable unknown-message error without signal output', () => {
    const result = decodeFrame(database, {
      can_id: '0x555',
      is_extended: false,
      dlc: 8,
      data: 'DEADBEEF01020304',
    })

    expect(result).toEqual({
      ok: false,
      error: {
        code: 'UNKNOWN_MESSAGE',
        message: 'No standard DBC message for 0x555',
      },
    })
    expect(Object.keys(result)).toEqual(['ok', 'error'])
  })

  it('rejects inconsistent frame bytes atomically', () => {
    const result = decodeFrame(database, {
      canId: 0x100,
      isExtended: false,
      dlc: 8,
      data: '803E',
    })

    expect(result).toEqual({
      ok: false,
      error: {
        code: 'INVALID_FRAME',
        message: 'Frame 0x100 declares DLC 8 but contains 2 bytes',
      },
    })
    expect(Object.keys(result)).toEqual(['ok', 'error'])
  })
})
