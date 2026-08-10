// RedBlue Sovereignty & Sensors (prompt §26-27) — ADDITIVE overlay.
// Component health the coordinator can ACTUALLY probe (/api/coordinator/sensors): itself, a live Neo4j
// connectivity check, and the telemetry sensors declared `external` (owned by the telemetry stack, not
// faked here). The inference topology + residency facts are the sovereign architecture (Decepticon /
// Vigil → local model layer, zero foreign egress) — labelled as such, not measured metrics.
import { useEffect, useState } from 'react'
import { EmptyState } from '../../shared/ui'
import { coordinatorApi, type Sensor } from '../../../services/coordinatorApi'
import type { ScreenProps } from '../../shared/types'
import { Panel, Kpi, StatusPill, TONE, asArray } from '../redblue/kit'

export default function SovereigntyScreen(_props: ScreenProps) {
  const [sensors, setSensors] = useState<Sensor[]>([])
  const [phase, setPhase] = useState<'loading' | 'ready' | 'error'>('loading')

  useEffect(() => {
    let live = true
    const load = () => coordinatorApi.getSensors()
      .then(({ data }) => { if (live) { setSensors(asArray<Sensor>(data, 'sensors', 'data')); setPhase('ready') } })
      .catch(() => { if (live) setPhase('error') })
    load(); const t = setInterval(load, 15_000); return () => { live = false; clearInterval(t) }
  }, [])

  const chain = (title: string, tone: keyof typeof TONE, nodes: [string, string][]) => (
    <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line)', borderRadius: 10, padding: 12 }}>
      <div style={{ fontSize: 10.5, textTransform: 'uppercase', letterSpacing: '.05em', color: 'var(--tx-faint)', marginBottom: 10 }}>{title}</div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 0, overflowX: 'auto' }}>
        {nodes.map(([n, s], i) => (
          <div key={n} style={{ display: 'flex', alignItems: 'center', flex: '0 0 auto' }}>
            <div style={{ minWidth: 100, textAlign: 'center', border: `1px solid ${TONE[tone]}55`, borderRadius: 8, padding: '8px 10px' }}>
              <div style={{ fontSize: 12.5, fontWeight: 650 }}>{n}</div>
              <div style={{ fontSize: 10, color: 'var(--tx-3)', fontFamily: 'var(--mono)' }}>{s}</div>
            </div>
            {i < nodes.length - 1 && <span style={{ width: 22, height: 2, background: TONE[tone], flex: '0 0 auto' }} />}
          </div>
        ))}
      </div>
    </div>
  )

  return (
    <div style={{ display: 'grid', gap: 16, padding: 16 }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 12 }}>
        <Kpi label="Foreign API egress" value="0" tone="green" />
        <Kpi label="Model location" value="Local" tone="green" />
        <Kpi label="Inference" value="On-Prem" tone="green" />
        <Kpi label="Data residency" value="India" tone="green" />
      </div>

      <Panel title="Sensor & component health" right={<span style={{ fontSize: 11, color: 'var(--tx-faint)' }}>live probe · 15s</span>}>
        {phase === 'loading' ? <EmptyState compact icon="clock" loading title="Probing components…" />
          : phase === 'error' ? <EmptyState compact icon="alert" error title="Sensors API unavailable" body="Is the coordinator reachable at /api/coordinator/sensors?" />
          : <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 12 }}>
              {sensors.map((s) => (
                <div key={s.name} style={{ padding: 12, borderRadius: 10, background: 'var(--bg-2)', border: '1px solid var(--line)' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <b style={{ fontSize: 13 }}>{s.name}</b><span style={{ flex: 1 }} /><StatusPill status={s.status} />
                  </div>
                  <div style={{ fontSize: 11.5, color: 'var(--tx-3)', marginTop: 4 }}>{s.kind}</div>
                  <div style={{ display: 'flex', gap: 12, marginTop: 8, fontSize: 11, color: 'var(--tx-faint)', flexWrap: 'wrap' }}>
                    {s.latency_ms != null && <span style={{ fontFamily: 'var(--mono)' }}>{s.latency_ms} ms</span>}
                    {s.source && <span>via {s.source}</span>}
                  </div>
                  {s.note && <div style={{ fontSize: 10.5, color: 'var(--tx-faint)', marginTop: 6 }}>ⓘ {s.note}</div>}
                </div>
              ))}
            </div>}
      </Panel>

      <Panel title="Sovereign inference topology">
        <div style={{ display: 'grid', gap: 12 }}>
          {chain('Red path', 'red', [['Decepticon', '25 agents'], ['LiteLLM', 'router'], ['Ollama', 'runtime'], ['Local Model', 'qwen2.5']])}
          {chain('Blue path', 'blue', [['Vigil', '13 agents'], ['Bifrost', 'gateway'], ['Ollama', 'runtime'], ['Local Model', 'foundation-sec']])}
        </div>
        <div style={{ fontSize: 11, color: 'var(--tx-faint)', marginTop: 10 }}>ⓘ Both engines route inference through the on-prem model layer. The only cross-boundary flow is sanitized graph/finding data to the coordinator — no model weights or telemetry leave the tenant.</div>
      </Panel>
    </div>
  )
}
