// RedBlue MITRE ATT&CK coverage (prompt §21) — ADDITIVE overlay.
// Per-technique detection coverage, grouped into tactics via the console's MITRE taxonomy
// (data/mitre.ts). Two LIVE modes: "All engagements" rolls up every scorecard (/api/coordinator/mitre),
// "This engagement" uses one scorecard's per_technique. Cell color = detection rate. No invented cells —
// only techniques actually exercised appear.
import { useCallback, useEffect, useMemo, useState } from 'react'
import { EmptyState } from '../../shared/ui'
import { coordinatorApi, type Scorecard, type MitreTechnique } from '../../../services/coordinatorApi'
import type { ScreenProps } from '../../shared/types'
import { Panel, Kpi, TONE, useEngagements, EngPicker } from '../redblue/kit'
import { techniqueName, techniqueTactic } from '../../data/mitre'

// both sources expose these fields; the rollup adds `engagements`, `detected`/`attacked` are counts.
type Cell = { technique_id: string; attacked: number; detected: number; detection_rate: number | null }

function toneFor(rate: number | null): keyof typeof TONE | 'gray' {
  if (rate == null) return 'gray'
  return rate >= 0.7 ? 'green' : rate >= 0.35 ? 'amber' : 'red'
}
const cellColor: Record<string, string> = { green: TONE.green, amber: TONE.amber, red: TONE.red, gray: 'var(--tx-faint)' }

export default function MitreScreen(props: ScreenProps) {
  const [mode, setMode] = useState<'all' | 'engagement'>('all')
  const { list, sel, setSel } = useEngagements()
  const [rollup, setRollup] = useState<MitreTechnique[] | null>(null)
  const [rollMeta, setRollMeta] = useState<{ scorecards: number; detection_rate: number | null } | null>(null)
  const [sc, setSc] = useState<Scorecard | null>(null)
  const [phase, setPhase] = useState<'idle' | 'loading' | 'error'>('loading')

  const loadRollup = useCallback(async () => {
    setPhase('loading')
    try { const { data } = await coordinatorApi.getMitreRollup(); setRollup(data.techniques); setRollMeta({ scorecards: data.scorecards, detection_rate: data.detection_rate }); setPhase('idle') }
    catch { setPhase('error') }
  }, [])
  const loadScorecard = useCallback(async (id: string) => {
    if (!id) { setSc(null); return }
    setPhase('loading')
    try { const { data } = await coordinatorApi.getScorecard(id); setSc(data as Scorecard); setPhase('idle') }
    catch { setPhase('error') }
  }, [])

  useEffect(() => { if (mode === 'all') loadRollup() }, [mode, loadRollup])
  useEffect(() => { if (mode === 'engagement') loadScorecard(sel) }, [mode, sel, loadScorecard])

  const cells: Cell[] = mode === 'all' ? (rollup ?? []) : (sc?.per_technique ?? [])
  const summary = mode === 'all'
    ? {
        rate: rollMeta?.detection_rate ?? null,
        attacked: (rollup ?? []).length,
        detected: (rollup ?? []).filter((t) => t.detected > 0).length,
        gaps: (rollup ?? []).filter((t) => t.attacked > 0 && t.detected === 0).length,
        scope: rollMeta ? `${rollMeta.scorecards} engagement${rollMeta.scorecards === 1 ? '' : 's'}` : '',
      }
    : {
        rate: sc?.detection_rate ?? null,
        attacked: sc?.attacked_techniques.length ?? 0,
        detected: sc?.detected_techniques.length ?? 0,
        gaps: sc?.gaps.length ?? 0,
        scope: sel,
      }

  const tactics = useMemo(() => {
    const by = new Map<string, Cell[]>()
    for (const r of cells) {
      const tac = techniqueTactic(r.technique_id) || 'Other'
      if (!by.has(tac)) by.set(tac, [])
      by.get(tac)!.push(r)
    }
    return [...by.entries()].sort((a, b) => a[0].localeCompare(b[0]))
  }, [cells])

  return (
    <div style={{ display: 'grid', gap: 16, padding: 16 }}>
      <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', background: 'var(--bg-2)', border: '1px solid var(--line)', borderRadius: 8, padding: 2 }}>
          {(['all', 'engagement'] as const).map((m) => (
            <button key={m} onClick={() => setMode(m)}
              style={{ border: 'none', background: mode === m ? 'var(--accent)' : 'transparent', color: mode === m ? '#fff' : 'var(--tx-2)', borderRadius: 6, padding: '5px 11px', fontSize: 12, cursor: 'pointer', fontWeight: 600 }}>
              {m === 'all' ? 'All engagements' : 'This engagement'}
            </button>
          ))}
        </div>
        {mode === 'engagement' && <EngPicker list={list} sel={sel} setSel={setSel} />}
        {summary.scope && <span style={{ fontSize: 11.5, color: 'var(--tx-faint)', fontFamily: 'var(--mono)' }}>{summary.scope}</span>}
        <span style={{ flex: 1 }} />
        {(['green', 'amber', 'red', 'gray'] as const).map((k) => (
          <span key={k} style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 11, color: 'var(--tx-3)' }}>
            <span style={{ width: 10, height: 10, borderRadius: 3, background: cellColor[k] }} />
            {k === 'green' ? 'strong' : k === 'amber' ? 'partial' : k === 'red' ? 'weak/missed' : 'untested'}
          </span>
        ))}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 12 }}>
        <Kpi label="Detection rate" value={summary.rate != null ? `${Math.round(summary.rate * 100)}%` : '—'} tone="green" />
        <Kpi label="Techniques attacked" value={String(summary.attacked)} tone="red" />
        <Kpi label="Techniques detected" value={String(summary.detected)} tone="blue" />
        <Kpi label="Gaps" value={String(summary.gaps)} tone="amber" />
      </div>

      <Panel title={mode === 'all' ? 'ATT&CK coverage · all engagements' : 'ATT&CK coverage · engagement'}>
        {phase === 'error' ? <EmptyState compact icon="alert" error title="Coverage unavailable" body="Is the coordinator reachable at /api/coordinator/mitre?" />
          : phase === 'loading' && cells.length === 0 ? <EmptyState compact icon="clock" loading title="Loading coverage…" />
          : tactics.length === 0 ? <EmptyState compact icon="grid" title="No techniques exercised" body={mode === 'all' ? 'No scored engagements yet — run one to populate the matrix.' : 'This engagement’s scorecard has no per-technique rows yet.'} />
          : <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 12, alignItems: 'start' }}>
              {tactics.map(([tac, rows]) => (
                <div key={tac} style={{ background: 'var(--bg-2)', border: '1px solid var(--line)', borderRadius: 10, padding: 12 }}>
                  <div style={{ fontSize: 10.5, textTransform: 'uppercase', letterSpacing: '.05em', color: 'var(--tx-faint)', marginBottom: 8 }}>{tac}</div>
                  <div style={{ display: 'grid', gap: 6 }}>
                    {rows.map((r) => {
                      const col = cellColor[toneFor(r.detection_rate)]
                      return (
                        <div key={r.technique_id} onClick={() => props.go('knowledgegraph')} title={`${techniqueName(r.technique_id)} · ${r.detected}/${r.attacked} detected`}
                          style={{ padding: '7px 9px', borderRadius: 8, background: `${col}1e`, border: `1px solid ${col}55`, cursor: 'pointer' }}>
                          <div style={{ fontFamily: 'var(--mono)', fontSize: 11.5 }}>{r.technique_id}</div>
                          <div style={{ fontSize: 10, color: col }}>{r.detection_rate != null ? `${Math.round(r.detection_rate * 100)}%` : 'untested'}</div>
                        </div>
                      )
                    })}
                  </div>
                </div>
              ))}
            </div>}
      </Panel>
    </div>
  )
}
