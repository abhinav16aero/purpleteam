// RedBlue Attack Paths (prompt §13) — ADDITIVE overlay.
// The purple-team kill chain for an engagement, derived from the REAL coordinator KG
// (/api/coordinator/engagements/:id/graph): host → finding → technique, each step flagged
// DETECTED / MISSED from the technique's detected state. This is where a red step that nothing
// caught becomes visually obvious. No fabricated steps — an empty graph shows an empty state.
import { useCallback, useEffect, useMemo, useState } from 'react'
import { EmptyState } from '../../shared/ui'
import { coordinatorApi, type Graph, type GraphNode } from '../../../services/coordinatorApi'
import type { ScreenProps } from '../../shared/types'
import { Panel, Kpi, TONE, useEngagements, EngPicker } from '../redblue/kit'
import { techniqueName } from '../../data/mitre'

interface Step { finding: GraphNode; host?: string; techniques: string[]; detected: boolean }

export default function AttackPathScreen(props: ScreenProps) {
  const { list, sel, setSel } = useEngagements()
  const [graph, setGraph] = useState<Graph | null>(null)
  const [phase, setPhase] = useState<'idle' | 'loading' | 'error'>('idle')

  const load = useCallback(async (id: string) => {
    if (!id) return
    setPhase('loading')
    try { const { data } = await coordinatorApi.getEngagementGraph(id); setGraph(data); setPhase('idle') }
    catch { setPhase('error') }
  }, [])
  useEffect(() => { load(sel) }, [sel, load])

  const steps = useMemo<Step[]>(() => {
    if (!graph) return []
    const byId = new Map(graph.nodes.map((n) => [n.id, n]))
    const findings = graph.nodes.filter((n) => n.kind === 'finding')
    return findings.map((f) => {
      const techIds = graph.edges.filter((e) => e.source === f.id && e.rel === 'USES')
        .map((e) => byId.get(e.target)).filter(Boolean).map((n) => (n as GraphNode).label)
      const hostEdge = graph.edges.find((e) => e.target === f.id && (e.rel === 'REACHES' || e.rel === 'HAS_PORT'))
      const host = hostEdge ? byId.get(hostEdge.source)?.label : undefined
      const detected = f.detected === true || graph.edges.some((e) => e.source === f.id && e.rel === 'USES' && byId.get(e.target)?.detected === true)
      return { finding: f, host, techniques: techIds, detected }
    })
  }, [graph])

  const detectedN = steps.filter((s) => s.detected).length
  const missedN = steps.length - detectedN

  return (
    <div style={{ display: 'grid', gap: 16, padding: 16 }}>
      <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
        <EngPicker list={list} sel={sel} setSel={setSel} />
        <span style={{ flex: 1 }} />
        <button onClick={() => props.go('knowledgegraph')} style={{ background: 'var(--bg-2)', color: 'var(--tx)', border: '1px solid var(--line)', borderRadius: 8, padding: '6px 12px', fontSize: 12.5, cursor: 'pointer' }}>Open in Knowledge Graph</button>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 12 }}>
        <Kpi label="Steps" value={String(steps.length)} tone="violet" />
        <Kpi label="Detected" value={String(detectedN)} tone="green" />
        <Kpi label="Missed (gaps)" value={String(missedN)} tone="red" />
      </div>

      <Panel title="Kill chain">
        {phase === 'error' ? <EmptyState compact icon="alert" error title="Graph unavailable" body="Is the coordinator reachable and the KG seeded (REDBLUE_DECEPTICON_NEO4J_PASSWORD)?" />
          : phase === 'loading' && !graph ? <EmptyState compact icon="clock" loading title="Building path…" />
          : steps.length === 0 ? <EmptyState compact icon="link" title="No attack path in scope" body="This engagement has no findings in the graph yet — run it or seed the KG." />
          : <div style={{ position: 'relative', paddingLeft: 8 }}>
              <div style={{ position: 'absolute', left: 24, top: 8, bottom: 8, width: 2, background: 'var(--line)' }} />
              {steps.map((s, i) => {
                const c = s.detected ? TONE.green : TONE.red
                return (
                  <div key={s.finding.id} style={{ display: 'grid', gridTemplateColumns: '34px 1fr', gap: 14, marginBottom: i === steps.length - 1 ? 0 : 6 }}>
                    <div style={{ width: 34, height: 34, borderRadius: 999, border: `2px solid ${c}`, color: c, background: 'var(--panel)', display: 'grid', placeItems: 'center', zIndex: 1, fontSize: 14, fontWeight: 700 }}>{s.detected ? '✓' : '✗'}</div>
                    <div style={{ border: '1px solid var(--line)', borderRadius: 10, padding: '10px 12px', background: 'var(--bg-2)', marginBottom: 8 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                        <b style={{ fontSize: 13 }}>{s.finding.label}</b>
                        {s.techniques.map((t) => <span key={t} style={{ fontSize: 10, fontFamily: 'var(--mono)', color: TONE.amber, border: `1px solid ${TONE.amber}44`, borderRadius: 6, padding: '2px 7px' }} title={techniqueName(t)}>{t}</span>)}
                        <span style={{ flex: 1 }} />
                        <span style={{ fontSize: 10.5, fontFamily: 'var(--mono)', color: c }}>{s.detected ? 'DETECTED' : 'MISSED'}</span>
                      </div>
                      <div style={{ fontSize: 12, color: 'var(--tx-3)', marginTop: 4 }}>
                        {s.host ? `on ${s.host}` : ''}{s.techniques.length ? ` · ${s.techniques.map(techniqueName).join(', ')}` : ''}{s.finding.tool ? ` · ${s.finding.tool}` : ''}
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>}
      </Panel>
    </div>
  )
}
