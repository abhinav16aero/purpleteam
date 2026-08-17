/* ============================================================
   Shared view-model types (Finding, CaseRow) + nav/title config
   for the SOC console. Screens fetch real data via services/api
   and map it into these shapes (see data/mappers.ts).
   ============================================================ */
import type { IconName } from '../shared/icons'

export type ScreenKey =
  | 'dashboard'
  | 'cases'
  | 'metrics'
  | 'analytics'
  | 'decisions'
  | 'workflows'
  | 'autoops'
  | 'overview'
  | 'posture'
  | 'engagements'
  | 'reconmap'
  | 'knowledgegraph'
  | 'aiagents'
  | 'aisafety'
  | 'evals'
  | 'approvals'
  | 'attackpaths'
  | 'mitre'
  | 'evidence'
  | 'sovereignty'
  | 'settings'

/** Runtime-dynamic rail membership, mirroring production's NavigationRail.
 *  A rail item carrying a gate only renders when the gate is satisfied. */
export interface NavGate {
  /** show only when this integration id is in the enabled-integrations list */
  integration?: string
  /** show only when the master orchestrator reports enabled */
  orchestrator?: boolean
}

/** [icon, label, screen-key | null, gate?] — null marks a not-yet-wired rail
 *  item (none today; Entity Graph now lives as a Dashboard tab). `gate` mirrors
 *  production's dynamic membership; the plumbing is live in SocConsole. No item
 *  is gated today: Auto Ops is intentionally always-visible (gating it made it
 *  vanish confusingly), and Timesketch has no redesign screen yet — when one
 *  lands, add `['…', 'Timesketch', 'timesketch', { integration: 'timesketch' }]`
 *  and the gating is done. */
export const NAV: [IconName, string, ScreenKey | null, NavGate?][] = [
  ['grid', 'Dashboard', 'dashboard'],
  ['folder', 'Cases', 'cases'],
  ['bars', 'Case Metrics', 'metrics'],
  ['pie', 'Analytics', 'analytics'],
  ['brain', 'AI Decisions', 'decisions'],
  ['flow', 'Workflows & Skills', 'workflows'],
  ['bot', 'Auto Ops', 'autoops'],
  ['sparkle', 'Command Center', 'overview'],
  ['shield', 'RedBlue Posture', 'posture'],
  ['bolt', 'Engagements', 'engagements'],
  ['graph', 'Recon Map', 'reconmap'],
  ['flow', 'Knowledge Graph', 'knowledgegraph'],
  ['bot', 'AI Agents', 'aiagents'],
  ['lock', 'AI Safety', 'aisafety'],
  ['check2', 'Evaluations', 'evals'],
  ['eye', 'Approvals', 'approvals'],
  ['link', 'Attack Paths', 'attackpaths'],
  ['grid', 'MITRE ATT&CK', 'mitre'],
  ['doc', 'Evidence', 'evidence'],
  ['infinity', 'Sovereignty', 'sovereignty'],
  ['gear', 'Settings', 'settings'],
]

export interface Finding {
  id: string
  sev: 'Critical' | 'High' | 'Medium' | 'Low'
  tech: string
  conf: number
  tactic: string
  src: string
  host: string
  user: string
  time: string
  /** epoch ms for the finding's timestamp — used to sort the Time column
   *  (the `time` string above is display-only and not safely comparable) */
  ts?: number
  score: number
  status: 'open' | 'investigating' | 'closed'
  /** entity_context keys the fixed fields above don't cover. Sources disagree
   *  about these — CrowdStrike sends device_id and no dest_ips, Splunk the
   *  reverse — so they're carried through rather than dropped, and rendered as
   *  optional columns derived from whatever the loaded rows actually contain. */
  extra?: Record<string, string>
}

export interface CaseRow {
  id: string
  title: string
  /** case description (optional; populated from the API) */
  desc?: string
  status: 'open' | 'investigating' | 'closed'
  prio: 'critical' | 'high' | 'medium' | 'low'
  owner: string
  ownerName: string
  findings: number
  tactic: string
  age: string
  sla: string
  slaState: 'warn' | 'danger' | 'ok'
  updated: string
  /** epoch ms for chronological sorting (display strings can't sort) */
  updatedTs?: number
  createdTs?: number
}

/** title + subtitle per screen (drives the topbar) */
export const TITLES: Record<ScreenKey, [string, string]> = {
  dashboard: ['Dashboard', 'Security operations overview'],
  cases: ['Cases', 'Manage investigation cases'],
  metrics: ['Case Metrics', 'Real-time SOC performance analytics'],
  analytics: ['Analytics Dashboard', 'Security operations analytics'],
  decisions: ['AI Decisions', 'Review and provide feedback for AI decisions'],
  workflows: ['Workflows & Skills', 'Pre-built multi-agent workflows for common SOC operations'],
  autoops: ['Auto Ops', 'Autonomous operations — master orchestrator and sub-agent investigations'],
  overview: ['Command Center', 'Live purple-team posture, engagements, approvals and AI activity'],
  posture: ['RedBlue Posture', 'Attacked-vs-detected coverage, MTTD and false-negative gaps'],
  engagements: ['Engagements', 'Launch and monitor scoped red-team engagements'],
  reconmap: ['Recon Map', 'Recon graph, live pipeline logs and scorecard analysis'],
  knowledgegraph: ['Knowledge Graph', 'Neo4j attack graph — assets, techniques, findings, detections, evidence'],
  aiagents: ['AI Agents', 'Blue-team agents, red-team runs and the coordinator'],
  aisafety: ['AI Safety', 'Red-team-of-the-AI evaluation results — hijack, injection, canary, grounding'],
  evals: ['Evaluations', 'Run the injection corpus against the live shield and policy engine'],
  approvals: ['Approvals', 'Human-in-the-loop queue for high-impact governed actions'],
  attackpaths: ['Attack Paths', 'Purple-team kill chain — red action → asset → technique → detection'],
  mitre: ['MITRE ATT&CK', 'Per-technique detection coverage grouped by tactic'],
  evidence: ['Evidence', 'Tamper-evident, hash-chained engagement ledger'],
  sovereignty: ['Sovereignty', 'On-prem inference topology, component health and zero foreign egress'],
  settings: ['Settings', 'Configure Vigil — AI, integrations, users and platform'],
}
