import { useState } from 'react'

import type { DashboardHistory } from '../../domain/dashboard/index.ts'
import type { CanLogFrame } from '../../domain/log/index.ts'
import { REPLAY_SPEEDS, type ReplayEngine, type ReplayGroup, type ReplaySnapshot } from '../../domain/replay/index.ts'

export interface ReplayControlsProps {
  readonly engine: ReplayEngine<DashboardHistory, CanLogFrame>
  readonly snapshot: ReplaySnapshot<DashboardHistory>
  readonly processedFrames: readonly CanLogFrame[]
  readonly selectedFrameSeq: number | null
  readonly onSelectFrame: (frame: CanLogFrame) => void
  readonly onStep: (group: ReplayGroup<CanLogFrame> | null) => void
  readonly onSeek: (timestampUs: number) => void
}

export const ReplayControls = ({ engine, snapshot, processedFrames, selectedFrameSeq, onSelectFrame, onStep, onSeek }: ReplayControlsProps) => {
  const [seekValue, setSeekValue] = useState(String(snapshot.replayTimeUs))
  const [lastStepSize, setLastStepSize] = useState<number | null>(null)
  const step = () => {
    const group = engine.step()
    setLastStepSize(group?.frames.length ?? 0)
    setSeekValue(String(engine.getSnapshot().replayTimeUs))
    onStep(group)
  }
  const seek = () => {
    const timestampUs = Number(seekValue)
    if (!Number.isSafeInteger(timestampUs) || timestampUs < 0) return
    setLastStepSize(null)
    engine.seek(timestampUs)
    onSeek(timestampUs)
  }
  return (
    <section className="workspace-section replay-section" aria-labelledby="replay-title">
      <div className="section-heading"><div><p className="eyebrow">Deterministic event time</p><h2 id="replay-title">Replay controls</h2></div><div className={`status-chip status-${snapshot.status}`}>Status {snapshot.status}</div></div>
      <div className="panel control-deck">
        <div className="transport-controls"><button className="primary-action" onClick={() => engine.play()} type="button">Play</button><button onClick={() => engine.pause()} type="button">Pause</button><button onClick={step} type="button">Step</button></div>
        <label><span>Replay speed</span><select aria-label="Replay speed" onChange={(event) => engine.setSpeed(Number(event.target.value))} value={String(snapshot.speed)}>{REPLAY_SPEEDS.map((speed) => <option key={speed} value={speed}>{speed}×</option>)}</select></label>
        <label className="checkbox-field"><input aria-label="Loop replay" checked={snapshot.loopEnabled} onChange={(event) => engine.setLoopEnabled(event.target.checked)} type="checkbox" /><span>Loop replay</span></label>
        <label className="seek-field"><span>Seek time (µs)</span><input aria-label="Seek time (µs)" min="0" onChange={(event) => setSeekValue(event.target.value)} step="1" type="number" value={seekValue} /><button onClick={seek} type="button">Seek</button></label>
      </div>
      <div className="replay-readout"><strong>Replay time {snapshot.replayTimeUs} µs</strong><span>Position {snapshot.processedFrameCount}/{snapshot.totalFrameCount}</span>{lastStepSize === null ? null : <span>{lastStepSize} frames · position {snapshot.processedFrameCount}/{snapshot.totalFrameCount}</span>}</div>
      <div className="panel frame-stream">
        <div className="panel-heading"><div><p className="eyebrow">Canonical history</p><h3>Processed frames</h3></div><span>{processedFrames.length}</span></div>
        <ol aria-label="Processed frames">{processedFrames.map((frame) => (
          <li key={frame.seq}><button aria-label={`Frame seq ${frame.seq}`} aria-pressed={selectedFrameSeq === frame.seq} onClick={() => onSelectFrame(frame)} type="button"><span><strong>seq {frame.seq}</strong><code>{frame.can_id}</code></span><span>{frame.timestamp_us} µs · {frame.phase}</span></button></li>
        ))}</ol>
      </div>
    </section>
  )
}
