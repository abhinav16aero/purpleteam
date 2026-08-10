// RedBlue coordinator API client (plan 09 §1.2) — ADDITIVE overlay.
// Single-origin: hits Vigil's `/api/coordinator/*` reverse-proxy (backend/api/coordinator_proxy.py),
// so it inherits the shared axios instance's cookie+CSRF auth. Mirrors the `orchestratorApi` shape.
import api from './api'

export interface Scorecard {
  scorecard_id: string; engagement_id: string; tenant_id: string; version: number
  attacked_techniques: string[]; detected_techniques: string[]
  detection_rate: number | null
  mttd: { mean: number | null; median: number | null; p90: number | null }
  per_technique: Array<{ technique_id: string; attacked: number; detected: number; missed: number;
    detection_rate: number | null; mttd_seconds: number | null }>
  gaps: Array<{ technique_id: string; entity: string | null; first_attack_ts: number | null }>
  evidence_refs: string[]
}

export interface Posture {
  engagements: number
  totals: { attacked: number; detected: number }
  detection_rate: number | null
  attacked_techniques: string[]; detected_techniques: string[]
  attack_coverage: { attacked: number; detected: number }
  mttd: { mean: number | null; median: number | null; p90: number | null }
  gap_count: number
  top_gaps: Array<{ technique_id: string; entity: string | null }>
}

export interface GraphNode {
  id: string
  kind: string
  label: string
  detected?: boolean
  engagement?: string
  severity?: string
  tool?: string
}
export interface GraphEdge {
  source: string
  target: string
  rel: string
}
export interface Graph {
  nodes: GraphNode[]
  edges: GraphEdge[]
  /** global graph only: the coordinator hit the node cap and stopped (paginate/scope) */
  truncated?: boolean
  /** shortest-path only: ordered node ids to highlight */
  path?: string[]
}

export interface Sensor {
  name: string
  kind: string
  status: string
  latency_ms?: number | null
  source?: string
  note?: string
}
export interface RedRun {
  engagement_id: string
  tenant_id?: string
  status?: string
  thread_id?: string
  target?: string | { name?: string; url?: string } | null   // coordinator returns the engagement target OBJECT
  team: string
  role: string
}
export interface RedAgents {
  team: string
  engine: string
  note: string
  runs: RedRun[]
  active: number
}

/** the coordinator's red-team-of-the-AI eval report (redblue/eval/harness.py InjectionEvalReport) */
export interface InjectionEvalReport {
  total: number
  injections: number
  benign: number
  caught: number
  missed: number
  false_positives: number
  injection_catch_rate: number | null
  false_positive_rate: number | null
  precision: number | null
  recall: number | null
  canary_leak_rate: number | null
  agent_hijack_rate: number
  verification_reject_rate: number | null
  grounding_compliance: number | null
  passed: boolean
  detail: Record<string, unknown>
}

export interface MitreTechnique {
  technique_id: string
  attacked: number
  detected: number
  missed: number
  detection_rate: number | null
  mttd_seconds: number | null
  engagements: number
}
export interface MitreRollup {
  scorecards: number
  technique_count: number
  totals: { attacked: number; detected: number }
  detection_rate: number | null
  techniques: MitreTechnique[]
}

/** the editable attack plan a human reviews before red executes (coordinator §2.3) */
export interface AttackPlan {
  engagement_id: string
  tenant_id?: string
  objective?: string
  instruction?: string
  in_scope?: string[]
  sandbox_url?: string | null
  enforcement_mode?: string
  hitl_enabled?: boolean
  mode?: string
  status?: string
  proposed_at?: number
  edited_by?: string
}

export const coordinatorApi = {
  // ── engagements (red control plane) ──
  listEngagements: (tenant_id?: string, status?: string) =>
    api.get('/coordinator/engagements', { params: { tenant_id, status } }),
  getEngagement: (id: string) => api.get(`/coordinator/engagements/${id}`),
  launch: (p: { tenant_id: string; engagement_id?: string; mode?: 'on_demand' | 'continuous';
                scope?: Record<string, unknown>; target?: Record<string, unknown>;
                instruction?: string; enforcement_mode?: string; hitl_enabled?: boolean }) =>
    api.post('/coordinator/engagements', p),
  stop: (id: string, reason = 'operator stop') =>
    api.post(`/coordinator/engagements/${id}/stop`, { reason }),

  // ── attack-plan human-in-the-loop (§2.3): review/edit/approve/reject before red executes ──
  getPlan: (id: string) =>
    api.get<{ engagement_id: string; plan: AttackPlan; awaiting_approval: boolean }>(`/coordinator/engagements/${id}/plan`),
  patchPlan: (id: string, body: { instruction?: string; objective?: string; in_scope?: string[] }) =>
    api.patch<{ engagement_id: string; plan: AttackPlan }>(`/coordinator/engagements/${id}/plan`, body),
  approvePlan: (id: string) => api.post(`/coordinator/engagements/${id}/plan/approve`),
  rejectPlan: (id: string, reason = 'rejected by operator') =>
    api.post(`/coordinator/engagements/${id}/plan/reject`, { reason }),

  // ── scoring / posture / evidence ──
  getScorecard: (id: string, version?: number) =>
    api.get(`/coordinator/engagements/${id}/scorecard`, { params: { version } }),
  getPosture: (tenant_id?: string) => api.get('/coordinator/posture', { params: { tenant_id } }),
  /** ATT&CK coverage rolled up across every engagement's latest scorecard (§21) */
  getMitreRollup: (tenant_id?: string) => api.get<MitreRollup>('/coordinator/mitre', { params: { tenant_id } }),
  getEvidence: (id: string, verify = false) =>
    api.get(`/coordinator/engagements/${id}/evidence`, { params: { verify } }),
  /** downloadable, self-verifying evidence bundle (digest-sealed; HMAC-signed when a key is configured) */
  getEvidenceBundle: (id: string) =>
    api.get<Blob>(`/coordinator/engagements/${id}/evidence/bundle`, { responseType: 'blob' }),

  // ── continuous mode (CART) ──
  drift: (id: string, ce: Record<string, unknown>) =>
    api.post(`/coordinator/engagements/${id}/drift`, ce),
  approveReplay: (id: string, planId: string) =>
    api.post(`/coordinator/engagements/${id}/drift/${planId}/approve`),

  // ── governance ──
  kill: (by: string, reason: string) => api.post('/coordinator/kill', { by, reason }),
  killTenant: (tenant: string, by: string, reason: string) =>
    api.post(`/coordinator/tenants/${tenant}/kill`, { by, reason }),

  // ── knowledge graph (Neo4j-backed, sanitized; §36-37) ──
  /** global graph = union of the tenant's engagement-scoped subgraphs (coordinator composes them) */
  getGraph: (tenant_id?: string, limit = 500) =>
    api.get<Graph>('/coordinator/graph', { params: { tenant_id, limit } }),
  getEngagementGraph: (id: string) => api.get<Graph>(`/coordinator/engagements/${id}/graph`),
  /** neighborhood expansion — scoped to the node's engagement */
  expandNode: (nodeId: string, engagement: string) =>
    api.get<Graph>(`/coordinator/graph/node/${encodeURIComponent(nodeId)}`, { params: { engagement } }),
  /** shortest path between two nodes in one engagement → { nodes, edges, path } */
  shortestPath: (engagement: string, source: string, target: string) =>
    api.post<Graph>('/coordinator/graph/path', { engagement, source, target }),

  // ── system status (honest: coordinator-probeable health + red-run rollup) ──
  getSensors: () => api.get<{ sensors: Sensor[] }>('/coordinator/sensors'),
  getAgents: (tenant_id?: string) =>
    api.get<RedAgents>('/coordinator/agents', { params: { tenant_id } }),

  // ── eval (the demo proof asset) ──
  runInjectionEval: () => api.get<InjectionEvalReport>('/coordinator/eval/injection'),

  // SSE live timeline URL (consumed via streamFetch, not axios)
  eventsUrl: (id: string) => `/api/coordinator/engagements/${id}/events`,
}
