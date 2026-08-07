# 09 — Unified Console, Observability, Testing & Delivery Roadmap

> **Status:** Planning (pre-code). **Owner:** RedBlue AI full-stack lead.
> **Conforms to** `00_MASTER_PLAN.md` (authoritative). This doc EXPANDS §8 (phases),
> §10 (success), §11 (risks) and the §4 port map. Where reality diverges from the
> planning memory, it is flagged in **§7 Conflicts with 00**.
> **Verified against code** (see path references throughout): `vigil/frontend/src/redesign/*`,
> `vigil/frontend/src/services/api.ts`, `vigil/docker/*`, `vigil/daemon/metrics.py`,
> `Decepticon/TELEMETRY.md`.

This is the "single pane of glass + prove it works + ship it" doc. It answers four questions:
1. **Where does the operator sit?** → extend Vigil's React console (`:6988`), not a new app.
2. **How do we see the loop running?** → reuse Vigil's OTEL/Prometheus/Grafana/Jaeger, add a coordinator scrape + a RedBlue posture dashboard.
3. **How do we know it's correct?** → layered tests + a loop smoke test + an eval harness that is also the demo asset.
4. **In what order do we build it?** → P0–P8 milestone plan with effort, dependencies, and a demo-able outcome per phase.

---

## 1. Unified console — extend Vigil's React frontend into the single pane of glass

### 1.0 What already exists (verified)

The Vigil frontend (`vigil/frontend/`, React 18 + Vite 5 + TS, no component library — custom
primitives in `redesign/shared/`) already gives us most of a SOC console for free:

| Capability | Where | Reuse for RedBlue |
|---|---|---|
| Shell: nav rail + topbar + view router + chat dock + FAB | `redesign/SocConsole.tsx` | host for new screens |
| Built-in screen registry | `SocConsole.tsx` `SCREENS` map + `data/data.ts` `ScreenKey`/`NAV`/`TITLES` | add engagement + posture keys |
| Per-screen RBAC gate | `SocConsole.tsx` `SCREEN_PERMS` + `hasPermission()` | gate red actions |
| **Approvals queue (HITL surface)** | `screens/decisions/DecisionsScreen.tsx` + `approvalsApi` (`api.ts:158`) + `approval_actions` table | **reuse as-is** for tiered-autonomy gates |
| Autonomous-ops console (KPIs + control bar + queue + full-bleed detail + kill switch) | `screens/autoops/AutoOpsScreen.tsx` + `orchestratorApi` (`api.ts:1529`) | **template** for the engagement screen |
| Custom SVG charts (Donut, Pie, Spark, Trend, GroupedBars, Hbars, Heatmap) | `redesign/shared/charts.tsx` | posture scorecard — **no new chart dep** |
| ATT&CK rollup + tactic summary API | `attackApi` (`api.ts:1306`) | ATT&CK coverage tile |
| SSE streaming helper (cookie + CSRF + one-shot refresh) | `streamFetch()` (`api.ts:89`) | live engagement event stream |
| Page-extension host (iframe-grade isolation) | `redesign/extensions/` (`ExtensionProvider`, `ExtensionHost`, `contracts.ts`) | heavy 3D viz / third-party only |
| VStrike control-plane client (iframe + kill-chain replay) | `vstrikeApi` (`api.ts:504`) | shared attack visualization |

Real-time today = **10 s polling** (`setInterval(..., 10_000)` in `SocConsole.tsx:251`, and in each
screen's hook). **Only the Vigil chat is SSE** (via `streamFetch`). There is **no WebSocket** anywhere
in the frontend. This shapes every real-time decision below.

### 1.1 CANONICAL DECISION — native `ScreenKey` for core RedBlue screens; extension/iframe only for heavy 3-D

We add the RedBlue surface as **native in-tree screens** (new `ScreenKey`s + `NAV` entries), **not** as
connector extensions via `ExtensionProvider`. The extension path is reserved for (a) the optional heavy
3-D kill-chain visualization (VStrike, already an iframe integration) and (b) any genuinely third-party
connector.

**Why native, not the connector-extension iframe path:**

| Concern | Native `ScreenKey` | Connector extension (`ExtensionHost`) |
|---|---|---|
| What it's *for* | first-class product surface we own | arms-length third-party connectors Vigil "knows nothing about" (`contracts.ts` intent) |
| Theme / accent / dark-light | inherited free | must be re-seeded via `hostContext.themeTokens` and kept in sync |
| RBAC | `SCREEN_PERMS` + `hasPermission()` in-process | connector re-implements; host only gates the tab |
| Router / chat dock / toast / full-bleed | `ScreenProps` (`openChat`, `go`, `goSettings`, `setViewFull`) passed in | must be relayed as `ExtensionEvent`s (`navigate`/`notify`/`setViewFull`) |
| Auth to backend | same-origin cookie + CSRF (`api.ts` axios instance) | separate session-token mint (`extensionsApi.getSessionToken`) + connector BFF |
| Deploy | ships with the console bundle | separate connector process + `connectorUrl` + manifest fetch + strict CSP/origin lock (`ExtensionHost.tsx:75`) |
| Build cost | low (copy `AutoOpsScreen` pattern) | high (custom-element bundle, manifest, BFF, origin plumbing) |

The engagement/monitor and posture-scorecard screens are **the product** (the moat is the closed loop and
its governance/evidence — see `redblue-strategic-moat`). Making the product a plugin into itself adds
origin-isolation, session-mint, and theme-sync overhead for zero benefit. Native wins.

**When the extension/iframe path IS right:** the VStrike **3-D topology + kill-chain replay** is already an
iframe integration (`vstrikeApi.iframeToken()` returns `{ token, iframe_url }`, `api.ts:508`). Embedding a
GPU-heavy WebGL scene in-tree would bloat the bundle and couple our release to VStrike's. So the shared
attack visualization (§1.5) mounts VStrike **through the existing extension/iframe seam**, while the
engagement control + scorecard stay native. This is the clean split: **we own the data screens; we embed
the heavy third-party renderer.**

### 1.2 New screens, nav, and API service (the concrete wiring)

Add to `redesign/data/data.ts`:

```ts
export type ScreenKey =
  | 'dashboard' | 'cases' | 'metrics' | 'analytics'
  | 'decisions' | 'workflows' | 'autoops'
  | 'engagements'   // NEW — Red Team / Engagement launch + monitor
  | 'posture'       // NEW — RedBlue posture scorecard dashboard
  | 'settings'

// NAV — insert above the pinned Settings entry (SocConsole already slots
// extension tabs there; we place these two just below 'autoops'):
['target',   'Red Team',      'engagements'],   // icon: reuse a crosshair/target glyph
['shield',   'Posture',       'posture'],
```

Register in `SocConsole.tsx` `SCREENS` map and `TITLES`; add gates in `SCREEN_PERMS`:

```ts
// SocConsole.tsx SCREENS
engagements: EngagementsScreen,
posture: PostureScreen,

// SCREEN_PERMS — red control plane is privileged; posture is read-mostly
engagements: 'redteam.operate',   // never shown to a tenant without operate rights
posture:     'posture.read',
```

New RBAC permissions (`redteam.operate`, `redteam.approve`, `posture.read`) are added to Vigil's
`database/init/06_auth_tables.sql` seed (additive migration, tracked as an engine patch per `00 §3`).
In `DEV_MODE=true` the auth context grants every permission, so everything shows during dev — but the
gate is real once `DEV_MODE=false` (mandatory before any tenant exposure — see `00 §10`, `08`).

New frontend service module `frontend/src/services/api.ts` → `coordinatorApi` (mirrors `orchestratorApi`
shape so the screen code is a near-copy of `useAutoOps`):

```ts
export const coordinatorApi = {
  // control plane
  listEngagements: (status?) => api.get('/coordinator/engagements', { params: { status } }),
  getEngagement:  (id)       => api.get(`/coordinator/engagements/${id}`),
  launch: (p: { tenant_id; scope; playbook; mode: 'oneshot'|'continuous'; roe_id }) =>
                                 api.post('/coordinator/engagements', p),
  pause:  (id) => api.post(`/coordinator/engagements/${id}/pause`),
  kill:   (id) => api.post(`/coordinator/engagements/${id}/kill`),       // global kill switch (08)
  // scoring / evidence
  getScorecard: (id)  => api.get(`/coordinator/engagements/${id}/scorecard`),
  getPosture:   (params) => api.get('/coordinator/posture', { params }), // aggregate across engagements
  getKillChain: (id)  => api.get(`/coordinator/engagements/${id}/killchain`), // replay steps for viz
  exportEvidence: (id) => api.get(`/coordinator/engagements/${id}/evidence`, { responseType: 'blob' }),
}
```

**Routing note — single origin (design decision):** the coordinator is a *separate* FastAPI service on
`:8900` (`00 §4`), but the console must stay single-origin so it keeps cookie+CSRF auth, the CSP, and the
`streamFetch` SSE machinery. So we add a thin **`/api/coordinator/*` reverse-proxy router in the Vigil
backend** (`backend/api/coordinator_proxy.py`, forwarding to `REDBLUE_COORDINATOR_URL`, default
`http://redblue-coordinator:8900`). The frontend never talks to `:8900` directly. This is the same shape
as Vigil's existing `vstrike` proxy routes (`/api/integrations/vstrike/*` forward to VStrike). It also
gives us one auth choke point for the privileged red control plane.

### 1.3 Engagement launch / monitor view (`EngagementsScreen`)

Clone `AutoOpsScreen.tsx` structure (control bar + clickable KPI tiles + queue table + full-bleed detail):

- **Control bar:** tenant selector, RoE/scope picker (from the governance store, `08`), playbook picker
  (Decepticon engagement template), **mode toggle oneshot / continuous (CART)**, **Launch**, and a
  prominent **Kill switch** (red, always visible — maps to `coordinatorApi.kill`, the `00 §10` non-negotiable).
- **KPI tiles** (reuse `AutoOpsScreen` `KpiDef` pattern): Running · Awaiting-approval · Detected/Attacked
  (live ratio) · MTTD (rolling) · Failed. Each tile filters the queue.
- **Engagement queue table** (`redesign/shared/DataTable.tsx`): id (`eng-<tenant>-<date>-<short>`, `00 §7`),
  tenant, phase (recon→…→exfiltration, from Decepticon OPPLAN), attacked/detected, MTTD, autonomy tier of
  last action, status.
- **Full-bleed engagement detail** (like `InvestigationDetail.tsx`, tabs):
  - **Timeline** — interleaved red steps (from Decepticon `events.jsonl` / KG) and blue detections/verdicts
    (Vigil findings + `ai_enrichment`), the core "attack → detect" narrative.
  - **Kill-chain** — the shared visualization (§1.5).
  - **Approvals** — inline view of this engagement's pending gates (filters the shared approvals queue by
    `engagement_id`); actions deep-link to the AI Decisions screen.
  - **Evidence / chain-of-custody** — read from the coordinator evidence store (`08`); **Export** button
    (`exportEvidence`) — the demo's "hand the auditor a file" moment.

### 1.4 Posture scorecard dashboard (`PostureScreen`)

Pure read/aggregate screen; **all charts from `redesign/shared/charts.tsx`** (no new dependency):

| Panel | Data | Chart primitive |
|---|---|---|
| **Attacked vs Detected** | per-engagement + rolling; ground-truth from Decepticon KG/`events.jsonl`, detections from Vigil `findings` | `Donut` (detection-rate %) + `GroupedBars` (by tactic) |
| **MTTD / MTTR** | coordinator scoring (`07`) vs a configured human baseline | `Trend` (over time) + stat tiles |
| **ATT&CK coverage** | attacked techniques (red KG) ∩ detected (`attackApi.getTechniqueRollup`, `api.ts:1306`) | `Heatmap` (tactic × coverage) |
| **Autonomy actions by tier** | count of auto / human-approved / blocked actions (`08` governance ledger) | `Hbars` |
| **False-negative watchlist** | attacked-but-never-detected techniques (the gaps) | `DataTable` |
| **Egress = 0 monitor** | sovereignty SLI (§2.4) — green/red banner | stat tile + `Spark` |

Data path: `coordinatorApi.getPosture()` (aggregate) + `getScorecard(id)` (drill-in). The scorecard shape
is defined canonically in `05`; this screen only renders it.

### 1.5 Shared red/blue attack visualization — wiring the `vstrikeApi` kill-chain-replay seam

**Reality check (verified, and a conflict with the memory — see §7):** `vstrikeApi` is **not a WebSocket
kill-chain replay**. It is an **iframe integration + REST control plane** (`api.ts:504–664`):
`iframeToken()` mints an iframe session; `killchainReplay(network_id, steps[], opts)` POSTs a sequence of
`{ node_id, timestamp, technique, label, dwell_ms }` steps for VStrike's 3-D scene to walk; it returns
**501** when VStrike's MCP hasn't shipped the `ui-killchain-replay` tool yet (`api.ts:526`). Camera and
storyline VCR controls are likewise REST POSTs. There is **no WS** in this seam.

**Plan — reuse it as the shared viz, don't reinvent it:**
1. In the engagement detail's **Kill-chain** tab, mount VStrike **through the existing extension/iframe host**
   (or a minimal dedicated iframe wrapper using `vstrikeApi.iframeToken()`), gated by the `vstrike`
   integration being enabled (`NavGate.integration`, already supported in `SocConsole.tsx:300`).
2. The coordinator exposes `getKillChain(id)` → an ordered step list built from the **engagement-scoped
   Neo4j attack graph** (`00 §5`, the shared source of truth) enriched with Vigil detection timestamps, so
   each node carries **both** the red action time and the blue detection time. We feed that array straight
   into `vstrikeApi.killchainReplay(...)`.
3. **Colour the shared story:** each replay step gets a `detected: bool` (from the purple-team join). Red
   nodes that were detected render blue-outlined; undetected reds render red — the visual "what got past us."
   (VStrike honours per-step `label`/`technique`; the detected flag rides in `label`/legend until VStrike
   adds a first-class field.)
4. **Graceful degradation:** if VStrike is absent or returns 501, the Kill-chain tab falls back to a
   **native SVG timeline** built from the same step array (a horizontal `Trend`/lane render from
   `charts.tsx`). The 3-D scene is an enhancement, never a dependency — the closed-loop story must be tellable
   with zero third-party GPU renderer. This keeps the demo sovereign and offline-safe.

### 1.6 Real-time: keep 10 s polling as the floor, add ONE SSE stream (no WebSocket)

Current real-time is 10 s polling; only chat is SSE. We **do not** introduce WebSockets — the console is
read-mostly and its controls are discrete POSTs, so bidirectional framing buys nothing and adds a new
transport, proxy config, and reconnect story.

- **Scorecard/posture aggregates:** stay on **10 s polling** (matches `AutoOpsScreen`/`SocConsole`
  patterns; cheap; resilient). Reuse the existing `setInterval` idiom.
- **Live engagement timeline:** add **one SSE endpoint** `GET /api/coordinator/engagements/{id}/events`
  (proxied to coordinator `:8900`), consumed via the existing **`streamFetch()` helper** (`api.ts:89`) —
  which already carries cookies, the `X-CSRF-Token` double-submit header, and a one-shot 401→refresh→retry.
  Events: `red.step`, `sensor.alert`, `blue.finding`, `blue.verdict`, `gate.pending`, `action.taken`,
  `score.updated`. The detail view appends them to the timeline live; the SSE **augments**, and a 10 s poll
  **reconciles** on reconnect (so a dropped SSE never loses state). Reuse `useDesktopNotifications` for
  `gate.pending` (a human is needed).

This is a **1-endpoint, pattern-matching** addition — no new frontend transport, no new auth path.

### 1.7 HITL surface — reuse the approvals queue as-is (no new UI)

The tiered-autonomy model (`redblue-strategic-moat`, `08`) needs a human gate for high-impact/irreversible
and never-auto actions. Vigil already ships the surface: `DecisionsScreen` + `approvalsApi`
(`list`/`listPending`/`approve`/`reject`, `api.ts:158`) backed by the `approval_actions` audit table, and
the nav item is already RBAC-gated on `ai_decisions.approve` (`SocConsole.tsx` `SCREEN_PERMS`).

Plan (no new HITL screen):
- The coordinator/governance engine (`08`) writes gated actions as **`approval_actions` rows** (or POSTs to
  the approvals API) with `engagement_id`, `tenant_id`, requested action, autonomy-tier, and blast-radius
  metadata. They appear in the existing queue automatically.
- Register any **Decepticon-driver tool** and high-impact **blue response** as `requires_approval` in Vigil's
  tool-tier config (`06`, `vigil-governance-gates`), so they *route through* this queue instead of
  auto-executing.
- The engagement detail's **Approvals tab** is just a filtered view (`?engagement=<id>`) that deep-links into
  `DecisionsScreen` — the operator can work the queue from either place.

**Gap to close (from memory):** Vigil's `isolate_host` is a **mock** and the daemon confidence gate is
`0.90` (`vigil-governance-gates`); the never-auto tenant/control-plane boundary is enforced in the
coordinator, not the UI. The UI merely surfaces the gate — the actual enforcement lives in `08`. Flag kept
in the risk register (§5, R2).

---

## 2. Observability — reuse Vigil's stack, add coordinator metrics + a RedBlue posture dashboard

### 2.0 What already exists (verified)

Vigil ships a full opt-in observability profile (`vigil/docker/docker-compose.yml`,
`--profile observability`):

| Component | Host port (`00 §4`) | Role |
|---|---|---|
| OTEL Collector (contrib) | 4317/4318 | OTLP in → fan-out to Jaeger + Prometheus (exporter on `:8889`) |
| Jaeger | 16686 | distributed traces |
| Prometheus | **9095** (→ internal 9090) | scrapes `soc-daemon:9090`, `backend:9090`, `otel-collector:8889` (`docker/prometheus.yml`) |
| Grafana | **3001** | dashboards: `system_overview.json`, `llm_costs.json`, `investigation_lifecycle.json` (`docker/grafana/dashboards/`) |

Metrics are **OTEL-native**: `daemon/metrics.py` creates OTEL counters/histograms
(`soc_daemon_poller_polls_total`, `soc_daemon_poller_findings_total`,
`soc_daemon_processor_processed_total`, `_duration_seconds` histograms) exported via a
`PrometheusMetricReader` on `:9090`. This is the pattern the coordinator copies verbatim.

### 2.1 Add the coordinator as a first-class metrics source

- The coordinator (`redblue-coordinator`, FastAPI, `00 §6`) initializes OTEL exactly like Vigil's
  `core/telemetry.init_telemetry()` and exposes a `PrometheusMetricReader` endpoint on **`:8902`**
  (already reserved in `00 §4` for "coordinator metrics"). **Decision:** `8901` (standalone UI) is **not
  built** — the UI folds into the Vigil console (§1) — so only `8902` (metrics) is used. (Resolves the
  `00 §4` "if standalone UI; else fold" branch — see §7.)
- Add one scrape job to `docker/prometheus.yml` (or the unified `deploy/` compose, `00 §3`):
  ```yaml
  - job_name: redblue-coordinator
    static_configs:
      - targets: ["redblue-coordinator:8902"]
        labels: { service: redblue-coordinator }
  ```
- Coordinator emits traces to the same OTEL Collector (OTLP `:4317`) so a single Jaeger trace can span
  **coordinator → Decepticon trigger → sensor alert → Vigil investigation → response** — the closed loop as
  one waterfall. This is a strong demo artifact ("here is one attack, end-to-end, as a trace").

### 2.2 Key SLIs (the coordinator's OTEL instruments)

| SLI | Instrument (proposed) | Type | Source |
|---|---|---|---|
| **MTTD** (mean time to detect) | `redblue_mttd_seconds` | histogram | red step ts → first Vigil detection ts |
| **MTTR** (mean time to respond) | `redblue_mttr_seconds` | histogram | detection ts → response/containment ts |
| **Detection rate** | `redblue_attacks_total`, `redblue_detected_total` | counters | KG attacked ∩ Vigil detected |
| **False-negative rate** | derived (`1 − detected/attacks`) | recording rule | Prometheus rule |
| **Autonomy actions by tier** | `redblue_actions_total{tier=auto\|approved\|never}` | counter | governance ledger (`08`) |
| **Approval latency** | `redblue_approval_wait_seconds` | histogram | gate created → decided |
| **Engagements** | `redblue_engagements_total{mode,status}`, `redblue_engagement_active` | counter / up-down | loop state machine (`07`) |
| **Egress = 0** | `redblue_external_egress_bytes_total` | counter (must stay 0) | sovereignty probe (§2.4) |
| **LLM cost / tokens** | reuse Vigil's `llm_costs` + Bifrost logs; add red LiteLLM | — | existing + LiteLLM |

### 2.3 RedBlue posture Grafana dashboard

Add `docker/grafana/dashboards/redblue_posture.json` (auto-provisioned by the existing
`dashboard-provider.yaml`) alongside the three current dashboards. Rows:
1. **Loop health** — active engagements, engagement rate, phase distribution.
2. **Posture** — detection rate (gauge), MTTD/MTTR (time series vs baseline threshold lines), ATT&CK
   coverage heatmap.
3. **Governance** — actions by tier (stacked), approval latency, kill-switch events.
4. **Sovereignty** — `redblue_external_egress_bytes_total` (must be flat 0; alert if > 0), Ollama
   latency/throughput.

This Grafana board is the **operator/SRE** view; the in-console `PostureScreen` (§1.4) is the
**analyst/exec** view of the same SLIs. Same numbers, two audiences — no divergence because both read the
coordinator's scoring API/metrics.

### 2.4 The egress = 0 monitor (sovereignty as an SLI, not a slogan)

`00 §10` makes zero foreign-API egress a **non-negotiable, packet-capture-proven** success criterion. We
operationalize it:
- A lightweight **egress probe** sidecar on the `redblue-shared` net (or a Falco/Suricata rule on
  `telemetry-net`) counts bytes to any non-allowlisted external IP and exports
  `redblue_external_egress_bytes_total`. Allowlist = **only** local Ollama `:11434` and intra-cluster hosts.
- Grafana alert + console banner turn **red** the instant it's non-zero. This is both an SRE guardrail and a
  **demo money-shot**: "watch the counter stay 0 while a full engagement runs."
- **Decepticon telemetry caveat (verified, `Decepticon/TELEMETRY.md`):** Decepticon ships **opt-out**
  telemetry (`DECEPTICON_TELEMETRY=research` default) to an external gateway (Cloudflare Worker + PostHog).
  For sovereignty we **must** set `DECEPTICON_TELEMETRY=off` (or `DO_NOT_TRACK=1`, or point
  `DECEPTICON_TELEMETRY_ENDPOINT` at a local sink) in every enclave. This is a P1 checklist item and an
  egress-probe test case. **Upside:** Decepticon's Tier-A structural events (`finding.created` with a
  purple-team `detected` flag + `mitre_techniques` + `phase` + `confidence`) are exactly the scoring signal
  we want — the coordinator can consume them **locally** as a supplement to `events.jsonl` + the KG (`05`).

---

## 3. Testing strategy

Reuse each engine's existing harness; add the loop-level pieces that neither engine can have alone.

### 3.1 Per-component test layers

| Component | Unit | Integration | E2E |
|---|---|---|---|
| **Coordinator** (`redblue-coordinator`, pytest — mirror Vigil markers `unit`/`integration`/`slow`) | loop state machine transitions, scoring math (MTTD/MTTR/precision/recall), governance tier decisions (pure functions) | drives a **mocked** Decepticon LangGraph `:2024` + a **mocked** Vigil `:6987`; asserts a scorecard is produced; evidence-store hash-chain integrity | see §3.2 loop smoke |
| **Vigil connector patch** (`DecepticonIngestionService`, `06`) | `transform_alert_to_finding` maps attack event → canonical 13-field finding; idempotent `finding_id` | post a real Decepticon event JSON to `/api/ingest/ingest-string`; assert a finding row | — |
| **Vigil frontend (new screens)** — vitest + RTL (`Component.test.tsx`, collocated; existing config `vitest.config.ts`) | `EngagementsScreen`/`PostureScreen` render from fixture scorecards; KPI filters; SSE reducer appends events; kill-switch confirm dialog | mock `coordinatorApi` (MSW-style) → screen shows launch→running→scored | Playwright (§3.3) |
| **Vigil backend proxy** (`coordinator_proxy.py`) — pytest | forwards + strips auth correctly; SSE passthrough | proxy → live coordinator | — |
| **Telemetry/sensors** (`04`) | rule-mapping unit tests (Wazuh/Suricata/Falco alert → finding) | fire a known attack at the range; assert an alert lands as a Vigil finding | part of loop smoke |
| **Governance** (`08`) | tier classifier; never-auto tenant/control-plane boundary; kill switch | approval created → surfaces in `approvalsApi.listPending` → approve → action executes | loop smoke with a gated action |

Frontend note: there is **no e2e runner today** (`package.json` = vitest only, no Playwright/Cypress). We
**add Playwright** for console e2e (§3.3). Keep it out of the fast unit lane.

### 3.2 Loop-level smoke test (`make smoke` — the "does the loop close?" gate)

One command spins the full stack (`deploy/docker-compose.redblue.yml`, `00 §3`) and drives **one engagement
end-to-end**, asserting the closed loop:

```
make smoke  →  launch eng-smoke-* (oneshot, one known technique, e.g. T1046 network scan)
            →  Decepticon runs the scoped attack against the target range
            →  Suricata/Wazuh/Falco alert  →  Vigil ingests as a finding
            →  Vigil triages/investigates (local Ollama)
            →  coordinator joins red ground-truth vs blue detection
            →  ASSERT: scorecard exists, detection_rate > 0, MTTD recorded,
                        evidence hash-chain verifies, egress counter == 0
```

Runs as a pytest `integration`+`slow` test and as a **nightly CI job** (mirrors Vigil's `nightly.yml`). This
is the single most important regression gate — if it goes red, the product's core claim is broken. Its happy
path is also **exactly the demo** (§6), so it doubles as demo-readiness CI.

### 3.3 E2E (Playwright) — console flows

Add `frontend/playwright/` (new; gated behind an `e2e` npm script, not in the default `test`): launch an
engagement from the UI, watch KPIs update, approve a gated action from the approvals queue, open the
kill-chain tab (with VStrike stubbed), export evidence. Runs against the smoke stack in nightly CI.

### 3.4 Eval harness — quality gate **and** demo asset

The eval harness is the moat made measurable (`redblue-strategic-moat`: "false-negative rate, MTTD/MTTR vs
human baseline"). It is a coordinator sub-tool (`redblue/eval/`) that runs a **labeled attack corpus** and
scores blue's performance — held-out from the sparring partner so we test detection, not memorization
(`redblue-strategic-moat`: "red/blue evidence separation").

**Corpus:** a versioned set of labeled scenarios — `{technique, expected_detection, expected_severity,
kill-chain phase, ground-truth artifacts}` — spanning Decepticon's kill-chain surface (recon → exfiltration).
Includes **held-out real-ish attacks** (Atomic Red Team / replayed PCAPs) that Decepticon did **not**
generate, so blue is tested on strangers.

**Metrics computed** (per run, per technique, per tactic):
| Metric | Definition | Gate |
|---|---|---|
| **Precision** | detected-true / all-blue-alerts (false-positive control) | ≥ target (set in P4, ratchet up) |
| **Recall / detection rate** | detected-true / all-attacks | ≥ target |
| **False-negative rate** | attacked-but-never-detected | ≤ threshold; every FN listed by technique |
| **MTTD / MTTR** | vs a **configured human-analyst baseline** | report delta; regression alert |
| **Grounding compliance** | % verdicts carrying a reproducible artifact / cited log lines | 100% (hard gate, `00 §10`) |

**Outputs:** (1) a machine-readable `eval_report.json` (CI artifact; nightly trend), (2) Grafana panels
(feeds §2.3), (3) a one-page **exec scorecard** (the "we detect X% at Y MTTD, beating human baseline by Z"
slide — the demo's proof). CI treats a metric regression beyond tolerance as a **failing check**
(mirrors Vigil's nightly audits). The false-negative list is the product backlog: every FN is a detection
rule or sensor gap to close.

---

## 4. Delivery roadmap — P0–P8 expanded

Effort is rough person-weeks (pw) for a small team (≈2 backend, 1 frontend, 1 SRE/DevOps). Phases are the
global `00 §8` numbers; this table adds deliverables, dependencies, effort, and a **demo-able outcome** per
phase. Docs 01–08 own the deep task lists; 09 owns the console/observability/testing/eval slices called out
in **bold**.

| Phase | Deliverables (09 slices in **bold**) | Depends on | Effort | Demo-able outcome |
|---|---|---|---|---|
| **P0** Prereqs & standalone | Docker/uv/Ollama; each engine boots standalone; **CI mirrors per engine; repo/plan scaffold** | — | 2 pw | "Both engines start on my laptop." |
| **P1** Sovereignty | Both engines answer via local Ollama, zero egress; **Decepticon telemetry OFF; egress-probe + `redblue_external_egress_bytes_total`=0; Grafana Sovereignty row (skeleton)** | P0, `03` | 2 pw | "Pull the network cable — it still answers, egress counter flat 0." |
| **P2** Sensor plane | Wazuh/Suricata/Falco + target range; alert→Vigil finding; **sensor→finding mapping tests** | P1, `04` | 3 pw | "I run nmap at the range; a finding appears in Vigil." |
| **P3** Red→Blue seam | `DecepticonIngestionService`; shared-Neo4j read; blue reads red ground-truth; **connector unit/integration tests** | P2, `05`,`06` | 3 pw | "A Decepticon attack shows up as a Vigil finding, tagged `data_source=decepticon`." |
| **P4** Coordinator MVP | Loop state machine; one manual engagement → scorecard; **`coordinator_proxy` router + `coordinatorApi` + thin `EngagementsScreen` (launch/monitor) + minimal read-only scorecard tile; `make smoke` v1; eval harness v0 (targets set)** | P3, `07` | 5 pw | "Launch an engagement in the console; watch attacked-vs-detected score appear." |
| **P5** Governance | Tiered-autonomy engine; immutable evidence; kill switch; **approvals-queue reuse wired to gates; Evidence/Export tab; kill-switch button + `gate.pending` notifications** | P4, `08` | 4 pw | "A prod-isolate action pauses for my approval; I export a tamper-evident report." |
| **P6** AI-native defense | vigil-llm MCP in front of both engines' ingestion; hard verification/grounding gate; **grounding-compliance eval metric = hard CI gate** | P5, `08` | 3 pw | "A poisoned log can't drive an action; every verdict cites its evidence." |
| **P7** Continuous + UI | CART continuous mode; **full `PostureScreen` (all panels) + `redblue_posture.json` Grafana; SSE live timeline; VStrike kill-chain viz (native SVG fallback); e2e Playwright** | P4–P6, `07`,`09` | 5 pw | "Continuous purple-teaming runs 24/7; the posture dashboard trends live." |
| **P8** Multi-tenant + demo | Per-tenant isolation/scoping; hardening (`DEV_MODE=off`, Grafana auth); **eval on held-out corpus (MTTD/MTTR vs human baseline); the 10-min demo script; exec scorecard** | P7, `08` | 4 pw | "Tenant A can't see Tenant B; here's the pitch with real numbers." |

Total ≈ **31 pw** (~8 calendar months at this staffing, with overlap). Critical path: P0→P1→P2→P3→P4 (the
loop must close before UI/governance have anything to show). P5/P6 can partly parallelize P7 once P4 lands.

### 4.1 Gantt-ish timeline (each ▓ ≈ 2 weeks; parallel tracks)

```
Month             1     2     3     4     5     6     7     8
                 |--|  |--|  |--|  |--|  |--|  |--|  |--|  |--|
P0 Prereqs       ▓▓
P1 Sovereignty      ▓▓
P2 Sensors             ▓▓▓
P3 Red→Blue seam           ▓▓▓
P4 Coordinator MVP              ▓▓▓▓▓            ← first console + scorecard (demo-able)
P5 Governance                        ▓▓▓▓
P6 AI-defense                          ▓▓▓  (overlaps P5 tail)
P7 Continuous + UI                        ▓▓▓▓▓  ← full posture dashboard + live SSE
P8 Multi-tenant + demo                          ▓▓▓▓  ← eval numbers + pitch
                 |--|  |--|  |--|  |--|  |--|  |--|  |--|  |--|
Milestones:        M1↑        M2↑              M3↑          M4↑
  M1 = sovereign standalone (P1)   M3 = closed loop scored in console (P4)
  M2 = attack→finding (P2/P3)      M4 = governed, continuous, demo-ready (P7/P8)
```

**First externally-demo-able build = end of P4** (M3): a human launches an engagement in the Vigil console
and watches a real Decepticon attack get independently detected by Vigil-via-sensors and scored. Everything
after P4 hardens and dramatizes that core loop.

---

## 5. Risk register (expands `00 §11`)

Likelihood/Impact: L / M / H. Owner = role.

| # | Risk | Likelihood | Impact | Mitigation | Owner |
|---|---|---|---|---|---|
| **R1** | Local-LLM quality drop vs cloud degrades blue triage / red reasoning | H | H | Per-role model tiers (`03`); eval harness (§3.4) catches regressions; grounding gate rejects low-confidence unverified verdicts; keep MTTD/recall as CI gates | ML/Backend |
| **R2** | Safety gates off-by-default: Decepticon RoE/HITL OFF, Vigil `isolate_host` **mock**, daemon auto-response at conf `0.90` | H | H | `08` turns RoE/HITL ON per tenant; never-auto boundary enforced in coordinator; replace mock isolate with real (or keep dry-run); kill switch (§1.3); gated actions route through approvals queue (§1.7) | Security/Backend |
| **R3** | Empty Vigil submodules + Decepticon's disabled KG pipeline raise integration cost | M | M | Vendoring/patch strategy (`01`); if KG disabled, fall back to `events.jsonl` + Decepticon Tier-A telemetry for ground truth (§2.4); connector tests pin the contract (`05`) | Backend |
| **R4** | Two LLM gateways / two Postgres / port collisions | M | M | `00 §4` port map is law; `deploy/` compose owns host ports; one Ollama serves LiteLLM + Bifrost (`03`) | DevOps |
| **R5** | Sensor tuning noise vs signal; target-range unrealism | M | M | Start with high-signal rules; eval FN/FP metrics tune thresholds; range realism iterated in `04`; smoke test pins one known technique end-to-end | SRE/Detection |
| **R6** | **`vstrikeApi` is iframe+REST, not WS; `killchainReplay` may 501** (viz seam weaker than assumed) | M | L | Native SVG kill-chain fallback (§1.5 step 4) — 3-D is an enhancement, never a dependency; feature-gate on `vstrike` integration | Frontend |
| **R7** | **Real-time gap:** only chat is SSE, no WS; live timeline needs new plumbing | M | L | Single SSE endpoint via existing `streamFetch`; 10 s poll reconciles on reconnect; no new transport (§1.6) | Frontend |
| **R8** | **`DEV_MODE=true` bypasses ALL auth**; Grafana anonymous viewer on — unsafe once exposed | M | H | Enclave-only during dev; P8 hard-flip `DEV_MODE=false`, seed RBAC, disable Grafana anon; add to release checklist | Security/DevOps |
| **R9** | **Decepticon opt-out telemetry ships to external gateway** (egress + data leak) | M | H | `DECEPTICON_TELEMETRY=off`/`DO_NOT_TRACK=1` in every enclave; egress probe test asserts 0 (§2.4); P1 checklist item | Security |
| **R10** | Coordinator is net-new (neither engine ships it) — schedule risk on the critical path | M | H | LangGraph (both engines native, no Shuffle/AGPL); mockable engine interfaces let coordinator dev start before sensors are perfect; SQLite MVP store (`00 §6`) | Backend lead |
| **R11** | Evidence store integrity / auditability challenged by a regulator | L | H | Append-only hash-chain (WORM, `08`); smoke test verifies the chain; export produces a signed, reproducible bundle (§1.3) | Security |
| **R12** | Scope creep on the 3-D viz / bespoke dashboards eats roadmap | M | M | Charts from `shared/charts.tsx` only (no new dep); VStrike embedded not rebuilt; posture panels fixed in §1.4 | Frontend lead |

---

## 6. Demo script — 10-minute sovereign-cloud pitch (attack → detect → score → govern → evidence)

Audience: Indian BFSI/gov security buyer. Every beat ties to a **moat pillar** (`redblue-strategic-moat`).
Runs the **P4+ happy path = `make smoke` happy path** (§3.2), so the demo is a CI-guarded flow, not a
liveware gamble.

| Min | Beat | What the operator does | What they see | Moat pillar |
|---|---|---|---|---|
| 0:00 | **Set the frame** | Open the Vigil console (`:6988`); show the **Egress = 0** banner and Grafana Sovereignty row | Counter flat at 0; models are local Ollama | **Sovereignty as structure** |
| 1:00 | **Pull the cable** | Physically/virtually cut external network; ask Vigil a question | It still answers — no foreign API | **Sovereignty** (the killer differentiator vs US SaaS) |
| 2:00 | **Launch an attack** | On **Red Team** screen, launch `eng-demo-*` (oneshot, scoped by RoE) against the target range | Engagement goes Running; phase advances recon→… | **Closed purple-team loop** |
| 3:30 | **Detect for real** | Switch to the engagement **Timeline**; watch sensor alerts → Vigil findings arrive live (SSE) | Red steps and **blue detections** interleave — blue caught it from sensors, not red's self-report | **Closed loop** (real detection, the honesty pillar) |
| 5:00 | **Score the posture** | Open **Posture** dashboard | Attacked-vs-Detected donut, MTTD/MTTR vs human baseline, ATT&CK coverage heatmap, and the **false-negative watchlist** (the gaps we're honest about) | **Closed loop + eval rigor** |
| 6:30 | **Hit a governed action** | The loop proposes isolating a *production* workload → it **pauses** in the approvals queue | A `gate.pending` notification; the action waits for a human; tenant-boundary action is **never-auto** | **Graduated-autonomy governance** |
| 8:00 | **Approve + AI-defense** | Approve the reversible action; show a **poisoned log** that tries to drive an action getting **blocked** by the verification/grounding gate | Auto-tier action executes; the injection is refused; every verdict **cites its log lines** | **First-class AI-native defense** + grounding |
| 9:00 | **Hand over the evidence** | Click **Export** on the engagement | A tamper-evident, hash-chained report: every red action, blue verdict, and response, reproducible | **Immutable evidence/audit** (the regulator's pillar) |
| 9:45 | **Close** | One line: "Sovereign, closed-loop, governed, AI-defended — the four things no incumbent ships together." | The Posture exec scorecard slide (eval numbers) | All four pillars |

**Fallbacks (so the demo never dies):** VStrike 3-D → native SVG kill-chain (§1.5); SSE drop → 10 s poll
reconciles (§1.6); if the live engagement stalls, replay a pre-recorded `eng-demo-golden` from the evidence
store. All three are built, not improvised.

---

## 7. Conflicts / clarifications vs `00_MASTER_PLAN.md`

1. **`vstrikeApi` is NOT a WebSocket kill-chain replay (memory correction).** The `vigil-architecture`
   memory calls it "3D topology, kill-chain replay over WebSocket." Verified in `api.ts:504–664`, it is an
   **iframe integration + REST control plane** (`iframeToken()`, `killchainReplay()` returns **501** until
   VStrike's MCP ships `ui-killchain-replay`). No WebSocket exists. **Impact:** the shared viz reuses the
   iframe+REST seam with a **native SVG fallback**; any live timeline needs a **new SSE endpoint** (not a WS).
   Does not change `00`'s intent, but corrects the mechanism the seam depends on. (Risk R6.)

2. **Real-time is 10 s polling, not streaming (except chat SSE).** `00` doesn't specify a real-time
   transport. This doc **decides**: keep 10 s polling as the floor; add exactly **one SSE endpoint** via the
   existing `streamFetch` helper; **introduce no WebSockets.** (Risk R7.)

3. **Coordinator UI/metrics ports (`00 §4` open branch).** `00 §4` lists `8901/8902` "if standalone UI;
   else fold into Vigil console." This doc **resolves it: fold the UI into the Vigil console** (native
   screens, §1) — so **`8901` is not used**; only **`8902` (coordinator Prometheus metrics)** is claimed.
   Recommend updating `00 §4` to mark `8901` as reserved-unused.

4. **Console lands earlier than `00 §8` implies.** `00 §8` pairs the unified console with **P7**
   ("Continuous + UI"). But `00 §8` **P4** exit criterion ("one manual engagement → scored scorecard")
   needs a surface to launch/see it. This doc **splits the console**: a **thin `EngagementsScreen` +
   read-only scorecard at P4**, and the **full `PostureScreen` + live SSE + VStrike viz at P7**. This is an
   expansion/re-sequencing, not a contradiction — P7 still owns the "full UI."

5. **New RBAC permissions + engine patches.** Adds `redteam.operate`, `redteam.approve`, `posture.read` to
   Vigil's auth seed, and a `/api/coordinator/*` proxy router + `DecepticonIngestionService` — all as
   **additive, tracked engine patches** per `00 §3` (no in-place forking). Flagged so `01`/`06` account for
   them in the patch set.

6. **`DEV_MODE` + Grafana anonymous access must be hard-flipped before P8/tenant exposure** — added as a
   release-checklist gate (Risk R8), consistent with `00 §10` ("must be off before exposure") but made
   explicit as a deliverable.

---

*End of 09. Cross-refs: console↔`07` (coordinator API/scoring shapes), HITL/evidence↔`08`, connector↔`05`/`06`,
sensors↔`04`, sovereignty↔`03`. This doc is the delivery + proof layer over all of them.*
