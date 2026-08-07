// RedBlue Engagements — launch + monitor (plan 09 §1.3) — ADDITIVE overlay.
// Control bar (launch + kill switch), engagement queue, and a detail with the SSE live timeline.
// Structure mirrors AutoOpsScreen. The kill switch is the always-visible 00 §10 non-negotiable.
import { useEffect, useState } from 'react'
import { DataTable } from '../../shared/DataTable'
import { EmptyState } from '../../shared/ui'
import { coordinatorApi } from '../../../services/coordinatorApi'
import { streamFetch } from '../../../services/api'
import type { ScreenProps } from '../../data/data'

export default function EngagementsScreen(_props: ScreenProps) {
  const [rows, setRows] = useState<any[]>([])
  const [tenant, setTenant] = useState('t01')
  const [mode, setMode] = useState<'on_demand' | 'continuous'>('on_demand')
  const [selected, setSelected] = useState<string | null>(null)

  const reload = async () => {
    try { setRows((await coordinatorApi.listEngagements()).data ?? []) } catch { /* coordinator down */ }
  }
  useEffect(() => { reload(); const t = setInterval(reload, 10_000); return () => clearInterval(t) }, [])

  const launch = async () => {
    await coordinatorApi.launch({ tenant_id: tenant, mode, scope: {} })
    reload()
  }
  const kill = async () => {
    if (confirm('KILL SWITCH: halt ALL engagements globally?'))
      await coordinatorApi.kill('operator', 'manual global kill')
  }

  return (
    <div style={{ display: 'grid', gap: 16, padding: 16 }}>
      <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
        <input value={tenant} onChange={e => setTenant(e.target.value)} placeholder="tenant"
               style={{ padding: 6, borderRadius: 6 }} />
        <select value={mode} onChange={e => setMode(e.target.value as any)} style={{ padding: 6 }}>
          <option value="on_demand">on-demand</option>
          <option value="continuous">continuous (CART)</option>
        </select>
        <button onClick={launch} style={{ padding: '6px 14px', fontWeight: 600 }}>Launch engagement</button>
        <div style={{ flex: 1 }} />
        <button onClick={kill} style={{ padding: '6px 14px', background: '#c0392b', color: '#fff',
                fontWeight: 700, borderRadius: 6 }}>■ KILL SWITCH</button>
      </div>

      {rows.length === 0
        ? <EmptyState title="No engagements yet" subtitle="Launch a scoped red engagement above." />
        : <DataTable
            columns={[
              { key: 'engagement_id', label: 'Engagement' }, { key: 'tenant_id', label: 'Tenant' },
              { key: 'mode', label: 'Mode' }, { key: 'status', label: 'Status' },
            ]}
            rows={rows}
            onRowClick={(r: any) => setSelected(r.engagement_id)} />}

      {selected && <EngagementDetail id={selected} />}
    </div>
  )
}

// Live timeline via the ONE SSE endpoint (plan 09 §1.6), consumed with the existing streamFetch helper.
function EngagementDetail({ id }: { id: string }) {
  const [events, setEvents] = useState<string[]>([])
  useEffect(() => {
    let stop = false
    ;(async () => {
      try {
        await streamFetch(coordinatorApi.eventsUrl(id), {}, (evt: string) => {
          if (!stop) setEvents(e => [...e, evt])
        })
      } catch { /* stream ended */ }
    })()
    return () => { stop = true }
  }, [id])
  return (
    <div style={{ padding: 14, borderRadius: 10, background: 'var(--panel, #1a1d24)' }}>
      <div style={{ fontWeight: 600, marginBottom: 8 }}>Timeline — {id}</div>
      <pre style={{ maxHeight: 280, overflow: 'auto', fontSize: 12 }}>{events.join('\n')}</pre>
    </div>
  )
}
