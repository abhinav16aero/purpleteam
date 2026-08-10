// RedBlue Knowledge Graph (prompt §8-12, §28-29, §37) — ADDITIVE overlay.
// The Neo4j attack graph, sanitized through the coordinator (/api/coordinator/graph). Interactive
// React Flow canvas: drag / zoom / pan / minimap, click → inspector, double-click → expand neighbors
// (real /graph/node/:id), pick-two → shortest path (real /graph/path), search + node-type filter.
// All data is LIVE from the coordinator; an empty graph shows an operational empty state (§41), never
// fabricated nodes. Colors follow the webapp's entity-type semantics; primitives + CSS-var tokens are
// Vigil's own (no new dependency — @xyflow/react is already used by WorkflowBuilder).
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type MouseEvent as ReactMouseEvent } from 'react'
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { EmptyState } from '../../shared/ui'
import { coordinatorApi, type Graph, type GraphNode } from '../../../services/coordinatorApi'
import type { ScreenProps } from '../../shared/types'

/* entity-type colors — the webapp's security-semantic node language */
const KIND_COLOR: Record<string, string> = {
  host: '#0d9488', ip: '#0d9488', asset: '#0d9488', server: '#0d9488', container: '#0891b2',
  database: '#7c3aed', application: '#2563eb', domain: '#1e40af', identity: '#a855f7', user: '#a855f7',
  port: '#0e7490', service: '#22b8cf', vulnerability: '#e05561', cve: '#dc2626', finding: '#e05561',
  alert: '#f97316', incident: '#dc2626', ioc: '#db2777', technique: '#f97316', mitre: '#f97316',
  tactic: '#ea580c', attack: '#e05561', agent: '#9d7ff0', tool: '#7a52c8', sensor: '#22b8cf',
  evidence: '#35c46b', event: '#4f8ef0',
}
const colorOf = (n: GraphNode) => {
  if (n.kind === 'technique' || n.kind === 'mitre') return n.detected ? '#35c46b' : '#f97316'
  if (n.kind === 'finding') return n.detected ? '#35c46b' : '#e05561'
  return KIND_COLOR[n.kind] || '#64748b'
}

/* deterministic radial layout by entity tier (React Flow has no built-in layout, no dagre dep) */
const TIER: Record<string, number> = {
  host: 0, asset: 0, server: 0, container: 0, database: 0, identity: 0,
  port: 1, service: 1, domain: 1, user: 1,
  finding: 2, alert: 2, vulnerability: 2, cve: 2,
  technique: 3, mitre: 3, tactic: 3, incident: 3, ioc: 3,
  agent: 4, sensor: 4, evidence: 4, tool: 4, event: 4,
}
const GOLDEN = 2.399963229728653
function layout(gnodes: GraphNode[]): Record<string, { x: number; y: number }> {
  const pos: Record<string, { x: number; y: number }> = {}
  gnodes.forEach((n, i) => {
    const tier = TIER[n.kind] ?? 2
    const r = 90 + tier * 150
    const a = i * GOLDEN
    pos[n.id] = { x: 640 + Math.cos(a) * r, y: 380 + Math.sin(a) * r }
  })
  return pos
}

function toFlowNode(n: GraphNode, pos: { x: number; y: number }, dimmed: boolean, marked: boolean): Node {
  const c = colorOf(n)
  return {
    id: n.id,
    position: pos,
    data: { label: (n.label || n.id).slice(0, 26), gnode: n },
    style: {
      background: 'var(--bg-2)', color: 'var(--tx)', border: `1.5px solid ${c}`,
      borderRadius: 8, padding: '6px 10px', fontSize: 11, fontFamily: 'var(--mono)',
      boxShadow: marked ? `0 0 0 2px var(--accent)` : `0 0 0 3px ${c}22`,
      opacity: dimmed ? 0.2 : 1, minWidth: 40, textAlign: 'center' as const,
    },
  }
}
function toFlowEdge(e: Graph['edges'][number], onPath: boolean): Edge {
  return {
    id: `${e.source}->${e.target}:${e.rel}`, source: e.source, target: e.target, label: e.rel,
    animated: onPath, style: { stroke: onPath ? 'var(--accent)' : 'var(--line-strong)', strokeWidth: onPath ? 2 : 1 },
    labelStyle: { fill: 'var(--tx-3)', fontSize: 9, fontFamily: 'var(--mono)' },
    labelBgStyle: { fill: 'var(--bg)', opacity: 0.7 },
  }
}

type Phase = 'loading' | 'ready' | 'empty' | 'error'

export default function KnowledgeGraphScreen(props: ScreenProps) {
  const [graph, setGraph] = useState<Graph>({ nodes: [], edges: [] })
  const [phase, setPhase] = useState<Phase>('loading')
  const [truncated, setTruncated] = useState(false)
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([])
  const [sel, setSel] = useState<GraphNode | null>(null)
  const [query, setQuery] = useState('')
  const [kind, setKind] = useState('')
  const [pathMode, setPathMode] = useState(false)
  const [pathIds, setPathIds] = useState<Set<string>>(new Set())
  const pickRef = useRef<string[]>([])
  const posRef = useRef<Record<string, { x: number; y: number }>>({})

  const load = useCallback(async () => {
    try {
      const { data } = await coordinatorApi.getGraph()
      if (!data.nodes.length) { setPhase('empty'); return }
      posRef.current = layout(data.nodes)
      setGraph(data); setTruncated(Boolean(data.truncated)); setPhase('ready')
    } catch { setPhase('error') }
  }, [])
  useEffect(() => { load() }, [load])

  const kinds = useMemo(() => [...new Set(graph.nodes.map((n) => n.kind))].sort(), [graph])

  // (re)project the graph model into React Flow whenever data / filters / path change
  useEffect(() => {
    if (phase !== 'ready') return
    const q = query.trim().toLowerCase()
    const visible = new Set(
      graph.nodes.filter((n) => (!kind || n.kind === kind)).map((n) => n.id),
    )
    const flowNodes = graph.nodes.map((n) => {
      const hidden = !visible.has(n.id)
      const dimmed = hidden || (q ? !(n.label || n.id).toLowerCase().includes(q) : false)
      const p = posRef.current[n.id] || { x: 640, y: 380 }
      return toFlowNode(n, p, dimmed, pathIds.has(n.id) || sel?.id === n.id)
    })
    const flowEdges = graph.edges
      .filter((e) => visible.has(e.source) && visible.has(e.target))
      .map((e) => toFlowEdge(e, pathIds.has(e.source) && pathIds.has(e.target)))
    setNodes(flowNodes); setEdges(flowEdges)
  }, [graph, query, kind, pathIds, sel, phase, setNodes, setEdges])

  const onNodeClick = useCallback((_e: ReactMouseEvent, node: Node) => {
    const g = (node.data as { gnode: GraphNode }).gnode
    if (pathMode) {
      const picks = [...pickRef.current, g.id].slice(-2)
      pickRef.current = picks
      if (picks.length === 2 && g.engagement) {
        coordinatorApi.shortestPath(g.engagement, picks[0], picks[1])
          .then(({ data }) => setPathIds(new Set(data.path || [])))
          .catch(() => setPathIds(new Set()))
      }
    }
    setSel(g)
  }, [pathMode, props])

  const onNodeDoubleClick = useCallback(async (_e: ReactMouseEvent, node: Node) => {
    const g = (node.data as { gnode: GraphNode }).gnode
    if (!g.engagement) return
    try {
      const { data } = await coordinatorApi.expandNode(g.id, g.engagement)
      setGraph((prev) => {
        const nid = new Set(prev.nodes.map((n) => n.id))
        const eid = new Set(prev.edges.map((e) => `${e.source}->${e.target}:${e.rel}`))
        const addN = data.nodes.filter((n) => !nid.has(n.id))
        addN.forEach((n, i) => {
          posRef.current[n.id] = { x: node.position.x + Math.cos(i) * 120, y: node.position.y + Math.sin(i) * 120 }
        })
        const addE = data.edges.filter((e) => !eid.has(`${e.source}->${e.target}:${e.rel}`))
        return { nodes: [...prev.nodes, ...addN], edges: [...prev.edges, ...addE] }
      })
    } catch { /* expand is best-effort; leave the graph as-is */ }
  }, [])

  const reset = () => {
    setQuery(''); setKind(''); setPathMode(false); setPathIds(new Set()); pickRef.current = []; setSel(null)
  }

  if (phase === 'loading') return <EmptyState icon="clock" loading title="Loading knowledge graph…" />
  if (phase === 'error')
    return <EmptyState icon="alert" error title="Graph service unavailable"
      body="Is the RedBlue coordinator reachable at /api/coordinator, and REDBLUE_DECEPTICON_NEO4J_PASSWORD set?" />
  if (phase === 'empty')
    return <EmptyState icon="shield" title="No graph data in current scope"
      body="Run an engagement (or seed the KG with demo-seed.sh) so Decepticon writes the attack graph to Neo4j. Try removing filters, another tenant, or a wider time range."
      primary={{ label: 'Go to Engagements', onClick: () => props.go('engagements') }} />

  return (
    <div style={{ position: 'relative', height: '100%', minHeight: 560, display: 'flex', flexDirection: 'column' }}>
      {/* filter bar (§29) */}
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '10px 12px', borderBottom: '1px solid var(--line)', flexWrap: 'wrap' }}>
        <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search nodes…"
          style={{ background: 'var(--bg-2)', border: '1px solid var(--line)', color: 'var(--tx)', borderRadius: 8, padding: '6px 10px', fontSize: 12, minWidth: 200 }} />
        <select value={kind} onChange={(e) => setKind(e.target.value)}
          style={{ background: 'var(--bg-2)', border: '1px solid var(--line)', color: 'var(--tx)', borderRadius: 8, padding: '6px 8px', fontSize: 12 }}>
          <option value="">All node types</option>
          {kinds.map((k) => <option key={k} value={k}>{k}</option>)}
        </select>
        <button onClick={() => { setPathMode((v) => !v); pickRef.current = []; setPathIds(new Set()) }}
          style={{ background: pathMode ? 'var(--accent)' : 'var(--bg-2)', color: pathMode ? '#fff' : 'var(--tx)', border: '1px solid var(--line)', borderRadius: 8, padding: '6px 10px', fontSize: 12, cursor: 'pointer' }}>
          Shortest path
        </button>
        <button onClick={reset} style={{ background: 'var(--bg-2)', color: 'var(--tx)', border: '1px solid var(--line)', borderRadius: 8, padding: '6px 10px', fontSize: 12, cursor: 'pointer' }}>Reset</button>
        <span style={{ flex: 1 }} />
        <span style={{ fontSize: 11, color: 'var(--tx-3)' }}>
          {graph.nodes.length} nodes · {graph.edges.length} relationships{truncated ? ' · truncated' : ''}
          {pathMode ? ' · pick two nodes' : ' · double-click to expand'}
        </span>
      </div>

      <div style={{ flex: 1, position: 'relative' }}>
        <ReactFlow
          nodes={nodes} edges={edges}
          onNodesChange={onNodesChange} onEdgesChange={onEdgesChange}
          onNodeClick={onNodeClick} onNodeDoubleClick={onNodeDoubleClick}
          fitView minZoom={0.15} proOptions={{ hideAttribution: true }}
        >
          <Background color="var(--line)" gap={22} />
          <MiniMap pannable zoomable nodeColor={(n) => colorOf((n.data as { gnode: GraphNode }).gnode)}
            style={{ background: 'var(--bg-1)' }} />
          <Controls showInteractive={false} />
        </ReactFlow>

        {/* right-side inspector (§12) */}
        {sel && (
          <aside style={{ position: 'absolute', top: 0, right: 0, bottom: 0, width: 320, background: 'var(--panel)', borderLeft: '1px solid var(--line)', overflowY: 'auto', boxShadow: 'var(--shadow)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '14px 16px', borderBottom: '1px solid var(--line)' }}>
              <span style={{ width: 26, height: 26, borderRadius: 6, background: colorOf(sel), display: 'grid', placeItems: 'center', color: '#fff', fontWeight: 700, fontSize: 12 }}>
                {(sel.kind[0] || '?').toUpperCase()}
              </span>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontWeight: 650, fontSize: 14, overflow: 'hidden', textOverflow: 'ellipsis' }}>{sel.label || sel.id}</div>
                <div style={{ fontSize: 11, color: 'var(--tx-3)', textTransform: 'uppercase', letterSpacing: '.05em' }}>{sel.kind}</div>
              </div>
              <span style={{ flex: 1 }} />
              <button onClick={() => setSel(null)} style={{ background: 'none', border: 'none', color: 'var(--tx-3)', cursor: 'pointer', fontSize: 18 }}>×</button>
            </div>
            <div style={{ padding: 16, display: 'grid', gap: 12, fontSize: 12.5 }}>
              {sel.detected != null && (
                <span style={{ justifySelf: 'start', padding: '3px 9px', borderRadius: 99, fontSize: 11, fontFamily: 'var(--mono)', color: sel.detected ? 'var(--ok)' : 'var(--crit)', border: `1px solid ${sel.detected ? 'var(--ok-dim)' : 'var(--crit-dim)'}` }}>
                  {sel.detected ? 'detected' : 'missed'}
                </span>
              )}
              <Row k="Type" v={sel.kind} />
              {sel.severity && <Row k="Severity" v={sel.severity} />}
              {sel.tool && <Row k="Tool" v={sel.tool} />}
              {sel.engagement && <Row k="Engagement" v={sel.engagement} />}
              <Row k="Neighbors" v={String(graph.edges.filter((e) => e.source === sel.id || e.target === sel.id).length)} />
              <div style={{ display: 'grid', gap: 6, marginTop: 4 }}>
                <button className="btn" onClick={() => props.go('engagements')} style={btn}>Trace attack path</button>
                <button className="btn" onClick={() => props.go('cases')} style={btn}>Related findings</button>
                <button className="btn" onClick={() => props.go('engagements')} style={btn}>Open engagement</button>
                <button className="btn" onClick={() => props.openChat(`Investigate ${sel.kind} ${sel.label || sel.id} in the attack graph.`)} style={btn}>Investigate with Vigil</button>
              </div>
            </div>
          </aside>
        )}
      </div>
    </div>
  )
}

const btn: CSSProperties = {
  background: 'var(--bg-2)', color: 'var(--tx)', border: '1px solid var(--line)',
  borderRadius: 8, padding: '7px 10px', fontSize: 12, cursor: 'pointer', textAlign: 'left',
}
function Row({ k, v }: { k: string; v: string }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, borderBottom: '1px solid var(--line-soft)', paddingBottom: 6 }}>
      <span style={{ color: 'var(--tx-faint)' }}>{k}</span>
      <span style={{ fontFamily: 'var(--mono)', textAlign: 'right', wordBreak: 'break-all' }}>{v}</span>
    </div>
  )
}
