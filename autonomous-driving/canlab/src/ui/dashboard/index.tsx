import type { CSSProperties } from 'react'

import { DASHBOARD_GAUGE_SIGNALS, DASHBOARD_TREND_SIGNALS, type DashboardProjection } from '../../domain/dashboard/index.ts'

export interface VehicleDashboardProps { readonly projection: DashboardProjection }
const titleCaseSignal = (name: string): string => name.replace(/([a-z])([A-Z])/g, '$1 $2')

export const VehicleDashboard = ({ projection }: VehicleDashboardProps) => (
  <section aria-label="Vehicle dashboard" className="workspace-section dashboard-section" data-projection-time={projection.replayTimeUs}>
    <div className="section-heading"><div><p className="eyebrow">One event-time projection</p><h2>Virtual vehicle</h2></div><span className="projection-clock">T = {projection.replayTimeUs} µs</span></div>
    <div className="gauge-grid">{DASHBOARD_GAUGE_SIGNALS.map((signalName) => {
      const sample = projection.gauges[signalName]
      return <article className="panel gauge-card" data-testid={`gauge-${signalName}`} key={signalName}><span className="label">{titleCaseSignal(signalName)}</span><strong>{sample?.displayValue ?? '—'}</strong><small>{sample === null ? 'Awaiting frame' : `sampled ${sample.timestampUs} µs`}</small></article>
    })}</div>
    <div className="dashboard-grid">
      <section className="panel trends-panel" aria-label="Event-time trends"><div className="panel-heading"><div><p className="eyebrow">Replay event time</p><h3>Six fixed trends</h3></div></div>
        <div className="trend-grid">{DASHBOARD_TREND_SIGNALS.map((signalName) => (
          <figure data-testid="trend-panel" key={signalName}><figcaption>{titleCaseSignal(signalName)}</figcaption><div className="trend-points" data-testid={`trend-${signalName}`}>
            {projection.trends[signalName].length === 0 ? <span className="empty-state">No samples</span> : projection.trends[signalName].map((point, index) => (
              <span className="trend-point" key={`${point.timestampUs}-${index}`} style={{ '--trend-value': point.physicalValue } as CSSProperties}><i aria-hidden="true" /><small>{point.timestampUs} µs</small><strong>{point.displayValue}</strong></span>
            ))}
          </div></figure>
        ))}</div>
      </section>
      <section className="panel health-panel" aria-label="Message health"><div className="panel-heading"><div><p className="eyebrow">DBC cycle health</p><h3>Message health</h3></div></div>
        <div className="health-table" role="table">{projection.health.map((metric) => (
          <div className={`health-row ${metric.stale === true ? 'is-stale' : ''}`} data-testid={`health-${metric.canId}`} key={metric.canId} role="row"><div role="cell"><strong>{metric.messageName}</strong><code>{metric.canId}</code></div><div role="cell">stale {metric.stale === null ? 'N/A' : metric.stale ? 'yes' : 'no'}</div><div role="cell">missing {metric.inferredMissingFrames ?? 'N/A'}</div><div role="cell">{metric.frequencyHz} Hz</div></div>
        ))}</div>
      </section>
    </div>
  </section>
)
