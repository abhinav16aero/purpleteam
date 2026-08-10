// RedBlue Engagements — launch + monitor (plan 09 §1.3) — ADDITIVE overlay.
// Control bar (launch + kill switch), the engagement queue, and a workspace with the SSE LIVE TIMELINE
// (prompt §16): the coordinator's ONE event stream (/api/coordinator/engagements/:id/events) parsed
// into structured, source-lane rows that interleave red actions, blue detections, scoring and gates.
// Reuses DataTable + streamFetch + the RedBlue kit; the kill switch is the always-visible 00 §10 rule.
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import { DataTable, useTableSort, type ColumnDef } from '../../shared/DataTable'
import { EmptyState } from '../../shared/ui'
import { coordinatorApi, type AttackPlan } from '../../../services/coordinatorApi'
import { streamFetch } from '../../../services/api'
import type { ScreenProps } from '../../shared/types'
import { Panel, Tag, StatusPill, TONE } from '../redblue/kit'

interface EngagementRow {
  engagement_id: string
  tenant_id?: string
  mode?: string
  status?: string
  target?: string
  detection_rate?: number | null
}

export default function EngagementsScreen(props: ScreenProps) {
  const [rows, setRows] = useState<EngagementRow[]>([])
  const [phase, setPhase] = useState<'loading' | 'ready' | 'error'>('loading')
  const [tenant, setTenant] = useState('t01')
  const [target, setTarget] = useState('range-dvwa')
  const [mode, setMode] = useState<'on_demand' | 'continuous'>('on_demand')
  const [selected, setSelected] = useState<string | null>(null)

  const reload = useCallback(async () => {
    try {
      const { data } = await coordinatorApi.listEngagements()
      setRows(Array.isArray(data) ? data : (data?.engagements ?? []))
      setPhase('ready')
    } catch { setPhase('error') }
  }, [])
  useEffect(() => { reload(); const t = setInterval(reload, 10_000); return () => clearInterval(t) }, [reload])

  const launch = async () => {
    try {
      const in_scope = target.split(',').map((s) => s.trim()).filter(Boolean)
      const { data } = await coordinatorApi.launch({ tenant_id: tenant, mode, scope: { in_scope, sandbox_url: 'http://sandbox:9999' } })
      await reload()
      // a live HITL engagement pauses for plan review — jump straight to it
      const id = (data as { engagement_id?: string })?.engagement_id
      if (id) setSelected(id)
    } catch { /* the failure surfaces via `phase` on the next reload */ }
  }
  const kill = async () => {
    if (window.confirm('KILL SWITCH — halt ALL engagements globally?'))
      await coordinatorApi.kill('operator', 'manual global kill (console)')
  }

  const columns = useMemo<ColumnDef<EngagementRow>[]>(() => [
    { key: 'engagement_id', label: 'Engagement', render: (r) => r.engagement_id,
      sortVal: (r) => r.engagement_id, searchVal: (r) => r.engagement_id },
    { key: 'tenant_id', label: 'Tenant', render: (r) => r.tenant_id ?? '—', sortVal: (r) => r.tenant_id ?? '' },
    { key: 'mode', label: 'Mode', render: (r) => r.mode ?? 'on_demand' },
    { key: 'status', label: 'Status', render: (r) => <StatusPill status={r.status} />, sortVal: (r) => r.status ?? '' },
    { key: 'detection_rate', label: 'Detection', defaultDir: 'desc',
      render: (r) => (r.detection_rate == null ? '—' : `${Math.round(r.detection_rate * 100)}%`),
      sortVal: (r) => r.detection_rate ?? -1 },
  ], [])
  const { sort, toggle } = useTableSort(columns, { key: 'engagement_id', dir: 'asc' })
  const selRow = rows.find((r) => r.engagement_id === selected)

  return (
    <div style={{ display: 'grid', gap: 16, padding: 16 }}>
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
        <input value={tenant} onChange={(e) => setTenant(e.target.value)} placeholder="tenant" style={{ padding: 6, borderRadius: 6, width: 90 }} />
        <input value={target} onChange={(e) => setTarget(e.target.value)} placeholder="in-scope target(s)" style={{ padding: 6, borderRadius: 6, width: 180 }} />
        <select value={mode} onChange={(e) => setMode(e.target.value as 'on_demand' | 'continuous')} style={{ padding: 6 }}>
          <option value="on_demand">on-demand</option>
          <option value="continuous">continuous (CART)</option>
        </select>
        <button className="btn primary" onClick={launch}>Launch engagement</button>
        <div style={{ flex: 1 }} />
        <button className="btn" onClick={kill} style={{ background: 'var(--crit)', color: '#fff', fontWeight: 700 }}>■ KILL SWITCH</button>
      </div>

      {phase !== 'error' && rows.length === 0
        ? <EmptyState icon="bolt" title="No engagements yet" body="Launch a scoped red engagement with the controls above." />
        : <DataTable columns={columns} rows={rows} rowKey={(r) => r.engagement_id} phase={phase}
            error={phase === 'error' ? 'Coordinator unavailable' : null} sort={sort} onSort={toggle}
            onRowClick={(r) => setSelected(r.engagement_id)} />}

      {selected && (selRow?.status === 'awaiting_plan_approval'
        ? <PlanReviewPanel id={selected} onClose={() => setSelected(null)} onResolved={reload} />
        : <EngagementWorkspace id={selected} row={selRow} go={props.go} onClose={() => setSelected(null)} />)}
    </div>
  )
}

/* ---------------- attack-plan review (HITL) — see + edit + approve/reject before red runs ---------- */

function PlanReviewPanel({ id, onClose, onResolved }: { id: string; onClose: () => void; onResolved: () => void }) {
  const [plan, setPlan] = useState<AttackPlan | null>(null)
  const [phase, setPhase] = useState<'loading' | 'ready' | 'error'>('loading')
  const [objective, setObjective] = useState('')
  const [instruction, setInstruction] = useState('')
  const [inScope, setInScope] = useState('')
  const [busy, setBusy] = useState<null | 'save' | 'approve' | 'reject'>(null)
  const [msg, setMsg] = useState('')

  const load = useCallback(async () => {
    try {
      const { data } = await coordinatorApi.getPlan(id)
      setPlan(data.plan)
      setObjective(data.plan.objective || '')
      setInstruction(data.plan.instruction || '')
      setInScope((data.plan.in_scope || []).join(', '))
      setPhase('ready')
    } catch { setPhase('error') }
  }, [id])
  useEffect(() => { load() }, [load])

  const save = async () => {
    setBusy('save'); setMsg('')
    try {
      const { data } = await coordinatorApi.patchPlan(id, {
        objective, instruction, in_scope: inScope.split(',').map((s) => s.trim()).filter(Boolean),
      })
      setPlan(data.plan); setMsg('Plan updated — red will run the edited instruction.')
    } catch { setMsg('Save failed.') } finally { setBusy(null) }
  }
  const approve = async () => {
    setBusy('approve'); setMsg('Approved — red is executing, telemetry settling…')
    try { await coordinatorApi.approvePlan(id); onResolved(); onClose() }
    catch { setMsg('Approve failed — is the coordinator reachable?'); setBusy(null) }
  }
  const reject = async () => {
    const reason = window.prompt('Reason for rejecting this attack plan?') || 'rejected by operator'
    setBusy('reject')
    try { await coordinatorApi.rejectPlan(id, reason); onResolved(); onClose() }
    catch { setMsg('Reject failed.'); setBusy(null) }
  }

  const busyAny = busy !== null
  return (
    <Panel
      title={<>Attack plan review · <span style={{ fontFamily: 'var(--mono)', color: 'var(--tx)' }}>{id}</span></>}
      right={<button className="btn ghost" style={{ fontSize: 12 }} onClick={onClose}>Close</button>}
    >
      {phase === 'loading' ? <EmptyState compact icon="clock" loading title="Loading plan…" />
        : phase === 'error' || !plan ? <EmptyState compact icon="alert" error title="Plan unavailable" body="Is the engagement still awaiting approval?" />
        : <div style={{ display: 'grid', gap: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '9px 12px', borderRadius: 8, background: `${TONE.amber}14`, border: `1px solid ${TONE.amber}55`, flexWrap: 'wrap' }}>
              <span style={{ fontSize: 12, fontFamily: 'var(--mono)', color: TONE.amber }}>⏸ AWAITING APPROVAL</span>
              <span style={{ fontSize: 12.5, color: 'var(--tx-2)' }}>Red has <b>not</b> executed. Review — and edit if needed — before you approve.</span>
              <span style={{ flex: 1 }} />
              <Tag tone="violet">{plan.enforcement_mode || 'enforce'}</Tag>
              {plan.hitl_enabled && <Tag tone="green">HITL</Tag>}
            </div>

            <Field label="Objective">
              <input value={objective} onChange={(e) => setObjective(e.target.value)} style={inp} />
            </Field>
            <Field label="Instruction — the directive red actually runs">
              <textarea value={instruction} onChange={(e) => setInstruction(e.target.value)} rows={3} style={{ ...inp, resize: 'vertical', fontFamily: 'var(--mono)', fontSize: 12.5 }} />
            </Field>
            <Field label="In-scope target(s) — comma-separated hard boundary">
              <input value={inScope} onChange={(e) => setInScope(e.target.value)} style={{ ...inp, fontFamily: 'var(--mono)' }} />
            </Field>

            {msg && <div style={{ fontSize: 12, color: 'var(--tx-2)' }}>{msg}</div>}
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <button onClick={reject} disabled={busyAny} style={btn(TONE.red)}>{busy === 'reject' ? '…' : 'Reject'}</button>
              <button onClick={save} disabled={busyAny} style={btn('var(--tx-2)')}>{busy === 'save' ? 'Saving…' : 'Save edits'}</button>
              <span style={{ flex: 1 }} />
              <button onClick={approve} disabled={busyAny} style={btn(TONE.green, true)}>{busy === 'approve' ? 'Running red…' : 'Approve & run red'}</button>
            </div>
          </div>}
    </Panel>
  )
}

const inp: CSSProperties = { width: '100%', background: 'var(--bg-2)', border: '1px solid var(--line)', color: 'var(--tx)', borderRadius: 8, padding: '8px 10px', fontSize: 13 }
const btn = (color: string, solid = false): CSSProperties => ({
  background: solid ? color : `${color}18`, color: solid ? '#04140b' : color,
  border: `1px solid ${color}55`, borderRadius: 8, padding: '8px 14px', fontSize: 12.5, fontWeight: 650, cursor: 'pointer',
})
function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label style={{ display: 'grid', gap: 5 }}>
      <span style={{ fontSize: 11, color: 'var(--tx-faint)', textTransform: 'uppercase', letterSpacing: '.05em' }}>{label}</span>
      {children}
    </label>
  )
}

/* ---------------- engagement workspace: header + SSE live timeline (§15/§16) ---------------- */

interface TEvent { seq?: number; ts?: number | string; actor?: string; record_type?: string; ref?: Record<string, unknown>; this_hash?: string }
type StreamState = 'connecting' | 'streaming' | 'ended' | 'error'

const SRC: Record<string, { label: string; tone: keyof typeof TONE }> = {
  red: { label: 'RED', tone: 'red' }, blue: { label: 'BLUE', tone: 'blue' },
  sensor: { label: 'SENSOR', tone: 'blue' }, coordinator: { label: 'COORD', tone: 'green' },
  policy: { label: 'GATE', tone: 'amber' }, governance: { label: 'GATE', tone: 'amber' },
}
const srcOf = (actor?: string) => SRC[(actor || '').toLowerCase()] || { label: (actor || 'SYS').toUpperCase().slice(0, 6), tone: 'violet' as const }
const friendly = (t?: string) => (t ? t.split(/[._]/).map((w, i) => (i === 0 ? w.charAt(0).toUpperCase() + w.slice(1) : w)).join(' ') : 'event')
const fmtTs = (t?: number | string) => {
  if (t == null) return ''
  if (typeof t === 'number') { try { return new Date(t * (t < 1e12 ? 1000 : 1)).toTimeString().slice(0, 8) } catch { return '' } }
  const s = String(t); return s.length >= 19 ? s.slice(11, 19) : s
}
const refSummary = (ref?: Record<string, unknown>) => {
  if (!ref || typeof ref !== 'object') return ''
  const pick = ['technique', 'technique_id', 'entity', 'dst_ip', 'finding_id', 'action', 'decision', 'target']
  const bits = pick.map((k) => (ref[k] != null ? `${k}=${String(ref[k])}` : '')).filter(Boolean)
  return bits.slice(0, 3).join(' · ')
}

function EngagementWorkspace({ id, row, go, onClose }: { id: string; row?: EngagementRow; go: ScreenProps['go']; onClose: () => void }) {
  const [events, setEvents] = useState<TEvent[]>([])
  const [state, setState] = useState<StreamState>('connecting')
  const scrollRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    const ac = new AbortController()
    setEvents([]); setState('connecting')
    ;(async () => {
      try {
        const res = await streamFetch(`/coordinator/engagements/${id}/events`, { headers: { Accept: 'text/event-stream' }, signal: ac.signal })
        if (!res.ok || !res.body) { setState('error'); return }
        setState('streaming')
        const reader = res.body.getReader()
        const dec = new TextDecoder()
        let buf = ''
        for (;;) {
          const { done, value } = await reader.read()
          if (done) break
          buf += dec.decode(value, { stream: true })
          let idx: number
          // SSE frames are separated by a blank line; each carries `event:` + `data:` lines.
          while ((idx = buf.indexOf('\n\n')) >= 0) {
            const frame = buf.slice(0, idx); buf = buf.slice(idx + 2)
            let evType = '', dataStr = ''
            for (const line of frame.split('\n')) {
              if (line.startsWith('event:')) evType = line.slice(6).trim()
              else if (line.startsWith('data:')) dataStr += line.slice(5).trim()
            }
            if (evType === 'end') { setState('ended'); continue }
            let rec: TEvent = {}
            try { rec = JSON.parse(dataStr) as TEvent } catch { /* non-JSON frame — skip */ }
            if (rec && (rec.record_type || rec.actor || rec.seq != null)) {
              if (!rec.record_type && evType) rec.record_type = evType
              setEvents((prev) => [...prev, rec])
            }
          }
        }
        setState((s) => (s === 'error' ? s : 'ended'))
      } catch { setState((s) => (s === 'error' ? s : 'ended')) } // aborted on unmount, or stream ended
    })()
    return () => ac.abort()
  }, [id])

  // keep the newest event in view as the stream fills
  useEffect(() => { const el = scrollRef.current; if (el) el.scrollTop = el.scrollHeight }, [events])

  const dot = state === 'streaming' ? TONE.green : state === 'error' ? TONE.red : 'var(--tx-faint)'

  return (
    <Panel
      title={<>Engagement · <span style={{ fontFamily: 'var(--mono)', color: 'var(--tx)' }}>{id}</span></>}
      right={<div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <StatusPill status={row?.status} />
        {row?.detection_rate != null && <Tag tone="green">detection {Math.round(row.detection_rate * 100)}%</Tag>}
        <button className="btn ghost" onClick={onClose} style={{ fontSize: 12 }}>Close</button>
      </div>}
    >
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 10, flexWrap: 'wrap' }}>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 11.5, color: 'var(--tx-2)' }}>
          <span style={{ width: 8, height: 8, borderRadius: 99, background: dot }} />
          Live timeline · {state === 'connecting' ? 'connecting…' : state === 'streaming' ? 'streaming' : state === 'ended' ? `replay complete (${events.length})` : 'stream error'}
        </span>
        <span style={{ flex: 1 }} />
        <button className="btn ghost" style={{ fontSize: 12 }} onClick={() => go('attackpaths')}>Attack path</button>
        <button className="btn ghost" style={{ fontSize: 12 }} onClick={() => go('mitre')}>ATT&amp;CK</button>
        <button className="btn ghost" style={{ fontSize: 12 }} onClick={() => go('evidence')}>Evidence</button>
      </div>

      <div ref={scrollRef} style={{ maxHeight: 360, overflowY: 'auto', border: '1px solid var(--line)', borderRadius: 10, background: 'var(--bg-2)' }}>
        {events.length === 0
          ? <div style={{ padding: 18, color: 'var(--tx-faint)', fontSize: 12.5 }}>{state === 'error' ? 'Stream unavailable — is the coordinator reachable at /api/coordinator?' : 'Waiting for engagement events…'}</div>
          : events.map((e, i) => {
              const s = srcOf(e.actor)
              const ref = refSummary(e.ref)
              return (
                <div key={e.seq ?? i} style={{ display: 'grid', gridTemplateColumns: '68px 62px 1fr auto', gap: 10, alignItems: 'center', padding: '7px 10px', borderBottom: '1px solid var(--line-soft)', fontSize: 12.5 }}>
                  <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--tx-faint)' }}>{fmtTs(e.ts)}</span>
                  <span style={{ fontFamily: 'var(--mono)', fontSize: 10, fontWeight: 700, textAlign: 'center', padding: '3px 0', borderRadius: 5, color: TONE[s.tone], background: `${TONE[s.tone]}1e` }}>{s.label}</span>
                  <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {friendly(e.record_type)}{ref ? <span style={{ color: 'var(--tx-3)', fontFamily: 'var(--mono)', fontSize: 11 }}> · {ref}</span> : null}
                  </span>
                  <span style={{ fontFamily: 'var(--mono)', fontSize: 10.5, color: 'var(--tx-faint)' }}>{e.this_hash ? `${e.this_hash.slice(0, 8)}` : ''}{e.seq != null ? ` · #${e.seq}` : ''}</span>
                </div>
              )
            })}
      </div>
    </Panel>
  )
}
