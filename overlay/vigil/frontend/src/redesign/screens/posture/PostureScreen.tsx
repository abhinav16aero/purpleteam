// RedBlue Posture dashboard (plan 09 §1.4) — ADDITIVE overlay.
// Attacked-vs-detected, MTTD, ATT&CK coverage, and the false-negative watchlist — all from
// coordinatorApi (which proxies to the coordinator's /api/posture). Charts + table reuse the
// existing redesign/shared primitives (no new dependency); wired into the nav by patch 0007.
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { Donut, GroupedBars, type DonutSeg, type GroupRow } from '../../shared/charts'
import { DataTable, useTableSort, type ColumnDef } from '../../shared/DataTable'
import { EmptyState } from '../../shared/ui'
import { coordinatorApi, type Posture } from '../../../services/coordinatorApi'
import type { ScreenProps } from '../../shared/types'

type Gap = { technique_id: string; entity: string | null }

export default function PostureScreen(_props: ScreenProps) {
  const [posture, setPosture] = useState<Posture | null>(null)
  const [phase, setPhase] = useState<'loading' | 'ready' | 'error'>('loading')

  useEffect(() => {
    let live = true
    const load = async () => {
      try {
        const { data } = await coordinatorApi.getPosture()
        if (live) { setPosture(data); setPhase('ready') }
      } catch { if (live) setPhase('error') }
    }
    load()
    const t = setInterval(load, 10_000) // 10s polling — matches AutoOps/SocConsole
    return () => { live = false; clearInterval(t) }
  }, [])

  // Column defs are stable, so build them once regardless of the fetch state.
  const gapColumns = useMemo<ColumnDef<Gap>[]>(() => [
    { key: 'technique_id', label: 'Technique', render: (g) => g.technique_id,
      sortVal: (g) => g.technique_id, searchVal: (g) => g.technique_id },
    { key: 'entity', label: 'Target', render: (g) => g.entity ?? '—',
      sortVal: (g) => g.entity ?? '', searchVal: (g) => g.entity ?? '' },
  ], [])
  const { sort, toggle } = useTableSort(gapColumns, { key: 'technique_id', dir: 'asc' })

  if (phase === 'loading') return <EmptyState icon="clock" loading title="Loading posture…" />
  if (phase === 'error' || !posture)
    return (
      <EmptyState
        icon="alert"
        error
        title="Coordinator unavailable"
        body="Is the RedBlue coordinator reachable at /api/coordinator (proxy to :8900)?"
      />
    )

  const frac = posture.detection_rate ?? 0
  const rate = Math.round(frac * 100)
  const { attacked, detected } = posture.totals
  const donutSegs: DonutSeg[] = [
    { v: frac, color: 'var(--ok)', label: 'Detected' },
    { v: 1 - frac, color: 'var(--crit)', label: 'Missed' },
  ]
  const coverage: GroupRow[] = [
    { label: 'ATT&CK techniques', a: posture.attack_coverage.attacked, b: posture.attack_coverage.detected },
  ]

  return (
    <div className="rb-posture" style={{ display: 'grid', gap: 16, padding: 16 }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 }}>
        <Kpi label="Detection rate" value={`${rate}%`} />
        <Kpi label="Attacked / Detected" value={`${attacked} / ${detected}`} />
        <Kpi label="MTTD (mean)" value={fmtSecs(posture.mttd.mean)} />
        <Kpi label="Coverage gaps" value={String(posture.gap_count)} />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <Panel title="Attacked vs Detected">
          <Donut segs={donutSegs} />
        </Panel>
        <Panel title="ATT&CK coverage (attacked vs detected)">
          <GroupedBars rows={coverage} />
        </Panel>
      </div>

      <Panel title="False-negative watchlist (attacked, never detected)">
        {posture.top_gaps.length === 0
          ? <EmptyState compact icon="shield" title="No gaps — every attacked technique was detected." />
          : <DataTable
              columns={gapColumns}
              rows={posture.top_gaps}
              rowKey={(g) => `${g.technique_id}:${g.entity ?? ''}`}
              phase="ready"
              sort={sort}
              onSort={toggle}
            />}
      </Panel>
    </div>
  )
}

const fmtSecs = (s: number | null) => (s == null ? '—' : s < 60 ? `${Math.round(s)}s` : `${Math.round(s / 60)}m`)

function Kpi({ label, value }: { label: string; value: string }) {
  return (
    <div className="rb-kpi" style={{ padding: 14, borderRadius: 10, background: 'var(--bg-2)' }}>
      <div style={{ fontSize: 12, opacity: 0.7 }}>{label}</div>
      <div style={{ fontSize: 26, fontWeight: 700 }}>{value}</div>
    </div>
  )
}

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div style={{ padding: 14, borderRadius: 10, background: 'var(--bg-2)' }}>
      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 10, opacity: 0.85 }}>{title}</div>
      {children}
    </div>
  )
}
