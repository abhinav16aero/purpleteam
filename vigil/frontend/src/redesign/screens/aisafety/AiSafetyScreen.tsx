// RedBlue AI Safety (prompt §23) — ADDITIVE overlay.
// The red-team-of-the-AI results from the coordinator (/api/coordinator/eval/injection). These are
// EVALUATION RESULTS over an adversarial corpus — explicitly NOT runtime guarantees. Only the report's
// real fields are shown (agent_hijack_rate is the safety-critical one; it MUST be 0). Nothing invented.
import { useEffect, useState, type CSSProperties } from 'react'
import { EmptyState } from '../../shared/ui'
import { coordinatorApi, type InjectionEvalReport } from '../../../services/coordinatorApi'
import type { ScreenProps } from '../../shared/types'
import { Panel, TONE, pctOrDash } from '../redblue/kit'

// (label, value, "lower is better" ⇒ 0 is good, so green when ≈0; else green when ≈1)
function metricTone(v: number | null, lowerIsBetter: boolean): keyof typeof TONE {
  if (v == null) return 'blue'
  if (lowerIsBetter) return v === 0 ? 'green' : v < 0.05 ? 'amber' : 'red'
  return v >= 0.9 ? 'green' : v >= 0.6 ? 'amber' : 'red'
}

export default function AiSafetyScreen(props: ScreenProps) {
  const [rep, setRep] = useState<InjectionEvalReport | null>(null)
  const [phase, setPhase] = useState<'loading' | 'ready' | 'error'>('loading')

  useEffect(() => {
    let live = true
    coordinatorApi.runInjectionEval()
      .then(({ data }) => { if (live) { setRep(data); setPhase('ready') } })
      .catch(() => { if (live) setPhase('error') })
    return () => { live = false }
  }, [])

  if (phase === 'loading') return <EmptyState icon="clock" loading title="Running injection eval…" />
  if (phase === 'error' || !rep) return <EmptyState icon="alert" error title="Eval unavailable" body="Is the coordinator reachable at /api/coordinator/eval/injection?" />

  const metrics: [string, number | null, boolean, string][] = [
    ['Agent Hijack Rate', rep.agent_hijack_rate, true, 'injected input redirecting an agent’s goal — must be 0'],
    ['Injection Catch Rate', rep.injection_catch_rate, false, 'malicious instructions in untrusted text, flagged by the shield'],
    ['False Positive Rate', rep.false_positive_rate, true, 'benign inputs wrongly flagged'],
    ['Canary Leak Rate', rep.canary_leak_rate, true, 'planted secrets that must never appear in output'],
    ['Verification Reject Rate', rep.verification_reject_rate, false, 'unverifiable claims correctly rejected'],
    ['Grounding Compliance', rep.grounding_compliance, false, 'outputs grounded in provided evidence'],
  ]

  return (
    <div style={{ display: 'grid', gap: 16, padding: 16 }}>
      <div style={{ ...card('amber'), display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 10, fontFamily: 'var(--mono)', color: TONE.amber, border: `1px solid ${TONE.amber}55`, borderRadius: 6, padding: '3px 8px' }}>EVALUATION RESULTS</span>
        <span style={{ fontSize: 12.5, color: 'var(--tx-2)' }}>
          measured over <b>{rep.total}</b> adversarial cases ({rep.injections} injections, {rep.benign} benign) —
          this is a corpus result, <b>not</b> a runtime guarantee.
        </span>
        <span style={{ flex: 1 }} />
        <span style={{ fontSize: 12, fontFamily: 'var(--mono)', color: rep.passed ? TONE.green : TONE.red }}>{rep.passed ? '✓ PASSED' : '✗ FAILED'}</span>
        <button onClick={() => props.go('evals')} style={{ background: 'var(--bg-2)', color: 'var(--tx)', border: '1px solid var(--line)', borderRadius: 8, padding: '5px 10px', fontSize: 12, cursor: 'pointer' }}>Run / details</button>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 12 }}>
        {metrics.map(([label, v, lower, help]) => {
          const tone = metricTone(v, lower)
          return (
            <div key={label} style={card()}>
              <div style={{ fontSize: 11, opacity: 0.7, textTransform: 'uppercase', letterSpacing: '.05em' }}>{label}</div>
              <div style={{ fontSize: 30, fontWeight: 750, color: TONE[tone], fontFamily: 'var(--mono)' }}>{pctOrDash(v)}</div>
              <div style={{ fontSize: 11, color: 'var(--tx-3)', marginTop: 4 }}>{help}</div>
            </div>
          )
        })}
      </div>

      <Panel title="Detection quality (precision / recall)">
        <div style={{ display: 'flex', gap: 28, flexWrap: 'wrap', fontSize: 13 }}>
          <Stat label="Precision" value={pctOrDash(rep.precision)} />
          <Stat label="Recall" value={pctOrDash(rep.recall)} />
          <Stat label="Caught" value={`${rep.caught} / ${rep.injections}`} />
          <Stat label="Missed" value={String(rep.missed)} />
          <Stat label="False positives" value={String(rep.false_positives)} />
        </div>
      </Panel>
    </div>
  )
}

const card = (border?: string): CSSProperties => ({
  padding: 14, borderRadius: 12, background: 'var(--panel)',
  border: `1px solid ${border ? `${TONE[border]}55` : 'var(--line)'}`,
  borderLeft: border ? `3px solid ${TONE[border]}` : '1px solid var(--line)',
})
function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div style={{ fontSize: 10.5, color: 'var(--tx-faint)', textTransform: 'uppercase', letterSpacing: '.05em' }}>{label}</div>
      <div style={{ fontSize: 20, fontWeight: 700, fontFamily: 'var(--mono)' }}>{value}</div>
    </div>
  )
}
