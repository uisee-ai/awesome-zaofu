import { useMemo } from 'react'

import type { DbcDatabase } from '../../domain/dbc/index.ts'
import type { CanLogFrame } from '../../domain/log/index.ts'
import { traceSignal } from '../../domain/trace/index.ts'
import type { ExplorerSelection } from '../explorer/index.tsx'

export interface SignalTracePanelProps { readonly database: DbcDatabase; readonly frame: CanLogFrame | null; readonly dbcHash: string; readonly logHash: string; readonly selection: ExplorerSelection | null }

export const SignalTracePanel = ({ database, frame, dbcHash, logHash, selection }: SignalTracePanelProps) => {
  const result = useMemo(() => frame === null || selection === null ? null : traceSignal(database, frame, { dbcHash, logHash, frameSeq: frame.seq, timestampUs: frame.timestamp_us, signalName: selection.signal.name }), [database, dbcHash, frame, logHash, selection])
  return (
    <section className="workspace-section trace-section" aria-labelledby="trace-title">
      <div className="section-heading"><div><p className="eyebrow">Explain every value</p><h2 id="trace-title">Decode trace</h2></div></div>
      <section className="panel trace-panel" aria-label="Signal trace">
        {result === null ? <p className="empty-state">Step replay and choose a frame to inspect its provenance.</p>
          : !result.ok ? <div className="error-state"><strong>{result.error.code}</strong><p>{result.error.message}</p></div>
          : result.trace.kind === 'unknown' ? (
            <div className="unknown-trace"><p className="eyebrow">No DBC match</p><h3>Unknown frame {result.trace.frame.canId}</h3>
              <dl className="trace-grid"><div><dt>Frame</dt><dd>frame seq {result.trace.frame.frameSeq}</dd></div><div><dt>Timestamp</dt><dd>{result.trace.frame.timestampUs} µs</dd></div><div><dt>CAN ID</dt><dd><code>{result.trace.frame.canId}</code></dd></div><div><dt>Format</dt><dd>{result.trace.frame.frameFormat} · isExtended {String(result.trace.frame.isExtended)}</dd></div><div><dt>DLC</dt><dd>{result.trace.frame.dlc}</dd></div><div><dt>Payload</dt><dd>raw bytes <code>{result.trace.frame.rawBytes}</code></dd></div><div><dt>Log SHA-256</dt><dd><code>{result.trace.frame.logHash}</code></dd></div><div><dt>DBC SHA-256</dt><dd><code>{result.trace.frame.dbcHash}</code></dd></div></dl><p>{result.trace.reason}</p>
            </div>
          ) : (
            <div data-signal-chain><div className="panel-heading"><div><p className="eyebrow">Stable trace ID</p><h3>{result.trace.signal.name}</h3></div><code className="trace-id">{result.trace.traceId}</code></div>
              <div className="trace-flow" aria-label="Raw-to-physical signal chain">
                <article><span>01</span><strong>Frame</strong><p>raw bytes <code>{result.trace.frame.rawBytes}</code></p><small>log {result.trace.frame.logHash} · DBC {result.trace.frame.dbcHash} · frame seq {result.trace.frame.frameSeq}</small></article>
                <article><span>02</span><strong>DBC bitfield</strong><p>start bit {result.trace.signal.startBit} · length {result.trace.signal.length}</p><small>{result.trace.signal.byteOrder} · {result.trace.signal.signed ? 'signed' : 'unsigned'}</small></article>
                <article><span>03</span><strong>Raw integer</strong><p>raw integer {result.trace.rawInteger}</p><small>{result.trace.signal.signalId}</small></article>
                <article><span>04</span><strong>Conversion</strong><p>{result.trace.conversion.formula}</p><small>factor {result.trace.conversion.factor} · offset {result.trace.conversion.offset}</small></article>
                <article><span>05</span><strong>Physical value</strong><p>final value {result.trace.value.displayValue}</p><small>{result.trace.value.enumLabel ?? result.trace.value.unit}</small></article>
              </div>
            </div>
          )}
      </section>
    </section>
  )
}
