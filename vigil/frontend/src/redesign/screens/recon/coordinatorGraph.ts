/* Data adapter: coordinator KG graph + SSE evidence records → the RedAmon
   recon-map shapes (GraphData / ReconLogEvent). The canvas, drawer and tables
   only ever see these shapes, so they stay a faithful copy of the webapp.

   Node types mirror the webapp's palette keys (Vulnerability/CVE/Service/...)
   with KG kinds added (Host/Finding/Technique/Mitre/Credential/...). The
   coordinator already flags technique/finding nodes `detected` from the
   engagement scorecard (redblue/scoring/extract.py kg_graph). */

import type {
  Graph as CoordinatorGraph,
  GraphNode as CoordinatorGraphNode,
  Scorecard,
} from '../../../services/coordinatorApi'
import type { GraphData, GraphNode, GraphLink, ReconLogEvent } from './types'

/** The coordinator loop's 7 nodes — the purple-team analogue of the webapp's
 *  RECON_PHASES (webapp/lib/recon-types.ts). SSE events carry a node name that
 *  maps onto this list for the phase progress strip. */
export const COORDINATOR_PHASES = [
  'plan_engagement',
  'trigger_red',
  'await_telemetry',
  'collect_detections',
  'decide_response',
  'score',
  'report_evidence',
] as const

export const phaseNumberFor = (nodeName: string | null | undefined): number | null => {
  if (!nodeName) return null
  const idx = COORDINATOR_PHASES.indexOf(nodeName as (typeof COORDINATOR_PHASES)[number])
  return idx === -1 ? null : idx + 1
}

/** coordinator kind (lowercased first Neo4j label) → webapp palette key */
const KIND_TO_TYPE: Record<string, string> = {
  host: 'Host',
  service: 'Service',
  port: 'Port',
  finding: 'Finding',
  vulnerability: 'Vulnerability',
  cve: 'CVE',
  technique: 'Technique',
  mitre: 'Mitre',
  capec: 'Capec',
  credential: 'Credential',
  account: 'Account',
  agent: 'Agent',
  evidence: 'Evidence',
  event: 'Event',
  asset: 'Asset',
  domain: 'Domain',
  subdomain: 'Subdomain',
  ip: 'IP',
  endpoint: 'Endpoint',
  secret: 'Secret',
  certificate: 'Certificate',
  technology: 'Technology',
}

const typeForKind = (kind: string): string => {
  if (!kind) return 'Node'
  const k = kind.toLowerCase()
  if (KIND_TO_TYPE[k]) return KIND_TO_TYPE[k]
  return k.charAt(0).toUpperCase() + k.slice(1)
}

/** wrap a plain value for the properties bag (objects/arrays stay untouched) */
const propValue = (v: unknown): unknown => {
  if (v == null) return undefined
  if (typeof v === 'object') return v
  return String(v)
}

export function coordinatorGraphToGraphData(
  coord: CoordinatorGraph | undefined,
  engagementId: string,
): GraphData {
  const nodes: GraphNode[] = (coord?.nodes ?? []).map((n: CoordinatorGraphNode) => {
    const props: Record<string, unknown> = {}
    if (typeof n.detected === 'boolean') props.detected = n.detected
    if (n.severity != null) props.severity = propValue(n.severity)
    if (n.tool != null) props.tool = propValue(n.tool)
    if (n.engagement != null) props.engagement = propValue(n.engagement)
    return {
      id: n.id,
      name: n.label || n.id,
      type: typeForKind(n.kind),
      properties: props,
    }
  })
  const links: GraphLink[] = (coord?.edges ?? []).map((e) => ({
    source: e.source,
    target: e.target,
    type: e.rel || 'RELATED_TO',
  }))
  return { nodes, links, projectId: engagementId }
}

/* ── SSE evidence record → recon log line ── */

const LEVEL_FOR_RECORD: Record<string, ReconLogEvent['level']> = {
  'red.launched': 'action',
  'engagement.planned': 'info',
  'engagement.completed': 'success',
  'telemetry.collected': 'info',
  'scorecard.produced': 'success',
  'policy_decision': 'info',
  'injection_block': 'warning',
  'verification_reject': 'warning',
  'red.failed': 'error',
  'loop.error': 'error',
  'sensor_alert': 'warning',
  'blue_finding': 'info',
  'detection': 'success',
  'decision': 'info',
  'response': 'info',
}

/** human-readable line for an evidence record; payloads fall back to compact JSON */
export function evidenceRecordToLog(record: Record<string, unknown>): ReconLogEvent {
  const recordType = typeof record.record_type === 'string' ? record.record_type : 'event'
  const payload = (record.payload && typeof record.payload === 'object'
    ? (record.payload as Record<string, unknown>)
    : {}) as Record<string, unknown>
  const actor = typeof record.actor === 'string' ? record.actor : ''
  const tsRaw = typeof record.ts === 'number' ? record.ts : Date.now() / 1000

  let log: string
  if (typeof payload.message === 'string' && payload.message) {
    log = payload.message
  } else {
    const summary = Object.entries(payload)
      .filter(([, v]) => v !== undefined && v !== null && typeof v !== 'object')
      .map(([k, v]) => `${k}=${String(v)}`)
      .join(' ')
    log = `[${recordType}]${summary ? ` ${summary}` : ''}`
  }

  const nodeName = typeof payload.node === 'string'
    ? payload.node
    : COORDINATOR_PHASES.find((p) => recordType.startsWith(p.replace('_', '.'))) || null

  return {
    timestamp: Math.round(tsRaw * 1000),
    level: LEVEL_FOR_RECORD[recordType] ?? (actor === 'red' ? 'action' : 'info'),
    phase: nodeName,
    log,
  }
}

/* ── Scorecard → analysis table rows ── */

export interface TechniqueRow {
  technique_id: string
  attacked: number
  detected: number
  missed: number
  detection_rate: number | null
  mttd_seconds: number | null
}

export interface GapRow {
  technique_id: string
  entity: string | null
  first_attack_ts: number | null
}

export const scorecardToRows = (card: Scorecard | null | undefined) => {
  const techniques: TechniqueRow[] = (card?.per_technique ?? []).map((t) => ({
    technique_id: t.technique_id,
    attacked: t.attacked,
    detected: t.detected,
    missed: t.missed,
    detection_rate: t.detection_rate,
    mttd_seconds: t.mttd_seconds,
  }))
  const gaps: GapRow[] = (card?.gaps ?? []).map((g) => ({
    technique_id: g.technique_id,
    entity: g.entity,
    first_attack_ts: g.first_attack_ts,
  }))
  return { techniques, gaps }
}