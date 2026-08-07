// RedBlue Posture dashboard (plan 09 §1.4) — ADDITIVE overlay.
// Attacked-vs-detected, MTTD, ATT&CK coverage, and the false-negative watchlist — all from
// coordinatorApi (which proxies to the coordinator's /api/posture). Charts reuse the existing
// redesign/shared primitives (no new dependency). Structure mirrors AutoOpsScreen.
import { useEffect, useState } from 'react'
import { Donut, GroupedBars, Trend } from '../../shared/charts'
import { DataTable } from '../../shared/DataTable'
import { EmptyState } from '../../shared/ui'
import { coordinatorApi, Posture } from '../../../services/coordinatorApi'
import type { ScreenProps } from '../../data/data'

type Phase = 'loading' | 'ready' | 'error'

export default function PostureScreen(_props: ScreenProps) {
  const [posture, setPosture] = useState<Posture | null>(null)
  const [phase, setPhase] = useState<Phase>('loading')

  useEffect(() => {
    let live = true
    const load = async () => {
      try {
        const { data } = await coordinatorApi.getPosture()
        if (live) { setPosture(data); setPhase('ready') }
      } catch { if (live) setPhase('error') }
    }
    load()
    const t = setInterval(load, 10_000)   // 10s polling — matches AutoOpsScreen/SocConsole
    return () => { live = false; clearInterval(t) }
  }, [])

  if (phase === 'loading') return <EmptyState title="Loading posture…" />
  if (phase === 'error' || !posture)
    return <EmptyState title="Coordinator unavailable" subtitle="Is the RedBlue coordinator running on :8900?" />

  const rate = posture.detection_rate == null ? 0 : Math.round(posture.detection_rate * 100)
  const { attacked, detected } = posture.totals

  return (
    <div className="rb-posture" style={{ display: 'grid', gap: 16, padding: 16 }}>
      {/* KPI row */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 }}>
        <Kpi label="Detection rate" value={`${rate}%`} />
        <Kpi label="Attacked / Detected" value={`${attacked} / ${detected}`} />
        <Kpi label="MTTD (mean)" value={fmt(posture.mttd.mean)} />
        <Kpi label="Coverage gaps" value={String(posture.gap_count)} />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <Panel title="Attacked vs Detected">
          <Donut value={rate} label={`${rate}% detected`} />
        </Panel>
        <Panel title="ATT&CK coverage">
          <GroupedBars data={[
            { label: 'Attacked', value: posture.attack_coverage.attacked },
            { label: 'Detected', value: posture.attack_coverage.detected },
          ]} />
        </Panel>
      </div>

      <Panel title="MTTD trend">
        <Trend points={[posture.mttd.median ?? 0, posture.mttd.mean ?? 0, posture.mttd.p90 ?? 0]} />
      </Panel>

      <Panel title="False-negative watchlist (attacked, never detected)">
        {posture.top_gaps.length === 0
          ? <EmptyState title="No gaps — every attacked technique was detected." />
          : <DataTable
              columns={[{ key: 'technique_id', label: 'Technique' }, { key: 'entity', label: 'Target' }]}
              rows={posture.top_gaps} />}
      </Panel>
    </div>
  )
}

const fmt = (s: number | null) => (s == null ? '—' : s < 60 ? `${Math.round(s)}s` : `${Math.round(s / 60)}m`)

function Kpi({ label, value }: { label: string; value: string }) {
  return (
    <div className="rb-kpi" style={{ padding: 14, borderRadius: 10, background: 'var(--panel, #1a1d24)' }}>
      <div style={{ fontSize: 12, opacity: 0.7 }}>{label}</div>
      <div style={{ fontSize: 26, fontWeight: 700 }}>{value}</div>
    </div>
  )
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ padding: 14, borderRadius: 10, background: 'var(--panel, #1a1d24)' }}>
      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 10, opacity: 0.85 }}>{title}</div>
      {children}
    </div>
  )
}
