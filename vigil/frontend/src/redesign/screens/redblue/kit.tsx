// Shared presentational bits for the RedBlue screens — Vigil-token styled, no new dependency.
// Kept tiny and local so the RedBlue screens stay consistent without touching the core shared/ kit.
import { useEffect, useState, type CSSProperties, type ReactNode } from 'react'
import { coordinatorApi } from '../../../services/coordinatorApi'

export const TONE: Record<string, string> = {
  red: '#e05561', blue: '#4f8ef0', green: '#35c46b', amber: '#e0a340', violet: '#9d7ff0',
}

export const panelStyle: CSSProperties = { padding: 15, borderRadius: 12, background: 'var(--panel)', border: '1px solid var(--line)' }
const secTitle: CSSProperties = { fontSize: 12, fontWeight: 650, marginBottom: 12, color: 'var(--tx-2)', textTransform: 'uppercase', letterSpacing: '.05em', display: 'flex', alignItems: 'center', gap: 8 }

export function Panel({ title, children, right }: { title?: ReactNode; children: ReactNode; right?: ReactNode }) {
  return (
    <section style={panelStyle}>
      {title != null && <div style={secTitle}>{title}<span style={{ flex: 1 }} />{right}</div>}
      {children}
    </section>
  )
}

export function Kpi({ label, value, tone = 'blue', sub, onClick }: { label: string; value: ReactNode; tone?: keyof typeof TONE; sub?: ReactNode; onClick?: () => void }) {
  return (
    <div onClick={onClick} style={{ padding: 14, borderRadius: 10, background: 'var(--bg-2)', border: '1px solid var(--line)', cursor: onClick ? 'pointer' : 'default' }}>
      <div style={{ fontSize: 10.5, opacity: 0.7, textTransform: 'uppercase', letterSpacing: '.05em' }}>{label}</div>
      <div style={{ fontSize: 26, fontWeight: 700, color: TONE[tone], fontFamily: 'var(--mono)' }}>{value}</div>
      {sub != null && <div style={{ fontSize: 11, color: 'var(--tx-3)', marginTop: 2 }}>{sub}</div>}
    </div>
  )
}

export function StatusPill({ status }: { status?: string }) {
  const s = (status || '').toLowerCase()
  const c = s.includes('run') || s.includes('pend') || s.includes('queue') ? TONE.amber
    : s.includes('fail') || s.includes('reject') || s.includes('block') || s.includes('error') ? TONE.red
    : s.includes('complet') || s.includes('approv') || s.includes('done') || s.includes('healthy') || s.includes('active') ? TONE.green
    : 'var(--tx-3)'
  return <span style={{ fontSize: 10.5, fontFamily: 'var(--mono)', color: c, border: `1px solid ${c}55`, borderRadius: 99, padding: '2px 8px', whiteSpace: 'nowrap' }}>{status || '—'}</span>
}

export function Tag({ children, tone = 'blue' }: { children: ReactNode; tone?: keyof typeof TONE }) {
  return <span style={{ fontSize: 10, fontFamily: 'var(--mono)', color: TONE[tone], background: `${TONE[tone]}18`, border: `1px solid ${TONE[tone]}44`, borderRadius: 6, padding: '2px 7px', whiteSpace: 'nowrap' }}>{children}</span>
}

export const pctOrDash = (f: number | null | undefined) => (f == null ? '—' : `${Math.round(f * 100)}%`)

export const asArray = <T,>(d: unknown, ...keys: string[]): T[] => {
  if (Array.isArray(d)) return d as T[]
  const o = (d ?? {}) as Record<string, unknown>
  for (const k of keys) if (Array.isArray(o[k])) return o[k] as T[]
  return []
}

/** The coordinator returns engagement `target` as {name,url} (or {}); never render it as a raw React child. */
export const targetText = (t: unknown): string =>
  typeof t === 'string' ? t
    : t && typeof t === 'object' ? ((t as { name?: string; url?: string }).name || (t as { url?: string }).url || '')
      : ''

export interface EngRow { engagement_id: string; target?: string | { name?: string; url?: string } | null; status?: string }

/** Load the engagement list once and track a selection — shared by Evidence / Attack Paths / MITRE. */
export function useEngagements() {
  const [list, setList] = useState<EngRow[]>([])
  const [sel, setSel] = useState('')
  useEffect(() => {
    let live = true
    coordinatorApi.listEngagements()
      .then(({ data }) => {
        if (!live) return
        const rows = asArray<EngRow>(data, 'engagements', 'data')
        setList(rows)
        setSel((s) => s || rows[0]?.engagement_id || '')
      })
      .catch(() => { /* screens render their own empty/error state */ })
    return () => { live = false }
  }, [])
  return { list, sel, setSel }
}

export function EngPicker({ list, sel, setSel }: { list: EngRow[]; sel: string; setSel: (v: string) => void }) {
  return (
    <select value={sel} onChange={(e) => setSel(e.target.value)}
      style={{ background: 'var(--bg-2)', border: '1px solid var(--line)', color: 'var(--tx)', borderRadius: 8, padding: '6px 10px', fontSize: 12.5 }}>
      {list.length === 0 && <option value="">no engagements</option>}
      {list.map((e) => <option key={e.engagement_id} value={e.engagement_id}>{e.engagement_id}{targetText(e.target) ? ` · ${targetText(e.target)}` : ''}</option>)}
    </select>
  )
}
