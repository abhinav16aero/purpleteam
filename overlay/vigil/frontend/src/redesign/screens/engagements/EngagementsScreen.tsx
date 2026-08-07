// RedBlue Engagements — launch + monitor (plan 09 §1.3) — ADDITIVE overlay.
// Control bar (launch + kill switch), the engagement queue, and a detail with the SSE live
// timeline. Reuses the redesign DataTable + streamFetch primitives; wired in by patch 0007.
// The kill switch is the always-visible 00 §10 non-negotiable.
import { useEffect, useMemo, useState } from 'react'
import { DataTable, useTableSort, type ColumnDef } from '../../shared/DataTable'
import { EmptyState } from '../../shared/ui'
import { coordinatorApi } from '../../../services/coordinatorApi'
import { streamFetch } from '../../../services/api'
import type { ScreenProps } from '../../shared/types'

interface EngagementRow {
  engagement_id: string
  tenant_id?: string
  mode?: string
  status?: string
  detection_rate?: number | null
}

export default function EngagementsScreen(_props: ScreenProps) {
  const [rows, setRows] = useState<EngagementRow[]>([])
  const [phase, setPhase] = useState<'loading' | 'ready' | 'error'>('loading')
  const [tenant, setTenant] = useState('t01')
  const [mode, setMode] = useState<'on_demand' | 'continuous'>('on_demand')
  const [selected, setSelected] = useState<string | null>(null)

  const reload = async () => {
    try {
      const { data } = await coordinatorApi.listEngagements()
      setRows(Array.isArray(data) ? data : (data?.engagements ?? []))
      setPhase('ready')
    } catch { setPhase('error') }
  }
  useEffect(() => { reload(); const t = setInterval(reload, 10_000); return () => clearInterval(t) }, [])

  const launch = async () => {
    try { await coordinatorApi.launch({ tenant_id: tenant, mode, scope: {} }); reload() }
    catch { /* the failure surfaces via `phase` on the next reload */ }
  }
  const kill = async () => {
    if (window.confirm('KILL SWITCH — halt ALL engagements globally?'))
      await coordinatorApi.kill('operator', 'manual global kill (console)')
  }

  const columns = useMemo<ColumnDef<EngagementRow>[]>(() => [
    { key: 'engagement_id', label: 'Engagement', render: (r) => r.engagement_id,
      sortVal: (r) => r.engagement_id, searchVal: (r) => r.engagement_id },
    { key: 'tenant_id', label: 'Tenant', render: (r) => r.tenant_id ?? '—',
      sortVal: (r) => r.tenant_id ?? '' },
    { key: 'mode', label: 'Mode', render: (r) => r.mode ?? 'on_demand' },
    { key: 'status', label: 'Status', render: (r) => r.status ?? '—', sortVal: (r) => r.status ?? '' },
    { key: 'detection_rate', label: 'Detection', defaultDir: 'desc',
      render: (r) => (r.detection_rate == null ? '—' : `${Math.round(r.detection_rate * 100)}%`),
      sortVal: (r) => r.detection_rate ?? -1 },
  ], [])
  const { sort, toggle } = useTableSort(columns, { key: 'engagement_id', dir: 'asc' })

  return (
    <div style={{ display: 'grid', gap: 16, padding: 16 }}>
      <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
        <input
          value={tenant}
          onChange={(e) => setTenant(e.target.value)}
          placeholder="tenant"
          style={{ padding: 6, borderRadius: 6 }}
        />
        <select
          value={mode}
          onChange={(e) => setMode(e.target.value as 'on_demand' | 'continuous')}
          style={{ padding: 6 }}
        >
          <option value="on_demand">on-demand</option>
          <option value="continuous">continuous (CART)</option>
        </select>
        <button className="btn primary" onClick={launch}>Launch engagement</button>
        <div style={{ flex: 1 }} />
        <button
          className="btn"
          onClick={kill}
          style={{ background: 'var(--crit)', color: '#fff', fontWeight: 700 }}
        >
          ■ KILL SWITCH
        </button>
      </div>

      {phase !== 'error' && rows.length === 0
        ? <EmptyState icon="bolt" title="No engagements yet"
            body="Launch a scoped red engagement with the controls above." />
        : <DataTable
            columns={columns}
            rows={rows}
            rowKey={(r) => r.engagement_id}
            phase={phase}
            error={phase === 'error' ? 'Coordinator unavailable' : null}
            sort={sort}
            onSort={toggle}
            onRowClick={(r) => setSelected(r.engagement_id)}
          />}

      {selected && <EngagementTimeline id={selected} onClose={() => setSelected(null)} />}
    </div>
  )
}

// Live timeline via the ONE SSE endpoint (plan 09 §1.6), read with the shared streamFetch helper
// exactly as Chat.tsx does (reader loop + TextDecoder, parsing `data:` frames).
function EngagementTimeline({ id, onClose }: { id: string; onClose: () => void }) {
  const [lines, setLines] = useState<string[]>([])

  useEffect(() => {
    const ac = new AbortController()
    setLines([])
    ;(async () => {
      try {
        const res = await streamFetch(`/coordinator/engagements/${id}/events`, {
          headers: { Accept: 'text/event-stream' },
          signal: ac.signal,
        })
        if (!res.ok || !res.body) return
        const reader = res.body.getReader()
        const decoder = new TextDecoder()
        let buf = ''
        for (;;) {
          const { done, value } = await reader.read()
          if (done) break
          buf += decoder.decode(value, { stream: true })
          const parts = buf.split('\n')
          buf = parts.pop() ?? ''
          for (const raw of parts) {
            const line = raw.trim()
            if (line.startsWith('data:')) setLines((prev) => [...prev, line.slice(5).trim()])
          }
        }
      } catch { /* stream aborted (unmount) or ended */ }
    })()
    return () => ac.abort()
  }, [id])

  return (
    <div style={{ padding: 14, borderRadius: 10, background: 'var(--bg-2)' }}>
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 8 }}>
        <div style={{ fontWeight: 600 }}>Timeline — {id}</div>
        <div style={{ flex: 1 }} />
        <button className="btn ghost" onClick={onClose}>Close</button>
      </div>
      <pre style={{ maxHeight: 280, overflow: 'auto', fontSize: 12, margin: 0 }}>
        {lines.length ? lines.join('\n') : 'Waiting for engagement events…'}
      </pre>
    </div>
  )
}
