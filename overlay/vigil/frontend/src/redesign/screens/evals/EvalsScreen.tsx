// RedBlue Evaluations (prompt §23) — ADDITIVE overlay.
// Runs the coordinator's red-team-of-the-AI corpus against the LIVE shield + policy engine
// (/api/coordinator/eval/injection) and shows the full report. Real numbers only.
import { useEffect, useState } from 'react'
import { EmptyState } from '../../shared/ui'
import { coordinatorApi, type InjectionEvalReport } from '../../../services/coordinatorApi'
import type { ScreenProps } from '../../shared/types'
import { Panel, TONE, pctOrDash } from '../redblue/kit'

export default function EvalsScreen(_props: ScreenProps) {
  const [rep, setRep] = useState<InjectionEvalReport | null>(null)
  const [state, setState] = useState<'idle' | 'running' | 'error'>('running')

  const run = () => {
    setState('running')
    coordinatorApi.runInjectionEval()
      .then(({ data }) => { setRep(data); setState('idle') })
      .catch(() => setState('error'))
  }
  useEffect(() => { run() }, [])

  const rows: [string, string][] = rep ? [
    ['Total cases', String(rep.total)],
    ['Injections', String(rep.injections)],
    ['Benign', String(rep.benign)],
    ['Caught (true positives)', String(rep.caught)],
    ['Missed (false negatives)', String(rep.missed)],
    ['False positives', String(rep.false_positives)],
    ['Injection catch rate', pctOrDash(rep.injection_catch_rate)],
    ['False positive rate', pctOrDash(rep.false_positive_rate)],
    ['Precision', pctOrDash(rep.precision)],
    ['Recall', pctOrDash(rep.recall)],
    ['Canary leak rate', pctOrDash(rep.canary_leak_rate)],
    ['Agent hijack rate', pctOrDash(rep.agent_hijack_rate)],
    ['Verification reject rate', pctOrDash(rep.verification_reject_rate)],
    ['Grounding compliance', pctOrDash(rep.grounding_compliance)],
  ] : []

  return (
    <div style={{ display: 'grid', gap: 16, padding: 16 }}>
      <Panel title="Injection eval"
        right={<button onClick={run} disabled={state === 'running'} style={{ background: TONE.violet, color: '#fff', border: 'none', borderRadius: 8, padding: '6px 12px', fontSize: 12.5, cursor: state === 'running' ? 'default' : 'pointer', opacity: state === 'running' ? 0.6 : 1 }}>{state === 'running' ? 'Running…' : 'Run injection eval'}</button>}>
        <div style={{ fontSize: 12.5, color: 'var(--tx-2)' }}>
          Runs the adversarial corpus against the live prompt-injection shield and policy engine. The
          safety gate <b>passes</b> only when agent-hijack = 0, no canary leak, high catch-rate and low false-positive rate.
        </div>
      </Panel>

      {state === 'error' && <EmptyState icon="alert" error title="Eval failed" body="Is the coordinator reachable at /api/coordinator/eval/injection?" />}
      {state === 'running' && !rep && <EmptyState icon="clock" loading title="Running corpus…" />}

      {rep && (
        <Panel title="Report" right={<span style={{ fontSize: 12, fontFamily: 'var(--mono)', color: rep.passed ? TONE.green : TONE.red }}>{rep.passed ? '✓ PASSED' : '✗ FAILED'}</span>}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <tbody>
              {rows.map(([k, v]) => (
                <tr key={k} style={{ borderBottom: '1px solid var(--line-soft)' }}>
                  <td style={{ padding: '8px 6px', color: 'var(--tx-2)' }}>{k}</td>
                  <td style={{ padding: '8px 6px', fontFamily: 'var(--mono)', textAlign: 'right' }}>{v}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      )}
    </div>
  )
}
