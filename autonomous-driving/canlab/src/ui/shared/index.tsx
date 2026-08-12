import { useEffect, useMemo, useState } from 'react'

import { createDashboardProjector, type DashboardHistory } from '../../domain/dashboard/index.ts'
import type { DbcDatabase } from '../../domain/dbc/index.ts'
import { createSignalId } from '../../domain/decode/index.ts'
import type { CanLogFrame } from '../../domain/log/index.ts'
import { ReplayEngine, type ReplayGroup } from '../../domain/replay/index.ts'
import { VehicleDashboard } from '../dashboard/index.tsx'
import { DbcExplorer, type ExplorerSelection } from '../explorer/index.tsx'
import { ReplayControls } from '../replay/index.tsx'
import { SignalTracePanel } from '../trace/index.tsx'
import type { CanLabAssetMetadata } from './model.ts'

export type { CanLabAssetMetadata } from './model.ts'
export interface CanLabWorkspaceProps { readonly assetMetadata: CanLabAssetMetadata; readonly database: DbcDatabase; readonly expectedPeriodUs: Readonly<Record<string, number>>; readonly frames: readonly CanLogFrame[]; readonly dbcHash: string; readonly logHash: string }

const firstSelection = (database: DbcDatabase): ExplorerSelection | null => {
  for (const message of database.messages) {
    const signal = message.signals[0]
    if (signal !== undefined) return { message, signal, signalId: createSignalId(message, signal.name) }
  }
  return null
}
const latestFrameAt = (frames: readonly CanLogFrame[], timestampUs: number): CanLogFrame | null => [...frames].filter((frame) => frame.timestamp_us <= timestampUs).sort((left, right) => left.timestamp_us - right.timestamp_us || left.seq - right.seq).at(-1) ?? null

export const CanLabWorkspace = ({ assetMetadata, database, expectedPeriodUs, frames, dbcHash, logHash }: CanLabWorkspaceProps) => {
  const projector = useMemo(() => createDashboardProjector({ database, expectedPeriodUs }), [database, expectedPeriodUs])
  const canonicalFrames = useMemo(() => [...frames].sort((left, right) => left.timestamp_us - right.timestamp_us || left.seq - right.seq), [frames])
  const engine = useMemo(() => new ReplayEngine<DashboardHistory, CanLogFrame>({ frames: canonicalFrames, initialState: projector.initialState, reduce: projector.reduce }), [canonicalFrames, projector])
  const [snapshot, setSnapshot] = useState(() => engine.getSnapshot())
  const [selection, setSelection] = useState<ExplorerSelection | null>(() => firstSelection(database))
  const [selectedFrame, setSelectedFrame] = useState<CanLogFrame | null>(null)
  useEffect(() => engine.subscribe(setSnapshot), [engine])
  const projection = useMemo(() => projector.project(snapshot.state, snapshot.replayTimeUs), [projector, snapshot.replayTimeUs, snapshot.state])
  const handleStep = (group: ReplayGroup<CanLogFrame> | null) => {
    const frame = group?.frames.at(-1)
    if (frame !== undefined) setSelectedFrame(frame)
  }
  return (
    <main className="can-lab-workspace">
      <header className="lab-header"><div><p className="eyebrow">Offline · synthetic · receive-only</p><h1>CAN Protocol Lab</h1><p>Explore definitions, replay deterministic traffic, and trace every decoded value.</p></div><div className="offline-badge"><span aria-hidden="true" />Offline fixture</div></header>
      <DbcExplorer assetMetadata={assetMetadata} database={database} onSelectSignal={setSelection} selectedSignalId={selection?.signalId ?? null} />
      <ReplayControls engine={engine} onSeek={(timestampUs) => setSelectedFrame(latestFrameAt(canonicalFrames, timestampUs))} onSelectFrame={setSelectedFrame} onStep={handleStep} processedFrames={canonicalFrames.slice(0, snapshot.processedFrameCount)} selectedFrameSeq={selectedFrame?.seq ?? null} snapshot={snapshot} />
      <SignalTracePanel database={database} dbcHash={dbcHash} frame={selectedFrame} logHash={logHash} selection={selection} />
      <VehicleDashboard projection={projection} />
    </main>
  )
}
