/* ============================================================
   Recon Map — the RedAmon recon graph + map, ported into the Vigil
   console (plan: bring webapp theme/icons/recon-map/recon-graph into
   the dashboard; control recon through Decepticon via the coordinator).

   The screen is a pixel-faithful port of webapp/src/app/graph/page.tsx:
     · header with engagement picker + status + Start/Pause/Stop + logs
     · toolbar with 2D/3D, labels, cluster, legend toggles
     · node-type filter chips + legend overlay on the canvas
     · GraphCanvas (2D/3D force graph with pulsing glows, clusters,
       selection rings) + GraphNavControls (translate/orbit d-pad)
     · ReconLogsDrawer (phase strip over the coordinator's 7 loop nodes,
       SSE evidence stream via /api/coordinator/engagements/{id}/events)
     · node inspector drawer + analysis tables (scorecard techniques/gaps)

   Data source: the redblue-coordinator (engagements, KG graph, scorecard,
   evidence SSE) — Decepticon's recon runs through it. The webapp's own
   orchestrator/agent services are not part of the Purple_Team deploy.
   ============================================================ */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Radar, Play, Pause, Square, Terminal, RefreshCw, Box, Tag, Layers, List, X,
  ExternalLink, Loader2, AlertCircle,
} from 'lucide-react'
import './recon.css'
import { coordinatorApi, type Scorecard, type Graph as CoordinatorGraph } from '../../../services/coordinatorApi'
import { streamFetch } from '../../../services/api'
import { useEngagements, targetText, type EngRow } from '../redblue/kit'
import { GraphCanvas, AUTO_2D_THRESHOLD } from './GraphCanvas'
import { ReconLogsDrawer } from './ReconLogsDrawer'
import { COORDINATOR_PHASES, phaseNumberFor } from './coordinatorGraph'
import { clusterGraphData } from './clusterNodes'
import { NODE_COLORS } from './config'
import { getNodeUrl, getNodeSeverity } from './nodeHelpers'
import {
  coordinatorGraphToGraphData,
  evidenceRecordToLog,
  scorecardToRows,
} from './coordinatorGraph'
import type { GraphData, GraphNode, ReconLogEvent, ReconStatus } from './types'

type ViewMode = 'graph' | 'split' | 'analysis'
type AnalysisTab = 'techniques' | 'gaps' | 'scorecard'

const TENANT = 't01' // matches the Engagements screen default

const statusToReconStatus = (status: string | undefined): ReconStatus => {
  const s = (status || '').toLowerCase()
  if (s.includes('running') || s.includes('launch')) return 'running'
  if (s.includes('await') || s.includes('pending') || s.includes('pause')) return 'paused'
  if (s.includes('complet')) return 'completed'
  if (s.includes('fail') || s.includes('error') || s.includes('block') || s.includes('reject')) return 'error'
  return 'idle'
}

const phaseLabel = (name: string) =>
  name.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())

export default function ReconMapScreen() {
  // ── engagements ──
  const { list, sel, setSel } = useEngagements()
  const [engRow, setEngRow] = useState<EngRow | null>(null)

  // ── graph + scorecard ──
  const [graph, setGraph] = useState<CoordinatorGraph | undefined>(undefined)
  const [scorecard, setScorecard] = useState<Scorecard | null>(null)
  const [graphLoading, setGraphLoading] = useState(false)
  const [graphError, setGraphError] = useState<string | null>(null)

  // ── logs (SSE evidence replay) ──
  const [logs, setLogs] = useState<ReconLogEvent[]>([])
  const [streamState, setStreamState] = useState<'idle' | 'connecting' | 'streaming' | 'ended' | 'error'>('idle')
  const seenHashes = useRef<Set<string>>(new Set())

  // ── UI state ──
  const [is3D, setIs3D] = useState(false)
  const [showLabels, setShowLabels] = useState(true)
  const [showCluster, setShowCluster] = useState(true)
  const [showLegend, setShowLegend] = useState(true)
  const [showLogs, setShowLogs] = useState(true)
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null)
  const [viewMode, setViewMode] = useState<ViewMode>('split')
  const [analysisTab, setAnalysisTab] = useState<AnalysisTab>('techniques')
  const [hiddenTypes, setHiddenTypes] = useState<Set<string>>(new Set())
  const [locallyPaused, setLocallyPaused] = useState(false)
  const [busy, setBusy] = useState<null | 'start' | 'stop'>(null)
  const [target, setTarget] = useState('range-dvwa')
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  // ── status + phase ──
  const status: ReconStatus = locallyPaused ? 'paused' : statusToReconStatus(engRow?.status)
  const lastPhase = useMemo(() => {
    for (let i = logs.length - 1; i >= 0; i--) if (logs[i].phase) return logs[i].phase
    return null
  }, [logs])
  const currentPhaseNumber = phaseNumberFor(lastPhase)

  // ── load engagement data (graph + scorecard + logs) ──
  const loadEngagement = useCallback(async (id: string) => {
    if (!id) return
    setGraphLoading(true)
    setGraphError(null)
    try {
      const [gRes, sRes] = await Promise.all([
        coordinatorApi.getEngagementGraph(id).catch(() => ({ data: undefined as CoordinatorGraph | undefined })),
        coordinatorApi.getScorecard(id).catch(() => ({ data: null as Scorecard | null })),
      ])
      setGraph(gRes.data)
      setScorecard(sRes.data)
    } catch {
      setGraphError('Failed to load engagement graph')
    } finally {
      setGraphLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!sel) return
    setEngRow(list.find((e) => e.engagement_id === sel) ?? null)
    loadEngagement(sel)
  }, [sel, list, loadEngagement])

  // ── SSE log replay (coordinator replays the evidence chain, then ends) ──
  useEffect(() => {
    if (!sel) return
    const ac = new AbortController()
    setLogs([])
    seenHashes.current.clear()
    setStreamState('connecting')
    ;(async () => {
      try {
        const res = await streamFetch(`/coordinator/engagements/${sel}/events`, {
          headers: { Accept: 'text/event-stream' },
          signal: ac.signal,
        })
        if (!res.ok || !res.body) { setStreamState('error'); return }
        setStreamState('streaming')
        const reader = res.body.getReader()
        const dec = new TextDecoder()
        let buf = ''
        for (;;) {
          const { done, value } = await reader.read()
          if (done) break
          buf += dec.decode(value, { stream: true })
          let idx: number
          while ((idx = buf.indexOf('\n\n')) >= 0) {
            const frame = buf.slice(0, idx); buf = buf.slice(idx + 2)
            let evType = '', dataStr = ''
            for (const line of frame.split('\n')) {
              if (line.startsWith('event:')) evType = line.slice(6).trim()
              else if (line.startsWith('data:')) dataStr += line.slice(5).trim()
            }
            if (evType === 'end') { setStreamState((s) => (s === 'error' ? s : 'ended')); continue }
            try {
              const rec = JSON.parse(dataStr) as Record<string, unknown>
              const key = typeof rec.this_hash === 'string' ? rec.this_hash
                : `${rec.seq ?? ''}:${rec.record_type ?? ''}`
              if (seenHashes.current.has(key)) continue
              seenHashes.current.add(key)
              setLogs((prev) => [...prev, evidenceRecordToLog(rec)])
            } catch { /* non-JSON frame — skip */ }
          }
        }
        setStreamState((s) => (s === 'error' ? s : 'ended'))
      } catch {
        setStreamState((s) => (s === 'error' ? s : 'ended'))
      }
    })()
    return () => ac.abort()
  }, [sel])

  // ── controls ──
  const startRecon = async () => {
    setBusy('start')
    setErrorMessage(null)
    try {
      const in_scope = target.split(',').map((s) => s.trim()).filter(Boolean)
      const { data } = await coordinatorApi.launch({
        tenant_id: TENANT,
        mode: 'on_demand',
        scope: { in_scope, sandbox_url: 'http://sandbox:9999' },
      })
      const id = (data as { engagement_id?: string })?.engagement_id
      if (id) {
        setSel(id)
        await loadEngagement(id)
      }
    } catch {
      setErrorMessage('Launch failed — is the coordinator reachable?')
    } finally {
      setBusy(null)
    }
  }

  const stopRecon = async () => {
    if (!window.confirm('Stop this tenant\'s recon? (coordinator kill switch — halts the engagement loop)')) return
    setBusy('stop')
    setErrorMessage(null)
    try {
      await coordinatorApi.killTenant(TENANT, 'operator', 'recon map stop')
      await loadEngagement(sel)
    } catch {
      setErrorMessage('Stop failed — is the coordinator reachable?')
    } finally {
      setBusy(null)
    }
  }

  const refresh = async () => {
    if (!sel) return
    await loadEngagement(sel)
  }

  const toggleType = (type: string) => {
    setHiddenTypes((prev) => {
      const next = new Set(prev)
      if (next.has(type)) next.delete(type)
      else next.add(type)
      return next
    })
  }

  // ── display data: filter → cluster ──
  const rawData = useMemo<GraphData>(
    () => (graph ? coordinatorGraphToGraphData(graph, sel) : { nodes: [], links: [], projectId: sel }),
    [graph, sel],
  )

  const displayData = useMemo(() => {
    const filtered: GraphData = {
      nodes: rawData.nodes.filter((n) => !hiddenTypes.has(n.type)),
      links: rawData.links,
      projectId: rawData.projectId,
    }
    return showCluster ? clusterGraphData(filtered) : filtered
  }, [rawData, hiddenTypes, showCluster])

  // type counts for chips + legend (computed on raw data so filters can toggle back)
  const typeCounts = useMemo(() => {
    const counts = new Map<string, number>()
    for (const n of rawData.nodes) counts.set(n.type, (counts.get(n.type) ?? 0) + 1)
    return [...counts.entries()].sort((a, b) => b[1] - a[1])
  }, [rawData])

  const { techniques: techniqueRows, gaps: gapRows } = useMemo(
    () => scorecardToRows(scorecard),
    [scorecard],
  )

  const detectionRate = scorecard?.detection_rate ?? null
  const mttdMean = scorecard?.mttd?.mean ?? null

  const fmtPct = (f: number | null | undefined) => (f == null ? '—' : `${Math.round(f * 100)}%`)
  const fmtMttd = (s: number | null | undefined) =>
    s == null ? '—' : s < 60 ? `${Math.round(s)}s` : s < 3600 ? `${(s / 60).toFixed(1)}m` : `${(s / 3600).toFixed(1)}h`

  return (
    <div className={`ra-screen ra-view-${viewMode}`}>
      {/* ── header (page header bar) ── */}
      <header className="ra-header">
        <div className="ra-header-title">
          <Radar size={16} style={{ color: 'var(--accent-secondary)' }} />
          <span>Recon Map</span>
        </div>
        <select
          className="ra-engagement-picker"
          value={sel}
          onChange={(e) => { setSel(e.target.value); setSelectedNode(null) }}
          title="Engagement"
        >
          {list.length === 0 && <option value="">no engagements — start recon</option>}
          {list.map((e) => (
            <option key={e.engagement_id} value={e.engagement_id}>
              {e.engagement_id}{targetText(e.target) ? ` · ${targetText(e.target)}` : ''}
            </option>
          ))}
        </select>

        <span className={`ra-status-pill ra-status-${status}`}>
          <span className="ra-status-dot" />
          {status}
        </span>
        {status === 'running' && lastPhase && (
          <span style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--text-tertiary)' }}>
            phase {currentPhaseNumber ?? '?'}/{COORDINATOR_PHASES.length} · {phaseLabel(lastPhase)}
          </span>
        )}

        <div className="ra-spacer" />

        <div className="ra-action-group">
          <input
            value={target}
            onChange={(e) => setTarget(e.target.value)}
            placeholder="in-scope target(s)"
            title="In-scope target(s)"
            style={{
              background: 'var(--bg-input)', border: '1px solid var(--border-default)',
              borderRadius: 'var(--radius-default)', color: 'var(--text-primary)',
              fontSize: 'var(--text-xs)', fontFamily: 'var(--font-mono)',
              padding: '5px 8px', width: 170, outline: 'none',
            }}
          />
          <button
            type="button"
            className={`ra-recon-btn${status === 'running' ? ' ra-recon-btn-active' : ''}`}
            onClick={startRecon}
            disabled={busy !== null || status === 'running' || status === 'starting'}
            title="Start recon through Decepticon (coordinator launch)"
          >
            {busy === 'start' ? <Loader2 size={12} className="ra-drawer-spinner" /> : <Play size={12} />}
            {status === 'running' || status === 'starting' ? 'Running' : 'Start Recon'}
          </button>
          <button
            type="button"
            className="ra-pause-btn"
            onClick={() => setLocallyPaused((p) => !p)}
            title={locallyPaused ? 'Resume log stream' : 'Pause log stream (coordinator has no pipeline pause)'}
          >
            {locallyPaused ? <Play size={12} /> : <Pause size={12} />}
          </button>
          <button
            type="button"
            className="ra-stop-btn"
            onClick={stopRecon}
            disabled={busy !== null}
            title="Stop recon (tenant kill switch)"
          >
            {busy === 'stop' ? <Loader2 size={12} className="ra-drawer-spinner" /> : <Square size={12} />}
          </button>
        </div>

        <div className="ra-action-group">
          <button
            type="button"
            className={`ra-icon-btn${showLogs ? ' ra-icon-btn-active' : ''}`}
            onClick={() => setShowLogs((v) => !v)}
            title="Recon logs"
          >
            <Terminal size={14} />
          </button>
          <button type="button" className="ra-icon-btn" onClick={refresh} title="Refresh graph + scorecard">
            <RefreshCw size={14} />
          </button>
        </div>
      </header>

      {/* ── toolbar ── */}
      <div className="ra-toolbar">
        <div className="ra-action-group">
          {(['graph', 'split', 'analysis'] as ViewMode[]).map((m) => (
            <button
              key={m}
              type="button"
              className={`ra-icon-btn${viewMode === m ? ' ra-icon-btn-active' : ''}`}
              onClick={() => setViewMode(m)}
              title={m === 'graph' ? 'Graph only' : m === 'split' ? 'Graph + analysis' : 'Analysis only'}
              style={{ width: 'auto', padding: '0 10px', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.03em' }}
            >
              {m}
            </button>
          ))}
        </div>
        <div className="ra-divider" />
        <div className="ra-action-group">
          <button
            type="button"
            className={`ra-icon-btn${is3D ? ' ra-icon-btn-active' : ''}`}
            onClick={() => setIs3D((v) => !v)}
            title="3D view"
          >
            <Box size={14} />
          </button>
          <button
            type="button"
            className={`ra-icon-btn${showLabels ? ' ra-icon-btn-active' : ''}`}
            onClick={() => setShowLabels((v) => !v)}
            title="Show labels"
          >
            <Tag size={14} />
          </button>
          <button
            type="button"
            className={`ra-icon-btn${showCluster ? ' ra-icon-btn-active' : ''}`}
            onClick={() => setShowCluster((v) => !v)}
            title="Cluster leaves"
          >
            <Layers size={14} />
          </button>
          <button
            type="button"
            className={`ra-icon-btn${showLegend ? ' ra-icon-btn-active' : ''}`}
            onClick={() => setShowLegend((v) => !v)}
            title="Legend"
          >
            <List size={14} />
          </button>
        </div>
        <div className="ra-spacer" />
        <div className="ra-action-group">
          <span style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--text-tertiary)' }}>
            {displayData.nodes.length} nodes · {displayData.links.length} links
            {rawData.nodes.length > AUTO_2D_THRESHOLD && is3D ? ' · 2D forced (large graph)' : ''}
          </span>
          {errorMessage && (
            <span style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--status-error)' }}>
              <AlertCircle size={11} style={{ verticalAlign: '-2px', marginRight: 4 }} />
              {errorMessage}
            </span>
          )}
        </div>
      </div>

      {/* ── node-type filter chips ── */}
      {typeCounts.length > 0 && (
        <div className="ra-filters">
          {typeCounts.map(([type, count]) => (
            <button
              key={type}
              type="button"
              className={`ra-filter-chip${hiddenTypes.has(type) ? ' ra-filter-chip-off' : ''}`}
              onClick={() => toggleType(type)}
              title={`Toggle ${type}`}
            >
              <span className="ra-dot" style={{ background: NODE_COLORS[type] || NODE_COLORS.Default }} />
              {type}
              <span style={{ opacity: 0.6 }}>{count}</span>
            </button>
          ))}
        </div>
      )}

      {/* ── canvas ── */}
      <div className="ra-canvas-area">
        <GraphCanvas
          data={displayData}
          isLoading={graphLoading}
          error={graphError ? new Error(graphError) : null}
          is3D={is3D}
          width={0}
          height={0}
          showLabels={showLabels}
          selectedNode={selectedNode}
          onNodeClick={(node) => setSelectedNode(node)}
          isDark
        />

        {showLegend && typeCounts.length > 0 && (
          <div className="ra-legend">
            <div className="ra-legend-header" onClick={() => setShowLegend(false)}>
              <span>Legend</span>
              <X size={11} />
            </div>
            <div className="ra-legend-body">
              {typeCounts.slice(0, 40).map(([type, count]) => (
                <button
                  key={type}
                  type="button"
                  className="ra-filter-chip"
                  style={{ width: '100%', justifyContent: 'flex-start', marginBottom: 2 }}
                  onClick={() => toggleType(type)}
                  title={`Toggle ${type}`}
                >
                  <span className="ra-dot" style={{ background: NODE_COLORS[type] || NODE_COLORS.Default }} />
                  {type}
                  <span className="ra-legend-type">{count}</span>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* node inspector drawer */}
        <NodeInspectorDrawer node={selectedNode} onClose={() => setSelectedNode(null)} />

        {/* recon logs drawer */}
        <ReconLogsDrawer
          isOpen={showLogs}
          onClose={() => setShowLogs(false)}
          logs={logs}
          currentPhase={lastPhase}
          currentPhaseNumber={currentPhaseNumber}
          status={status === 'paused' ? 'paused' : status}
          onClearLogs={() => setLogs([])}
          onPause={() => setLocallyPaused(true)}
          onResume={() => setLocallyPaused(false)}
          onStop={stopRecon}
          title="Reconnaissance Logs"
          errorMessage={streamState === 'error' ? 'Coordinator stream unavailable' : errorMessage}
        />
      </div>

      {/* ── analysis section (scorecard) ── */}
      <div className="ra-analysis">
        <div className="ra-kpi-row">
          <div className="ra-kpi">
            <span className="ra-kpi-label">Detection rate</span>
            <span className={`ra-kpi-value ${detectionRate != null && detectionRate >= 0.5 ? 'ra-kpi-value-green' : detectionRate != null ? 'ra-kpi-value-red' : ''}`}>
              {fmtPct(detectionRate)}
            </span>
          </div>
          <div className="ra-kpi">
            <span className="ra-kpi-label">Attacked</span>
            <span className="ra-kpi-value">{scorecard?.attacked_techniques.length ?? 0}</span>
          </div>
          <div className="ra-kpi">
            <span className="ra-kpi-label">Detected</span>
            <span className="ra-kpi-value ra-kpi-value-green">{scorecard?.detected_techniques.length ?? 0}</span>
          </div>
          <div className="ra-kpi">
            <span className="ra-kpi-label">Missed</span>
            <span className="ra-kpi-value ra-kpi-value-red">
              {(scorecard?.attacked_techniques.length ?? 0) - (scorecard?.detected_techniques.length ?? 0)}
            </span>
          </div>
          <div className="ra-kpi">
            <span className="ra-kpi-label">MTTD (mean)</span>
            <span className="ra-kpi-value ra-kpi-value-amber">{fmtMttd(mttdMean)}</span>
          </div>
          <div className="ra-spacer" />
          <span style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--text-tertiary)' }}>
            {scorecard ? `scorecard v${scorecard.version} · ${scorecard.evidence_refs.length} evidence refs` : 'no scorecard yet'}
          </span>
        </div>

        <div className="ra-analysis-tabs">
          {(['techniques', 'gaps', 'scorecard'] as AnalysisTab[]).map((t) => (
            <button
              key={t}
              type="button"
              className={`ra-analysis-tab${analysisTab === t ? ' ra-analysis-tab-active' : ''}`}
              onClick={() => setAnalysisTab(t)}
            >
              {t}
            </button>
          ))}
        </div>

        <div className="ra-table-wrap">
          {analysisTab === 'techniques' && (
            <table className="ra-table">
              <thead>
                <tr>
                  <th>Technique</th><th>Attacked</th><th>Detected</th><th>Missed</th>
                  <th>Detection</th><th>MTTD</th>
                </tr>
              </thead>
              <tbody>
                {techniqueRows.length === 0 && (
                  <tr><td colSpan={6}><div className="ra-table-empty">No techniques scored yet — start recon to attack the target.</div></td></tr>
                )}
                {techniqueRows.map((t) => (
                  <tr key={t.technique_id}>
                    <td style={{ color: 'var(--text-primary)' }}>{t.technique_id}</td>
                    <td>{t.attacked}</td>
                    <td className={t.detected > 0 ? 'ra-detected' : ''}>{t.detected}</td>
                    <td className={t.missed > 0 ? 'ra-missed' : ''}>{t.missed}</td>
                    <td>{fmtPct(t.detection_rate)}</td>
                    <td>{fmtMttd(t.mttd_seconds)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {analysisTab === 'gaps' && (
            <table className="ra-table">
              <thead>
                <tr><th>Technique</th><th>Entity</th><th>First attack</th></tr>
              </thead>
              <tbody>
                {gapRows.length === 0 && (
                  <tr><td colSpan={3}><div className="ra-table-empty">No detection gaps — every attacked technique was detected.</div></td></tr>
                )}
                {gapRows.map((g, i) => (
                  <tr key={`${g.technique_id}-${i}`}>
                    <td style={{ color: 'var(--text-primary)' }}>{g.technique_id}</td>
                    <td>{g.entity ?? '—'}</td>
                    <td>{g.first_attack_ts ? new Date(g.first_attack_ts * 1000).toLocaleString() : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {analysisTab === 'scorecard' && scorecard && (
            <table className="ra-table">
              <thead>
                <tr><th>Field</th><th>Value</th></tr>
              </thead>
              <tbody>
                {[
                  ['scorecard_id', scorecard.scorecard_id],
                  ['version', String(scorecard.version)],
                  ['detection_rate', fmtPct(scorecard.detection_rate)],
                  ['attacked_techniques', scorecard.attacked_techniques.join(', ') || '—'],
                  ['detected_techniques', scorecard.detected_techniques.join(', ') || '—'],
                  ['mttd mean', fmtMttd(scorecard.mttd?.mean ?? null)],
                  ['mttd median', fmtMttd(scorecard.mttd?.median ?? null)],
                  ['mttd p90', fmtMttd(scorecard.mttd?.p90 ?? null)],
                  ['evidence refs', String(scorecard.evidence_refs.length)],
                ].map(([k, v]) => (
                  <tr key={k}>
                    <td style={{ color: 'var(--text-tertiary)' }}>{k}</td>
                    <td style={{ color: 'var(--text-primary)' }}>{v}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {analysisTab === 'scorecard' && !scorecard && (
            <div className="ra-table-empty">No scorecard yet — the coordinator produces one when the engagement completes a loop.</div>
          )}
        </div>
      </div>
    </div>
  )
}

/* ── Node inspector drawer (webapp NodeDrawer look) ── */

function NodeInspectorDrawer({ node, onClose }: { node: GraphNode | null; onClose: () => void }) {
  const isOpen = node !== null
  const url = node ? getNodeUrl(node) : null
  const severity = node ? getNodeSeverity(node) : 'unknown'
  const props = node?.properties ?? {}

  return (
    <div className={`ra-node-drawer${isOpen ? ' ra-node-drawer-open' : ''}`}>
      <div className="ra-node-drawer-header">
        <div className="ra-node-drawer-title">
          <span style={{ width: 9, height: 9, borderRadius: '50%', background: node ? (NODE_COLORS[node.type] || NODE_COLORS.Default) : 'transparent', flexShrink: 0 }} />
          <span>{node?.name ?? ''}</span>
        </div>
        <button className="ra-node-drawer-close" onClick={onClose} aria-label="Close">
          <X size={16} />
        </button>
      </div>
      <div className="ra-node-drawer-body">
        {node && (
          <>
            <div className="ra-node-drawer-section">
              <div className="ra-node-drawer-label">Type</div>
              <span className="ra-node-drawer-type">
                <span style={{ width: 8, height: 8, borderRadius: '50%', background: NODE_COLORS[node.type] || NODE_COLORS.Default }} />
                {node.type}
                {node.isCluster ? ` · ${node.clusterChildren?.length ?? 0} children` : ''}
                {severity !== 'unknown' ? ` · ${severity}` : ''}
              </span>
            </div>
            {url && (
              <div className="ra-node-drawer-section">
                <div className="ra-node-drawer-label">URL</div>
                <a className="ra-node-drawer-url" href={url} target="_blank" rel="noopener noreferrer">
                  <ExternalLink size={11} />
                  {url}
                </a>
              </div>
            )}
            <div className="ra-node-drawer-section">
              <div className="ra-node-drawer-label">Properties</div>
              {Object.keys(props).length === 0 && (
                <div className="ra-node-drawer-prop"><span className="ra-node-drawer-prop-key">—</span><span className="ra-node-drawer-prop-value">no properties</span></div>
              )}
              {Object.entries(props).map(([k, v]) => (
                <div key={k} className="ra-node-drawer-prop">
                  <span className="ra-node-drawer-prop-key">{k}</span>
                  <span className="ra-node-drawer-prop-value">
                    {v != null && typeof v === 'object' ? JSON.stringify(v) : String(v ?? '')}
                  </span>
                </div>
              ))}
            </div>
            {node.clusterChildren && node.clusterChildren.length > 0 && (
              <div className="ra-node-drawer-section">
                <div className="ra-node-drawer-label">Children</div>
                {node.clusterChildren.slice(0, 60).map((c) => (
                  <div key={c.id} className="ra-node-drawer-prop">
                    <span className="ra-node-drawer-prop-key" style={{ width: 60 }}>{c.type}</span>
                    <span className="ra-node-drawer-prop-value" style={{ color: 'var(--text-primary)' }}>{c.name}</span>
                  </div>
                ))}
                {node.clusterChildren.length > 60 && (
                  <div className="ra-node-drawer-prop">
                    <span className="ra-node-drawer-prop-key">…</span>
                    <span className="ra-node-drawer-prop-value">+{node.clusterChildren.length - 60} more</span>
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}