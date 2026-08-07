// RedBlue coordinator API client (plan 09 §1.2) — ADDITIVE overlay.
// Single-origin: hits Vigil's `/api/coordinator/*` reverse-proxy (backend/api/coordinator_proxy.py),
// so it inherits the shared axios instance's cookie+CSRF auth. Mirrors the `orchestratorApi` shape.
import { api } from './api'

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

  // ── scoring / posture / evidence ──
  getScorecard: (id: string, version?: number) =>
    api.get(`/coordinator/engagements/${id}/scorecard`, { params: { version } }),
  getPosture: (tenant_id?: string) => api.get('/coordinator/posture', { params: { tenant_id } }),
  getEvidence: (id: string, verify = false) =>
    api.get(`/coordinator/engagements/${id}/evidence`, { params: { verify } }),

  // ── continuous mode (CART) ──
  drift: (id: string, ce: Record<string, unknown>) =>
    api.post(`/coordinator/engagements/${id}/drift`, ce),
  approveReplay: (id: string, planId: string) =>
    api.post(`/coordinator/engagements/${id}/drift/${planId}/approve`),

  // ── governance ──
  kill: (by: string, reason: string) => api.post('/coordinator/kill', { by, reason }),
  killTenant: (tenant: string, by: string, reason: string) =>
    api.post(`/coordinator/tenants/${tenant}/kill`, { by, reason }),

  // ── eval (the demo proof asset) ──
  runInjectionEval: () => api.get('/coordinator/eval/injection'),

  // SSE live timeline URL (consumed via streamFetch, not axios)
  eventsUrl: (id: string) => `/api/coordinator/engagements/${id}/events`,
}
