import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it } from 'vitest'

import { parseDbc, type DbcDatabase } from '../../src/domain/dbc/index.ts'
import { CanLabWorkspace, type CanLabAssetMetadata } from '../../src/ui/shared/index.tsx'

const parsed = parseDbc(readFileSync(join(process.cwd(), 'public/assets/canlab-demo-v1.0.0.dbc'), 'utf8'))
if (!parsed.ok) throw new Error(parsed.error.message)

const database: DbcDatabase = {
  ...parsed.database,
  messages: [...parsed.database.messages, {
    id: 0x600,
    rawId: 0x600,
    isExtended: false,
    name: 'Diagnostics',
    dlc: 8,
    transmitter: 'CANLAB',
    signals: [],
  }],
}
const assetMetadata = JSON.parse(readFileSync(
  join(process.cwd(), 'public/assets/canlab-demo-v1.0.0.metadata.json'),
  'utf8',
)) as CanLabAssetMetadata
const frames = [
  { type: 'frame' as const, seq: 1, timestamp_us: 0, phase: 'start', can_id: '0x100', is_extended: false, dlc: 8, data: '803E881364320302' },
  { type: 'frame' as const, seq: 0, timestamp_us: 0, phase: 'start', can_id: '0x100', is_extended: false, dlc: 8, data: '803E881364320302' },
  { type: 'frame' as const, seq: 2, timestamp_us: 100_000, phase: 'acceleration', can_id: '0x555', is_extended: false, dlc: 8, data: 'DEADBEEF01020304' },
  { type: 'frame' as const, seq: 3, timestamp_us: 400_000, phase: 'turn', can_id: '0x200', is_extended: false, dlc: 8, data: 'FB1E000000000000' },
]

const renderWorkspace = () => render(
  <CanLabWorkspace
    assetMetadata={assetMetadata}
    database={database}
    dbcHash="d5e6ab74ba4fccb1"
    expectedPeriodUs={assetMetadata.drive_cycle.expected_period_us}
    frames={frames}
    logHash="31e49897877e494e"
  />,
)
const expectText = (element: Element, text: string) =>
  expect(element.textContent).toContain(text)

afterEach(cleanup)

describe('CAN Lab browser integration', () => {
  it('searches the DBC hierarchy and exposes the complete 64-bit signal definition', async () => {
    const user = userEvent.setup()
    renderWorkspace()
    const hierarchy = screen.getByRole('tree', { name: 'DBC hierarchy' })

    expect(within(hierarchy).getByText('Powertrain')).not.toBeNull()
    expect(within(hierarchy).getByText('Chassis')).not.toBeNull()
    expect(within(hierarchy).getByText('EnvironmentExtended')).not.toBeNull()

    const search = screen.getByRole('searchbox', { name: 'Search DBC' })
    await user.type(search, 'rpm')
    expect(within(hierarchy).getByText('EngineRpm')).not.toBeNull()
    expect(within(hierarchy).queryByText('Chassis')).toBeNull()

    await user.clear(search)
    await user.type(search, '0x200')
    expect(within(hierarchy).getByText('Chassis')).not.toBeNull()
    expect(within(hierarchy).queryByText('Powertrain')).toBeNull()

    await user.clear(search)
    await user.click(screen.getByRole('button', { name: 'EngineRpm' }))
    const details = screen.getByRole('region', { name: 'Signal details' })
    for (const detail of ['start bit 0', 'length 16', 'intel', 'unsigned', 'factor 0.25', 'offset 0', 'unit rpm']) {
      expectText(details, detail)
    }

    const layout = within(details).getByLabelText('64-bit layout for EngineRpm')
    expect(layout.querySelectorAll('[data-bit]')).toHaveLength(64)
    expect(layout.querySelectorAll('[data-active="true"]')).toHaveLength(16)

    await user.click(screen.getByRole('button', { name: 'SelectedGear' }))
    expectText(details, '0 Park')
    expectText(details, '3 Drive')
  })

  it('shows bundled asset provenance and validation-vector identity', () => {
    renderWorkspace()
    const provenance = screen.getByRole('region', { name: 'DBC asset provenance' })
    for (const item of [
      'project-authored synthetic fixture',
      'v1.0.0',
      'CC0-1.0',
      'd5e6ab74ba4fccb17493cdfae79ae115e0b9b64c3153033531a3d3c74a1d23f7',
      'validation vectors v1.0.0',
    ]) expectText(provenance, item)
  })

  it('operates replay controls and reports atomic timestamp-group progress in seq order', async () => {
    const user = userEvent.setup()
    renderWorkspace()

    await user.click(screen.getByRole('button', { name: 'Step' }))
    expect(screen.getByText('2 frames · position 2/4')).not.toBeNull()
    expect(screen.getByText('Replay time 0 µs')).not.toBeNull()
    const frameItems = within(screen.getByRole('list', { name: 'Processed frames' })).getAllByRole('listitem')
    expect(frameItems).toHaveLength(2)
    expectText(frameItems[0]!, 'seq 0')
    expectText(frameItems[1]!, 'seq 1')

    const speed = screen.getByLabelText('Replay speed') as HTMLSelectElement
    await user.selectOptions(speed, '2')
    expect(speed.value).toBe('2')
    const loop = screen.getByLabelText('Loop replay') as HTMLInputElement
    await user.click(loop)
    expect(loop.checked).toBe(true)

    await user.click(screen.getByRole('button', { name: 'Play' }))
    expect(screen.getByText('Status playing')).not.toBeNull()
    await user.click(screen.getByRole('button', { name: 'Pause' }))
    expect(screen.getByText('Status paused')).not.toBeNull()

    const seek = screen.getByLabelText('Seek time (µs)')
    await user.clear(seek)
    await user.type(seek, '400000')
    await user.click(screen.getByRole('button', { name: 'Seek' }))
    expect(screen.getByText('Replay time 400000 µs')).not.toBeNull()
    expect(screen.getByText('Position 4/4')).not.toBeNull()
  })

  it('renders a stable known-signal chain and never invents one for an unknown frame', async () => {
    const user = userEvent.setup()
    renderWorkspace()
    await user.click(screen.getByRole('button', { name: 'EngineRpm' }))
    await user.click(screen.getByRole('button', { name: 'Step' }))
    await user.click(screen.getByRole('button', { name: 'Frame seq 1' }))

    const known = screen.getByRole('region', { name: 'Signal trace' })
    for (const item of [
      '31e49897877e494e/d5e6ab74ba4fccb1/1/0x100/EngineRpm',
      'raw bytes 803E881364320302',
      'start bit 0 · length 16',
      'raw integer 16000',
      '16000 × 0.25 + 0 = 4000',
      'final value 4000 rpm',
    ]) expectText(known, item)

    await user.click(screen.getByRole('button', { name: 'Step' }))
    const unknown = screen.getByRole('region', { name: 'Signal trace' })
    expectText(unknown, 'Unknown frame 0x555')
    expectText(unknown, 'frame seq 2')
    expectText(unknown, '100000 µs')
    expectText(unknown, 'standard · isExtended false')
    expectText(unknown, 'DLC8')
    expectText(unknown, 'raw bytes DEADBEEF01020304')
    expect(unknown.querySelector('[data-signal-chain]')).toBeNull()
  })

  it('updates fixed gauges, health and six event-time trends from one projection', async () => {
    const user = userEvent.setup()
    renderWorkspace()
    await user.click(screen.getByRole('button', { name: 'Step' }))

    const dashboard = screen.getByRole('region', { name: 'Vehicle dashboard' })
    expect(dashboard.getAttribute('data-projection-time')).toBe('0')
    expectText(within(dashboard).getByTestId('gauge-VehicleSpeed'), '50 km/h')
    expectText(within(dashboard).getByTestId('gauge-EngineRpm'), '4000 rpm')
    expect(within(dashboard).getAllByTestId('trend-panel')).toHaveLength(6)
    expectText(within(dashboard).getByTestId('trend-VehicleSpeed'), '0 µs')

    const seek = screen.getByLabelText('Seek time (µs)')
    await user.clear(seek)
    await user.type(seek, '400000')
    await user.click(screen.getByRole('button', { name: 'Seek' }))

    expect(dashboard.getAttribute('data-projection-time')).toBe('400000')
    expectText(within(dashboard).getByTestId('health-0x100'), 'stale yes')
    const noPeriod = within(dashboard).getByTestId('health-0x600')
    expectText(noPeriod, 'stale N/A')
    expectText(noPeriod, 'missing N/A')
    expectText(within(dashboard).getByTestId('trend-SteeringAngle'), '400000 µs')
  })
})
