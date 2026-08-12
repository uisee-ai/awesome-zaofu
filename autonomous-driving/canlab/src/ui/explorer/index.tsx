import { useMemo, useState } from 'react'

import type { DbcDatabase, DbcMessage, DbcSignal } from '../../domain/dbc/index.ts'
import { createSignalId, formatCanId } from '../../domain/decode/index.ts'
import type { CanLabAssetMetadata } from '../shared/model.ts'

export interface ExplorerSelection {
  readonly message: DbcMessage
  readonly signal: DbcSignal
  readonly signalId: string
}

export interface DbcExplorerProps {
  readonly database: DbcDatabase
  readonly assetMetadata: CanLabAssetMetadata
  readonly selectedSignalId: string | null
  readonly onSelectSignal: (selection: ExplorerSelection) => void
}

const signalBits = (signal: DbcSignal): readonly number[] => {
  if (signal.byteOrder === 'intel') {
    return Array.from({ length: signal.length }, (_, index) => signal.startBit + index)
  }
  const bits: number[] = []
  let bit = signal.startBit
  for (let index = 0; index < signal.length; index += 1) {
    bits.push(bit)
    bit = bit % 8 === 0 ? bit + 15 : bit - 1
  }
  return bits
}

const matchesQuery = (message: DbcMessage, query: string): boolean => {
  const canId = formatCanId(message.id, message.isExtended).toLowerCase()
  return message.name.toLowerCase().includes(query) || canId.includes(query) ||
    message.signals.some((signal) => signal.name.toLowerCase().includes(query))
}

const SignalDetails = ({ selection }: { readonly selection: ExplorerSelection | null }) => {
  if (selection === null) {
    return <section className="panel signal-details" aria-label="Signal details"><p className="empty-state">Select a signal to inspect its DBC definition.</p></section>
  }
  const { message, signal } = selection
  const activeBits = new Set(signalBits(signal))
  return (
    <section className="panel signal-details" aria-label="Signal details">
      <div className="panel-heading"><div><p className="eyebrow">Signal definition</p><h3>{signal.name}</h3></div><code>{selection.signalId}</code></div>
      <dl className="definition-grid">
        <div><dt>Message</dt><dd>{message.name}</dd></div>
        <div><dt>Start</dt><dd>start bit {signal.startBit}</dd></div>
        <div><dt>Width</dt><dd>length {signal.length}</dd></div>
        <div><dt>Byte order</dt><dd>{signal.byteOrder}</dd></div>
        <div><dt>Signedness</dt><dd>{signal.signed ? 'signed' : 'unsigned'}</dd></div>
        <div><dt>Scale</dt><dd>factor {signal.factor}</dd></div>
        <div><dt>Bias</dt><dd>offset {signal.offset}</dd></div>
        <div><dt>Unit</dt><dd>unit {signal.unit || '—'}</dd></div>
      </dl>
      <div className="bit-layout" aria-label={`64-bit layout for ${signal.name}`}>
        {Array.from({ length: 64 }, (_, bit) => (
          <span className="bit-cell" data-active={activeBits.has(bit) ? 'true' : 'false'} data-bit={bit} key={bit} title={`bit ${bit}`}>{bit}</span>
        ))}
      </div>
      <div className="enum-values"><span className="label">Enum</span>
        {Object.keys(signal.values).length === 0 ? <span>None</span> : (
          <ul>{Object.entries(signal.values).map(([value, label]) => <li key={value}><code>{value}</code> {label}</li>)}</ul>
        )}
      </div>
    </section>
  )
}

export const DbcExplorer = ({ database, assetMetadata, selectedSignalId, onSelectSignal }: DbcExplorerProps) => {
  const [query, setQuery] = useState('')
  const normalizedQuery = query.trim().toLowerCase()
  const visibleMessages = useMemo(
    () => database.messages.filter((message) => matchesQuery(message, normalizedQuery)),
    [database.messages, normalizedQuery],
  )
  const selection = useMemo(() => {
    for (const message of database.messages) {
      const signal = message.signals.find((candidate) => createSignalId(message, candidate.name) === selectedSignalId)
      if (signal !== undefined) return { message, signal, signalId: createSignalId(message, signal.name) }
    }
    return null
  }, [database.messages, selectedSignalId])

  return (
    <section className="workspace-section explorer-section" aria-labelledby="dbc-explorer-title">
      <div className="section-heading"><div><p className="eyebrow">Schema map</p><h2 id="dbc-explorer-title">DBC Explorer</h2></div><span className="count-pill">{database.messages.length} messages</span></div>
      <section className="provenance-strip" aria-label="DBC asset provenance">
        <div><span className="label">Source</span>{assetMetadata.asset.source}</div>
        <div><span className="label">Version</span>v{assetMetadata.asset.version}</div>
        <div><span className="label">License</span>{assetMetadata.asset.license}</div>
        <div className="hash"><span className="label">SHA-256</span><code>{assetMetadata.asset.sha256}</code></div>
        <div><span className="label">Vectors</span>validation vectors v{assetMetadata.validation_vectors.version}</div>
      </section>
      <div className="explorer-grid">
        <div className="panel message-browser">
          <label className="search-field"><span>Search DBC</span><input aria-label="Search DBC" onChange={(event) => setQuery(event.target.value)} placeholder="Signal, message, or CAN ID" type="search" value={query} /></label>
          <div className="message-tree" role="tree" aria-label="DBC hierarchy">
            {visibleMessages.map((message) => (
              <article className="message-node" key={`${message.isExtended}-${message.id}`} role="treeitem">
                <header><div><strong>{message.name}</strong><code>{formatCanId(message.id, message.isExtended)}</code></div><span>{message.signals.length} signals</span></header>
                <ul>{message.signals.filter((signal) => normalizedQuery.length === 0 || message.name.toLowerCase().includes(normalizedQuery) || formatCanId(message.id, message.isExtended).toLowerCase().includes(normalizedQuery) || signal.name.toLowerCase().includes(normalizedQuery)).map((signal) => {
                  const signalId = createSignalId(message, signal.name)
                  return <li key={signal.name}><button aria-label={signal.name} aria-pressed={signalId === selectedSignalId} className="signal-button" onClick={() => onSelectSignal({ message, signal, signalId })} type="button"><span>{signal.name}</span><small>{signal.startBit}:{signal.length}</small></button></li>
                })}</ul>
              </article>
            ))}
          </div>
        </div>
        <SignalDetails selection={selection} />
      </div>
    </section>
  )
}
