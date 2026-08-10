// RedBlue Evidence / Audit Ledger (prompt §25) — ADDITIVE overlay.
// The tamper-evident, hash-chained WORM ledger for an engagement, from the coordinator
// (/api/coordinator/engagements/:id/evidence?verify=true). "Verify Ledger" re-runs the chain check.
// Real records only — no fabricated hashes, no fake "download signed bundle" button.
import { useCallback, useEffect, useState } from 'react'
import { EmptyState } from '../../shared/ui'
import { coordinatorApi } from '../../../services/coordinatorApi'
import type { ScreenProps } from '../../shared/types'
import { Panel, Tag, useEngagements, EngPicker } from '../redblue/kit'

interface EvRecord { seq: number; ts?: number | string; actor?: string; record_type?: string; prev_hash?: string; this_hash?: string; payload_hash?: string }
interface Evidence { engagement_id?: string; records?: EvRecord[]; count?: number; verified?: boolean }

const shortHash = (h?: string) => (h ? (h.length > 12 ? `${h.slice(0, 10)}…` : h) : '—')
const fmtTs = (t?: number | string) => {
  if (t == null) return '—'
  if (typeof t === 'number') { try { return new Date(t * (t < 1e12 ? 1000 : 1)).toISOString().slice(11, 19) } catch { return String(t) } }
  return String(t).slice(11, 19) || String(t)
}

export default function EvidenceScreen(_props: ScreenProps) {
  const { list, sel, setSel } = useEngagements()
  const [ev, setEv] = useState<Evidence | null>(null)
  const [phase, setPhase] = useState<'idle' | 'loading' | 'error'>('idle')
  const [bundling, setBundling] = useState(false)

  const load = useCallback(async (id: string) => {
    if (!id) return
    setPhase('loading')
    try { const { data } = await coordinatorApi.getEvidence(id, true); setEv(data as Evidence); setPhase('idle') }
    catch { setPhase('error') }
  }, [])
  useEffect(() => { load(sel) }, [sel, load])

  // download the server-built, self-verifying (digest-sealed / HMAC-signed) evidence bundle
  const downloadBundle = useCallback(async () => {
    if (!sel) return
    setBundling(true)
    try {
      const { data } = await coordinatorApi.getEvidenceBundle(sel)
      const url = URL.createObjectURL(data)
      const a = document.createElement('a')
      a.href = url; a.download = `evidence-${sel}.json`
      document.body.appendChild(a); a.click(); a.remove()
      URL.revokeObjectURL(url)
    } catch { /* download failed — nothing persisted client-side */ } finally { setBundling(false) }
  }, [sel])

  const records = ev?.records ?? []

  return (
    <div style={{ display: 'grid', gap: 16, padding: 16 }}>
      <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
        <EngPicker list={list} sel={sel} setSel={setSel} />
        {ev && (ev.verified
          ? <Tag tone="green">✓ CHAIN VERIFIED</Tag>
          : <Tag tone="red">✗ CHAIN BROKEN</Tag>)}
        <span style={{ flex: 1 }} />
        <button onClick={downloadBundle} disabled={bundling || !sel}
          style={{ background: 'var(--bg-2)', color: 'var(--tx)', border: '1px solid var(--line)', borderRadius: 8, padding: '6px 12px', fontSize: 12.5, cursor: sel ? 'pointer' : 'default', opacity: bundling || !sel ? 0.6 : 1 }}>
          {bundling ? 'Preparing…' : 'Download signed bundle'}
        </button>
        <button onClick={() => load(sel)} disabled={phase === 'loading' || !sel}
          style={{ background: 'var(--accent)', color: '#fff', border: 'none', borderRadius: 8, padding: '6px 12px', fontSize: 12.5, cursor: 'pointer', opacity: phase === 'loading' ? 0.6 : 1 }}>
          {phase === 'loading' ? 'Verifying…' : 'Verify ledger'}
        </button>
      </div>

      <Panel title="Evidence records" right={<span style={{ fontSize: 11, color: 'var(--tx-faint)' }}>{records.length} hash-chained records</span>}>
        {phase === 'error' ? <EmptyState compact icon="alert" error title="Evidence unavailable" body="Is the coordinator reachable, and does this engagement have a persisted chain?" />
          : phase === 'loading' && !ev ? <EmptyState compact icon="clock" loading title="Loading ledger…" />
          : records.length === 0 ? <EmptyState compact icon="doc" title="No evidence yet" body="Records are written as the engagement plans, attacks, detects, scores and gates." />
          : <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12.5 }}>
              <thead>
                <tr style={{ textAlign: 'left', color: 'var(--tx-faint)', fontSize: 10.5, textTransform: 'uppercase', letterSpacing: '.05em' }}>
                  <th style={th}>Seq</th><th style={th}>Record</th><th style={th}>Actor</th><th style={th}>Prev hash</th><th style={th}>This hash</th><th style={th}>Time</th>
                </tr>
              </thead>
              <tbody>
                {records.map((r) => (
                  <tr key={r.seq} style={{ borderBottom: '1px solid var(--line-soft)' }}>
                    <td style={{ ...td, fontFamily: 'var(--mono)' }}>{r.seq}</td>
                    <td style={{ ...td, fontFamily: 'var(--mono)', fontSize: 11.5 }}>{r.record_type || '—'}</td>
                    <td style={td}>{r.actor || '—'}</td>
                    <td style={{ ...td, fontFamily: 'var(--mono)', color: 'var(--tx-faint)' }}>{shortHash(r.prev_hash)}</td>
                    <td style={{ ...td, fontFamily: 'var(--mono)' }}>{shortHash(r.this_hash)}</td>
                    <td style={{ ...td, fontFamily: 'var(--mono)', color: 'var(--tx-faint)' }}>{fmtTs(r.ts)}</td>
                  </tr>
                ))}
              </tbody>
            </table>}
      </Panel>
      <div style={{ fontSize: 11, color: 'var(--tx-faint)' }}>ⓘ Each record’s <code>this_hash</code> commits to the previous — any tampering breaks the chain. The signed bundle is digest-sealed (SHA-256 over the canonical records) and HMAC-signed when <code>REDBLUE_EVIDENCE_SIGNING_KEY</code> is configured.</div>
    </div>
  )
}

const th = { padding: '8px 6px', borderBottom: '1px solid var(--line)' } as const
const td = { padding: '8px 6px' } as const
