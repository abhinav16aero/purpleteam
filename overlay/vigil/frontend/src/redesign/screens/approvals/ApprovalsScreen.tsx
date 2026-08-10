// RedBlue Approvals — Human-in-the-Loop (prompt §24, §43) — ADDITIVE overlay.
// The real pending-action queue from Vigil (/api/approvals/pending). Approve/Reject POST to the real
// endpoints. The AUTO / HUMAN / NEVER-AUTO tiers are the architecture's governance policy (static,
// authoritative), shown so an operator sees why an action is gated. Only real action fields render.
import { useCallback, useEffect, useState, type CSSProperties } from 'react'
import { EmptyState } from '../../shared/ui'
import { approvalsApi } from '../../../services/api'
import type { ScreenProps } from '../../shared/types'
import { Panel, Tag, TONE, asArray } from '../redblue/kit'

interface Action {
  action_id: string
  action_type?: string
  title?: string
  description?: string
  target?: string
  confidence?: number
  reason?: string
  evidence?: unknown
  created_by?: string
  created_at?: string
  status?: string
}

const evidenceCount = (e: unknown) => (Array.isArray(e) ? e.length : e ? 1 : 0)

export default function ApprovalsScreen(_props: ScreenProps) {
  const [actions, setActions] = useState<Action[]>([])
  const [phase, setPhase] = useState<'loading' | 'ready' | 'error'>('loading')
  const [busy, setBusy] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const { data } = await approvalsApi.listPending()
      setActions(asArray<Action>(data, 'actions', 'pending', 'data'))
      setPhase('ready')
    } catch { setPhase('error') }
  }, [])
  useEffect(() => { load(); const t = setInterval(load, 10_000); return () => clearInterval(t) }, [load])

  const decide = async (a: Action, approve: boolean) => {
    setBusy(a.action_id)
    try {
      if (approve) await approvalsApi.approve(a.action_id, 'operator')
      else {
        const reason = window.prompt('Reason for rejecting this action?') || 'rejected by operator'
        await approvalsApi.reject(a.action_id, reason, 'operator')
      }
      await load()
    } catch { /* surfaces on next poll */ } finally { setBusy(null) }
  }

  return (
    <div style={{ display: 'grid', gap: 16, padding: 16 }}>
      {/* governance tiers (§24) */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 12 }}>
        <Tier tone="green" name="AUTO" body="Low-risk, reversible actions run automatically." examples="enrich · tag · notify" />
        <Tier tone="amber" name="HUMAN" body="High-impact actions require operator approval — every time." examples="isolate · block · quarantine" />
        <Tier tone="red" name="NEVER AUTO" body="Tenant-boundary / control-plane actions are never automated." examples="cross-tenant · disable-control" />
      </div>

      <Panel title="Pending approvals" right={<span style={{ fontSize: 11, color: 'var(--tx-faint)' }}>{actions.length} awaiting decision</span>}>
        {phase === 'loading' ? <EmptyState compact icon="clock" loading title="Loading approvals…" />
          : phase === 'error' ? <EmptyState compact icon="alert" error title="Approvals API unavailable" body="Is Vigil reachable at /api/approvals/pending?" />
          : actions.length === 0 ? <EmptyState compact icon="check2" title="No pending approvals" body="All clear — no gated actions awaiting a human." />
          : <div style={{ display: 'grid', gap: 12 }}>
              {actions.map((a) => (
                <div key={a.action_id} style={{ border: `1px solid ${TONE.amber}44`, borderLeft: `3px solid ${TONE.amber}`, borderRadius: 10, padding: 14, background: 'var(--bg-2)' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                    <Tag tone="amber">ACTION REQUEST</Tag>
                    <b style={{ fontSize: 14 }}>{a.title || a.action_type || a.action_id}</b>
                    <span style={{ flex: 1 }} />
                    {a.confidence != null && <Tag tone="violet">conf {Math.round(a.confidence * 100)}%</Tag>}
                    {a.action_type && <Tag tone="blue">{a.action_type}</Tag>}
                  </div>
                  {a.description && <div style={{ fontSize: 12.5, color: 'var(--tx-2)', marginTop: 8 }}>{a.description}</div>}
                  <div style={{ display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '4px 14px', fontSize: 12, marginTop: 10, color: 'var(--tx-2)' }}>
                    {a.reason && <><span style={{ color: 'var(--tx-faint)' }}>Reason</span><span>{a.reason}</span></>}
                    {a.target && <><span style={{ color: 'var(--tx-faint)' }}>Target</span><span style={{ fontFamily: 'var(--mono)' }}>{a.target}</span></>}
                    <span style={{ color: 'var(--tx-faint)' }}>Requested by</span><span>{a.created_by || '—'}</span>
                    <span style={{ color: 'var(--tx-faint)' }}>Evidence</span><span>{evidenceCount(a.evidence)} artifact(s)</span>
                    <span style={{ color: 'var(--tx-faint)' }}>Policy</span><span><Tag tone="amber">HUMAN APPROVAL</Tag></span>
                  </div>
                  <div style={{ display: 'flex', gap: 8, marginTop: 14 }}>
                    <button disabled={busy === a.action_id} onClick={() => decide(a, false)} style={btn(TONE.red)}>Reject</button>
                    <span style={{ flex: 1 }} />
                    <button disabled={busy === a.action_id} onClick={() => decide(a, true)} style={btn(TONE.green, true)}>{busy === a.action_id ? '…' : 'Approve'}</button>
                  </div>
                </div>
              ))}
            </div>}
      </Panel>
    </div>
  )
}

const btn = (color: string, solid = false): CSSProperties => ({
  background: solid ? color : `${color}18`, color: solid ? '#04140b' : color,
  border: `1px solid ${color}55`, borderRadius: 8, padding: '7px 14px', fontSize: 12.5, fontWeight: 650, cursor: 'pointer',
})
function Tier({ tone, name, body, examples }: { tone: keyof typeof TONE; name: string; body: string; examples: string }) {
  return (
    <div style={{ padding: 14, borderRadius: 12, background: 'var(--panel)', border: '1px solid var(--line)' }}>
      <Tag tone={tone}>{name}</Tag>
      <div style={{ fontSize: 12.5, color: 'var(--tx-2)', marginTop: 10 }}>{body}</div>
      <div style={{ fontSize: 11, color: 'var(--tx-3)', marginTop: 8, fontFamily: 'var(--mono)' }}>{examples}</div>
    </div>
  )
}
