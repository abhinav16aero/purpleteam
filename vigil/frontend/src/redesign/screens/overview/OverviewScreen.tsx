// RedBlue Command Center (prompt §4-7, §39) — ADDITIVE overlay.
// The landing situation view. Every number is LIVE: posture + engagements from the coordinator, pending
// approvals + recent AI decisions from Vigil's own API. The purple-team loop is the architecture
// pipeline (structural, not fabricated data) with real counts pinned onto its stages. Primitives +
// CSS-var tokens are Vigil's; no new dependency.
import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { EmptyState } from '../../shared/ui'
import { coordinatorApi, type Posture } from '../../../services/coordinatorApi'
import { approvalsApi, aiDecisionsApi } from '../../../services/api'
import type { ScreenProps } from '../../shared/types'

interface Engagement { engagement_id: string; tenant_id?: string; status?: string; target?: string; detection_rate?: number | null }
interface Approval { id?: string; action_id?: string; action?: string; title?: string; risk?: string; status?: string }
interface Decision { id?: string; decision_id?: string; action?: string; summary?: string; title?: string; status?: string; created_at?: string; timestamp?: string }

const asArray = <T,>(d: unknown, ...keys: string[]): T[] => {
  if (Array.isArray(d)) return d as T[]
  const o = (d ?? {}) as Record<string, unknown>
  for (const k of keys) if (Array.isArray(o[k])) return o[k] as T[]
  return []
}
const fmtSecs = (s: number | null | undefined) => (s == null ? '—' : s < 60 ? `${Math.round(s)}s` : `${Math.round(s / 60)}m`)

const TONE: Record<string, string> = { red: '#e05561', blue: '#4f8ef0', green: '#35c46b', amber: '#e0a340', violet: '#9d7ff0' }

export default function OverviewScreen(props: ScreenProps) {
  const [posture, setPosture] = useState<Posture | null>(null)
  const [engagements, setEngagements] = useState<Engagement[]>([])
  const [approvals, setApprovals] = useState<Approval[]>([])
  const [decisions, setDecisions] = useState<Decision[]>([])
  const [phase, setPhase] = useState<'loading' | 'ready' | 'error'>('loading')

  useEffect(() => {
    let live = true
    const load = async () => {
      try {
        const [p, e] = await Promise.all([coordinatorApi.getPosture(), coordinatorApi.listEngagements()])
        // Vigil-side panels are best-effort — a missing SOC API must not blank the whole command center.
        const [ap, de] = await Promise.allSettled([approvalsApi.listPending(), aiDecisionsApi.list({ limit: 8 })])
        if (!live) return
        setPosture(p.data)
        setEngagements(asArray<Engagement>(e.data, 'engagements', 'data'))
        setApprovals(ap.status === 'fulfilled' ? asArray<Approval>(ap.value.data, 'approvals', 'pending', 'data') : [])
        setDecisions(de.status === 'fulfilled' ? asArray<Decision>(de.value.data, 'decisions', 'data') : [])
        setPhase('ready')
      } catch { if (live) setPhase('error') }
    }
    load()
    const t = setInterval(load, 10_000)
    return () => { live = false; clearInterval(t) }
  }, [])

  const activeEng = useMemo(() => engagements.filter((e) => e.status === 'running').length, [engagements])
  const rate = posture?.detection_rate != null ? Math.round(posture.detection_rate * 100) : null
  const cov = posture?.attack_coverage
  const covPct = cov && cov.attacked ? Math.round((cov.detected / cov.attacked) * 100) : null

  if (phase === 'loading') return <EmptyState icon="clock" loading title="Loading command center…" />
  if (phase === 'error' || !posture)
    return <EmptyState icon="alert" error title="Coordinator unavailable"
      body="Is the RedBlue coordinator reachable at /api/coordinator (proxy to :8900)?"
      primary={{ label: 'System settings', onClick: () => props.goSettings('system') }} />

  const loop: [string, string, string, string][] = [
    ['red', 'RED TEAM', 'Decepticon', `${activeEng} running`],
    ['red', 'ATTACK', 'techniques', `${posture.totals.attacked} fired`],
    ['red', 'TARGET', engagements[0]?.target || 'in-scope', 'authorised'],
    ['blue', 'SENSORS', 'Wazuh·Suricata·Falco', 'telemetry'],
    ['blue', 'BLUE TEAM', 'Vigil', `${posture.totals.detected} detected`],
    ['green', 'COORDINATOR', 'LangGraph', 'scoring'],
    ['green', 'SCORE', 'detection rate', rate != null ? `${rate}%` : '—'],
    ['amber', 'GOVERNANCE', 'HITL', `${approvals.length} pending`],
    ['violet', 'EVIDENCE', 'ledger', 'hash-chained'],
  ]

  return (
    <div style={{ display: 'grid', gap: 16, padding: 16 }}>
      {/* hero */}
      <section style={{ ...panel, padding: '20px 22px' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 20, flexWrap: 'wrap' }}>
          <div>
            <div style={{ fontSize: 11, letterSpacing: '.14em', color: 'var(--tx-faint)', fontFamily: 'var(--mono)' }}>SECURITY OPERATIONS · SOVEREIGN MODE</div>
            <h1 style={{ margin: '8px 0 4px', fontSize: 22 }}>Your environment is being continuously validated.</h1>
            <div style={{ color: 'var(--tx-2)', fontSize: 13 }}>{activeEng} engagement{activeEng === 1 ? '' : 's'} running · purple-team loop active · local inference · <b style={{ color: TONE.green }}>egress 0</b></div>
          </div>
          <span style={{ flex: 1 }} />
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 10, color: 'var(--tx-faint)', textTransform: 'uppercase', letterSpacing: '.05em' }}>Detection rate</div>
            <div style={{ fontSize: 44, fontWeight: 750, lineHeight: 1.05, color: TONE.green, fontFamily: 'var(--mono)' }}>{rate != null ? `${rate}%` : '—'}</div>
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8, marginTop: 14, flexWrap: 'wrap' }}>
          <button className="btn" style={cta(true)} onClick={() => props.go('engagements')}>Launch engagement</button>
          <button className="btn" style={cta(false)} onClick={() => props.go('knowledgegraph')}>Knowledge graph</button>
          <button className="btn" style={cta(false)} onClick={() => props.go('posture')}>Posture detail</button>
        </div>
      </section>

      {/* KPI row */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 12 }}>
        <Kpi label="Detection rate" value={rate != null ? `${rate}%` : '—'} tone="green" onClick={() => props.go('posture')} />
        <Kpi label="MTTD (mean)" value={fmtSecs(posture.mttd.mean)} tone="blue" onClick={() => props.go('posture')} />
        <Kpi label="Active engagements" value={String(activeEng)} tone="violet" onClick={() => props.go('engagements')} />
        <Kpi label="Pending approvals" value={String(approvals.length)} tone="amber" onClick={() => props.go('decisions')} />
        <Kpi label="ATT&CK coverage" value={covPct != null ? `${covPct}%` : '—'} tone="violet" onClick={() => props.go('posture')} />
        <Kpi label="Coverage gaps" value={String(posture.gap_count)} tone="red" onClick={() => props.go('posture')} />
      </div>

      {/* live purple-team loop (structural pipeline, real counts) */}
      <section style={panel}>
        <div style={secTitle}>Live Purple-Team Loop</div>
        <div style={{ display: 'flex', alignItems: 'stretch', gap: 6, overflowX: 'auto', paddingBottom: 4 }}>
          {loop.map(([tone, title, sub, meta], i) => (
            <div key={title} style={{ display: 'flex', alignItems: 'center', gap: 6, flex: '1 0 auto' }}>
              <div style={{ minWidth: 108, border: `1px solid ${TONE[tone]}`, borderRadius: 10, padding: '9px 10px', background: 'var(--bg-2)', boxShadow: `0 0 0 3px ${TONE[tone]}18` }}>
                <div style={{ fontSize: 9, letterSpacing: '.08em', color: 'var(--tx-faint)', fontFamily: 'var(--mono)' }}>STAGE {i + 1}</div>
                <div style={{ fontSize: 12.5, fontWeight: 650, marginTop: 2 }}>{title}</div>
                <div style={{ fontSize: 10.5, color: 'var(--tx-3)', fontFamily: 'var(--mono)' }}>{sub}</div>
                <div style={{ fontSize: 10.5, color: TONE[tone], fontFamily: 'var(--mono)', marginTop: 2 }}>{meta}</div>
              </div>
              {i < loop.length - 1 && <span style={{ color: 'var(--tx-faint)' }}>→</span>}
            </div>
          ))}
        </div>
      </section>

      {/* two columns: engagements + pending approvals */}
      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 16 }}>
        <section style={panel}>
          <div style={secTitle}>Active Engagements</div>
          {engagements.length === 0
            ? <EmptyState compact icon="bolt" title="No engagements yet" body="Launch one to drive the loop." />
            : <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12.5 }}>
                <tbody>
                  {engagements.slice(0, 6).map((e) => (
                    <tr key={e.engagement_id} style={{ cursor: 'pointer', borderBottom: '1px solid var(--line-soft)' }} onClick={() => props.go('engagements')}>
                      <td style={{ padding: '8px 6px', fontFamily: 'var(--mono)', fontSize: 11.5 }}>{e.engagement_id}</td>
                      <td style={{ padding: '8px 6px' }}>{e.target || '—'}</td>
                      <td style={{ padding: '8px 6px' }}><StatusPill status={e.status} /></td>
                      <td style={{ padding: '8px 6px', fontFamily: 'var(--mono)', textAlign: 'right' }}>{e.detection_rate != null ? `${Math.round(e.detection_rate * 100)}%` : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>}
        </section>

        <section style={panel}>
          <div style={secTitle}>Pending Approvals</div>
          {approvals.length === 0
            ? <EmptyState compact icon="check2" title="No pending approvals" />
            : approvals.slice(0, 6).map((a, i) => (
                <div key={a.id || a.action_id || i} style={{ display: 'flex', justifyContent: 'space-between', gap: 10, padding: '8px 0', borderBottom: '1px solid var(--line-soft)', cursor: 'pointer' }} onClick={() => props.go('decisions')}>
                  <span style={{ fontSize: 12.5 }}>{a.action || a.title || a.action_id || a.id}</span>
                  <span style={{ fontSize: 10.5, fontFamily: 'var(--mono)', color: TONE.amber, whiteSpace: 'nowrap' }}>{(a.risk || 'HUMAN').toUpperCase()}</span>
                </div>
              ))}
        </section>
      </div>

      {/* recent AI activity (real decisions) */}
      <section style={panel}>
        <div style={secTitle}>Recent AI Activity <span style={{ fontSize: 10, color: 'var(--tx-faint)' }}>· from AI Decisions</span></div>
        {decisions.length === 0
          ? <EmptyState compact icon="brain" title="No recent AI decisions" body="The daemon writes decisions here as it triages." />
          : decisions.slice(0, 8).map((d, i) => (
              <div key={d.id || d.decision_id || i} style={{ display: 'flex', gap: 12, alignItems: 'center', padding: '7px 0', borderBottom: '1px solid var(--line-soft)', fontSize: 12.5, cursor: 'pointer' }} onClick={() => props.go('decisions')}>
                <span style={{ fontFamily: 'var(--mono)', fontSize: 10.5, color: 'var(--tx-faint)', minWidth: 64 }}>{(d.created_at || d.timestamp || '').toString().slice(11, 19) || '—'}</span>
                <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{d.action || d.summary || d.title || 'AI decision'}</span>
                {d.status && <StatusPill status={d.status} />}
              </div>
            ))}
      </section>
    </div>
  )
}

/* ---------- small local presentational bits (Vigil-token styled) ---------- */
const panel: CSSProperties = { padding: 15, borderRadius: 12, background: 'var(--panel)', border: '1px solid var(--line)' }
const secTitle: CSSProperties = { fontSize: 12, fontWeight: 650, marginBottom: 12, color: 'var(--tx-2)', textTransform: 'uppercase', letterSpacing: '.05em' }
const cta = (primary: boolean): CSSProperties => ({
  background: primary ? 'var(--accent)' : 'var(--bg-2)', color: primary ? '#fff' : 'var(--tx)',
  border: '1px solid var(--line)', borderRadius: 8, padding: '7px 12px', fontSize: 12.5, cursor: 'pointer', fontWeight: primary ? 650 : 500,
})

function Kpi({ label, value, tone, onClick }: { label: string; value: string; tone: keyof typeof TONE; onClick?: () => void }) {
  return (
    <div onClick={onClick} style={{ padding: 14, borderRadius: 10, background: 'var(--bg-2)', border: '1px solid var(--line)', cursor: onClick ? 'pointer' : 'default' }}>
      <div style={{ fontSize: 10.5, opacity: 0.7, textTransform: 'uppercase', letterSpacing: '.05em' }}>{label}</div>
      <div style={{ fontSize: 26, fontWeight: 700, color: TONE[tone], fontFamily: 'var(--mono)' }}>{value}</div>
    </div>
  )
}
function StatusPill({ status }: { status?: string }) {
  const s = (status || '').toLowerCase()
  const c = s.includes('run') || s.includes('pend') ? TONE.amber : s.includes('fail') || s.includes('reject') ? TONE.red : s.includes('complet') || s.includes('approv') ? TONE.green : 'var(--tx-3)'
  return <span style={{ fontSize: 10.5, fontFamily: 'var(--mono)', color: c, border: `1px solid ${c}55`, borderRadius: 99, padding: '2px 8px', whiteSpace: 'nowrap' }}>{status || '—'}</span>
}
