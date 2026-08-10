// RedBlue AI Agents (prompt §22) — ADDITIVE overlay.
// Composes the REAL rosters: Vigil's blue agents (/api/agents/agents) + the coordinator's honest
// red-run rollup (/api/coordinator/agents). No fabricated per-agent telemetry — the coordinator itself
// declares that Decepticon's per-agent detail is internal, so this shows red *runs*, not invented agents.
import { useEffect, useState } from 'react'
import { EmptyState } from '../../shared/ui'
import { coordinatorApi, type RedRun } from '../../../services/coordinatorApi'
import { agentsApi } from '../../../services/api'
import type { ScreenProps } from '../../shared/types'
import { Panel, Kpi, StatusPill, Tag, TONE, asArray, targetText } from '../redblue/kit'

interface BlueAgent { id?: string; agent_id?: string; name?: string; display_name?: string; role?: string; description?: string; status?: string; enabled?: boolean; model?: string }

export default function AiAgentsScreen(props: ScreenProps) {
  const [blue, setBlue] = useState<BlueAgent[]>([])
  const [red, setRed] = useState<RedRun[]>([])
  const [note, setNote] = useState('')
  const [phase, setPhase] = useState<'loading' | 'ready' | 'error'>('loading')

  useEffect(() => {
    let live = true
    const load = async () => {
      const [b, r] = await Promise.allSettled([agentsApi.listAgents(), coordinatorApi.getAgents()])
      if (!live) return
      if (b.status === 'rejected' && r.status === 'rejected') { setPhase('error'); return }
      setBlue(b.status === 'fulfilled' ? asArray<BlueAgent>(b.value.data, 'agents', 'data') : [])
      if (r.status === 'fulfilled') { setRed(r.value.data.runs || []); setNote(r.value.data.note || '') }
      setPhase('ready')
    }
    load(); const t = setInterval(load, 10_000); return () => { live = false; clearInterval(t) }
  }, [])

  if (phase === 'loading') return <EmptyState icon="clock" loading title="Loading AI agents…" />
  if (phase === 'error') return <EmptyState icon="alert" error title="Agent APIs unavailable" body="Neither Vigil (/api/agents) nor the coordinator (/api/coordinator/agents) responded." />

  const redActive = red.filter((r) => r.status === 'running').length

  return (
    <div style={{ display: 'grid', gap: 16, padding: 16 }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 12 }}>
        <Kpi label="Blue agents (Vigil)" value={String(blue.length)} tone="blue" />
        <Kpi label="Red runs (Decepticon)" value={String(red.length)} tone="red" sub={`${redActive} running`} />
        <Kpi label="Coordinator" value="LangGraph" tone="green" />
        <Kpi label="Inference" value="local" tone="violet" sub="Ollama · on-prem" />
      </div>

      <Panel title={<><span style={{ width: 8, height: 8, borderRadius: 99, background: TONE.blue, display: 'inline-block' }} /> Blue Team agents · Vigil</>}>
        {blue.length === 0
          ? <EmptyState compact icon="bot" title="No blue agents reported" body="Vigil's /api/agents returned an empty roster." />
          : <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: 12 }}>
              {blue.map((a, i) => (
                <div key={a.agent_id || a.id || i} style={{ padding: 12, borderRadius: 10, background: 'var(--bg-2)', border: '1px solid var(--line)' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ width: 24, height: 24, borderRadius: 6, background: TONE.blue, display: 'grid', placeItems: 'center', color: '#fff', fontWeight: 700, fontSize: 11 }}>{(a.name || a.display_name || 'A')[0].toUpperCase()}</span>
                    <b style={{ fontSize: 13 }}>{a.name || a.display_name || a.agent_id || a.id}</b>
                    <span style={{ flex: 1 }} />
                    <StatusPill status={a.status || (a.enabled === false ? 'disabled' : 'ready')} />
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--tx-2)', marginTop: 8, minHeight: 32 }}>{a.role || a.description || '—'}</div>
                  {a.model && <div style={{ marginTop: 8 }}><Tag tone="violet">{a.model}</Tag></div>}
                </div>
              ))}
            </div>}
      </Panel>

      <Panel title={<><span style={{ width: 8, height: 8, borderRadius: 99, background: TONE.red, display: 'inline-block' }} /> Red-team runs · Decepticon</>}
        right={<button onClick={() => props.go('engagements')} style={{ background: 'var(--bg-2)', color: 'var(--tx)', border: '1px solid var(--line)', borderRadius: 8, padding: '5px 10px', fontSize: 12, cursor: 'pointer' }}>Engagements</button>}>
        {red.length === 0
          ? <EmptyState compact icon="bolt" title="No red runs" body="Launch an engagement to start a Decepticon red run." />
          : <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12.5 }}>
              <tbody>
                {red.map((r) => (
                  <tr key={r.engagement_id} style={{ borderBottom: '1px solid var(--line-soft)', cursor: 'pointer' }} onClick={() => props.go('engagements')}>
                    <td style={{ padding: '8px 6px', fontFamily: 'var(--mono)', fontSize: 11.5 }}>{r.engagement_id}</td>
                    <td style={{ padding: '8px 6px' }}>{targetText(r.target) || '—'}</td>
                    <td style={{ padding: '8px 6px', color: 'var(--tx-3)' }}>{r.role}</td>
                    <td style={{ padding: '8px 6px', textAlign: 'right' }}><StatusPill status={r.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>}
        {note && <div style={{ fontSize: 11, color: 'var(--tx-faint)', marginTop: 10 }}>ⓘ {note}</div>}
      </Panel>
    </div>
  )
}
