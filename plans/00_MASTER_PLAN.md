# 00 — RedBlue AI: Master Plan & Canonical Decisions

> **Status:** Planning (pre-code). **Owner:** ESDS RedBlue AI team.
> **This document is AUTHORITATIVE.** Docs `01`–`09` MUST conform to the decisions here
> (directory layout, port map, service/network names, naming conventions, tech stack,
> phase numbering). If a downstream doc needs to deviate, it must flag the conflict back
> to this file — it does not silently diverge.

---

## 1. What we are building

**RedBlue AI — Real-Time Automated Red Team & Blue Team**: an AI-powered, continuously-running
purple-team platform for **ESDS Sovereign Cloud**. It closes the loop between an autonomous
red engine and an autonomous blue SOC, with a sensor plane in the middle so blue detects red
*for real* (not from red's self-report), all on **local LLM inference** (no foreign API egress).

**We are NOT building red or blue engines from scratch.** Both exist and are mature:

| Component | Repo | Role | Reuse? |
|---|---|---|---|
| 🔴 Decepticon | `Decepticon/` | Autonomous red team (~25 LangGraph agents, Neo4j attack graph, CART continuous replay) | **Reuse** |
| 🔵 Vigil (DeepTempo) | `vigil/` | Autonomous AI SOC (13 agents, daemon, approvals, ingestion) | **Reuse** |
| 🟡 vigil-llm (Deadbits) | `vigil-llm/` | Prompt-injection scanner | **Reuse (as MCP defense)** |
| 🎯 Sensor plane | NEW `telemetry/` | Wazuh + Suricata + Falco + target range | **Build (compose + configs)** |
| 🧠 Coordinator | NEW `redblue-coordinator/` | The closed-loop brain (LangGraph) | **Build** |
| 🛡️ Governance/Evidence | in coordinator | Tiered-autonomy policy + immutable audit | **Build** |
| 🖥️ Unified console | extends `vigil/frontend` | Single pane of glass + red engagement view | **Build (extend)** |

**The product is the glue + the governance + the sovereignty**, not the engines. See `redblue-strategic-moat` (memory) for why.

---

## 2. Target architecture (the closed loop)

```
        ┌──────────────── redblue-coordinator (LangGraph, :8900) ────────────────┐
        │  schedule engagement → trigger red → await telemetry → collect blue     │
        │  detections → score posture (MTTD/MTTR/detection-rate) → drive response │
        │  ── tiered-autonomy policy engine + immutable evidence store ──          │
        └───┬───────────────────────────────────────────────────────────┬────────┘
       trigger (scoped, per-tenant RoE)                          read ground-truth / score
            ▼                                                            ▲
  🔴 DECEPTICON ──attacks──▶ 🎯 TARGET + SENSORS ──alerts/logs──▶ 🔵 VIGIL ──investigate/respond──▶ ACTION
  LangGraph :2024            Wazuh/Suricata/Falco                 daemon + 13 agents               (gate: auto/human/never)
       │                                                                 │
       └──── shared attack graph: Decepticon Neo4j (engagement-scoped) ◀─┘  (blue reads red ground-truth)
       AI-native defense: vigil-llm MCP wraps all tool/log ingestion (both engines)
       Sovereignty: LiteLLM :4000 (red) + Bifrost :8080 (blue) → ONE Ollama :11434, zero egress
```

Layer responsibilities:
1. **Red (Decepticon)** — runs scoped engagements; emits findings (filesystem `FIND-*.md`), `events.jsonl`, and writes the engagement-scoped **Neo4j** attack graph.
2. **Sensor plane** — instruments the target; Wazuh (host), Suricata (network), Falco (container/K8s runtime) → alerts.
3. **Blue (Vigil)** — ingests sensor alerts as canonical findings; triages/investigates/responds via daemon + 13 agents; gates actions.
4. **Coordinator** — orchestrates the loop, scores "attacked vs detected," runs continuous mode (CART), enforces unified governance, writes the evidence store.
5. **Cross-cutting** — sovereignty (local Ollama), AI-native defense (vigil-llm), observability, multi-tenant scoping.

---

## 3. CANONICAL DECISION — Unified directory layout

```
/home/abhinav/Desktop/Purple_Team/
├── Decepticon/               # reused red engine   (kept as sibling repo, pinned by a thin superproject — see 01)
├── vigil/                    # reused blue engine
├── vigil-llm/                # reused injection scanner
├── redblue-coordinator/      # NEW  — the coordinator (Python 3.13, uv, LangGraph)
│   ├── redblue/              #        package: contracts/, loop/, connectors/, scoring/, governance/, evidence/, store/, api/, config/
│   ├── tests/
│   └── pyproject.toml
├── telemetry/                # NEW  — sensor plane
│   ├── wazuh/  suricata/  falco/  target-range/
│   └── docker-compose.telemetry.yml
├── deploy/                   # NEW  — unified bring-up
│   ├── docker-compose.redblue.yml   # coordinator + shared Ollama + the redblue-shared external net (NOT one merged file — stacks stay separate Compose projects; see §5)
│   ├── .env.example
│   ├── Makefile
│   └── k8s/ (later)
├── docs/                     # ADRs, integration notes, runbooks
└── plans/                    # THESE 10 planning docs (00–09)
```

**Rule:** we do **not** edit the three reused repos in place except through a small, tracked
patch set (documented in `01` and `06`). All new code lives in `redblue-coordinator/`,
`telemetry/`, `deploy/`. Engine changes are additive (a new Vigil connector file, a new MCP
server entry, config) and captured as patches so upstream updates stay mergeable.

---

## 4. CANONICAL DECISION — Unified port map (collisions resolved)

Both engines were authored independently and collide on `5432`, `8081`, `3000/3001/3003`, and the
`909x` range. Resolution: keep each stack's **internal** ports (inside its own Docker network) but
give every **host-exposed** port a unique number. Coordinator + telemetry claim fresh ranges.

| Service | Host port | Internal | Stack | Notes |
|---|---|---|---|---|
| Decepticon LangGraph API | **2024** | 2024 | red | control plane |
| Decepticon LiteLLM proxy | **4000** | 4000 | red | → Ollama |
| Decepticon Neo4j (bolt/http) | **7687 / 7474** | 7687/7474 | red | shared attack graph |
| Decepticon Postgres | **5433** | 5432 | red | ⚠ remapped (Vigil owns 5432) |
| Decepticon web dashboard | **3100** | 3000 | red | band-organization (behind default-off `web` profile; not a hard collision) |
| Decepticon terminal WS | **3103** | 3003 | red | band-organization (default-off `web` profile) |
| Decepticon sandbox | (none) | 9999 | red | never host-exposed |
| Decepticon skillogy | **9100** | 9100 | red | |
| Vigil backend API | **6987** | 6987 | blue | |
| Vigil frontend | **6988** | 6988 | blue | unified console lives here |
| Vigil Postgres | **5432** | 5432 | blue | keeps 5432 |
| Vigil Redis | **6379** | 6379 | blue | |
| Vigil Bifrost gateway | **8080** | 8080 | blue | → Ollama |
| Vigil daemon (webhook/prom/health) | **8082 / 9090 / 9091** | 8081/9090/9091 | blue | ⚠ webhook remapped 8081→8082 (Decepticon BHCE owns 8081) |
| Vigil Grafana / Jaeger / Prom(host) | **3001 / 16686 / 9095** | — | blue | observability profile |
| Decepticon BHCE (on-demand) | **8081** | 8081 | red | AD specialist only |
| **Ollama** | **11434** | 11434 | shared | single local LLM host |
| **Wazuh indexer / dashboard / manager** | **9200 / 8443 / 1514–1515,55000** | — | telemetry | dashboard remapped 443→8443 |
| **Falco gRPC** | **5060** | 5060 | telemetry | optional |
| **Kafka** (Falco lane) | **9092** | 9092 | telemetry | Falco→Falcosidekick→Kafka `security.findings`→Vigil (per doc 04) |
| **redblue-coordinator API** | **8900** | 8900 | coordinator | |
| **redblue-coordinator metrics** | **8902** | 8902 | coordinator | Prometheus scrape; UI **folds into the Vigil console** `:6988` (8901 unused — resolved per doc 09) |

Any doc introducing a new service claims the next free port in `89xx` (coordinator) or `92xx`
(telemetry aux) and records it here via a PR to this table.

---

## 5. CANONICAL DECISION — Networks & data stores

- **Docker networks:** `redblue-shared` (cross-stack bus: coordinator ↔ engines ↔ Ollama ↔ Neo4j),
  plus each stack keeps its private net (`decepticon-net`, `sandbox-net` **stays isolated**,
  `vigil-net`, `telemetry-net`). The Kali `sandbox-net` is **never** joined to `redblue-shared`. A **`range-net`** (added per doc 04) is the target-range network: the Kali `sandbox-net` takes `range-net` as its **only** extra attachment (so Decepticon can reach the target but still not the engines/Ollama), and the sensors (Wazuh agents / Suricata / Falco) sit on `range-net` watching the target.
- **Compose model (corrected per doc 02):** each stack runs as its OWN Compose project — both engines
  define a service literally named `postgres`, so a single merged `-f` chain would collide them into
  one broken service. They are joined only by the shared **external** `redblue-shared` network.
  `deploy/` orchestrates the separate projects; cross-project ordering is handled by the Makefile
  (`--wait` + retry) since `depends_on` can't cross projects. Requires **Compose v2.24+** (the
  `!override` tag is needed for Vigil's hardcoded `ports:`). On Linux, `host.docker.internal` isn't
  automatic, so **Ollama runs as a containerized service on `redblue-shared`** rather than via host
(both gateways use `http://ollama:11434`; Vigil's host-native `ollama_process` supervisor is bypassed —
host-native Ollama + `extra_hosts` is a documented alternative in doc 03).
- **Shared attack graph:** Decepticon's **Neo4j** is the single source of truth (Vigil's
  `graph_builder` is ephemeral). Blue reads it engagement-scoped (`MATCH (n) WHERE n.engagement=$e`).
  The coordinator connects with **read-only** creds (env `REDBLUE_DECEPTICON_NEO4J_*`, same bolt
  `:7687`, no new port) — per doc 06.
- **Two Postgres instances stay separate** (red `decepticon_web`, blue `vigil`) — do not merge; the
  coordinator has its own small store (SQLite for MVP → Postgres later) for engagements/scorecards/evidence.
- **One Ollama** serves both LiteLLM (:4000) and Bifrost (:8080).
- **Evidence store:** append-only, hash-chained (WORM-style) — see `08`.
- **Shared engagement workspace (per doc 06):** Decepticon's engagement workspace (`events.jsonl`,
  `findings/FIND-*.md`, `approvals/{requests,decisions}.jsonl`) is a **shared read-write volume**
  between Decepticon and the coordinator, so the coordinator can tail events (seam 3) and
  auto-adjudicate HITL by writing `approvals/decisions.jsonl` (seam 5d).

---

## 6. CANONICAL DECISION — Tech stack & versions

| Concern | Choice | Rationale |
|---|---|---|
| Coordinator language | **Python 3.13** (uv) | matches Decepticon; conda env `redblue` also OK |
| Orchestration | **LangGraph** | both engines are LangGraph/agent-SDK-native; avoids Shuffle AGPL |
| Coordinator API | **FastAPI** | matches Vigil; async |
| Coordinator store | SQLite (MVP) → **Postgres 16 + pgvector** | parity with Vigil |
| LLM (sovereign) | **Ollama** local; models per role-tier (see `03`) | DPDP/CERT-In, zero egress |
| Red LLM routing | LiteLLM proxy (Decepticon-native) | keep engine defaults |
| Blue LLM routing | Bifrost gateway (Vigil-native) | keep engine defaults |
| Sensors | **Wazuh** (host) + **Suricata** (network) + **Falco** (container/K8s) | covers Decepticon's kill-chain surface |
| Target range | v1: **DVWA + a vuln container**; sovereign-rep: **kubernetes-goat + Linux/AD** | the instrumented thing under attack (per doc 04) |
| Wazuh→Vigil wiring | **Wazuh Integrator webhook** → new `POST /api/webhooks/wazuh` (+ Kafka for Falco) | NOT the Elastic connector — Vigil's Elastic path needs Kibana Detection API (per doc 04) |
| Injection defense | **vigil-llm** wrapped as MCP tool | log-substrate prompt-injection |
| Containers | Docker + Compose v2 (K8s/Helm later) | both engines ship compose |
| CI | GitHub Actions (mirror each engine's) | |

**License hygiene:** keep GPL/AGPL components (Wazuh GPLv2, Suricata GPLv2) at arm's length —
deploy, don't fork-and-redistribute. Coordinator + new code = Apache-2.0 to match the engines.
Never build the coordinator on Shuffle (AGPLv3). See `redblue-integration-gotchas` (memory).

---

## 7. CANONICAL DECISION — Naming conventions

- Coordinator package: `redblue`; services `redblue-coordinator`, `redblue-ui`.
- Engagement id (shared tenant/scope key): `eng-<tenant>-<YYYYMMDD>-<short>` — MUST satisfy
  Decepticon's `DECEPTICON_ENGAGEMENT` regex `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`.
- Vigil finding from red: `finding_id = f-<YYYYMMDD>-<sha256_16>` (Vigil uses sha256[:16] = 64-bit per `ingestion_service.py:38-40`; the sha1_8/32-bit form was abandoned as collision-prone — do **not** use it). `data_source="decepticon"`.
- **Idempotency/dedup key:** Vigil dedupes on the DB unique index `(data_source, external_id)`, independent of `finding_id`. The red→blue connector MUST set `external_id="<engagement_id>:<red_action_id>"` — this is the real idempotency key (corrected per doc 05).
- Correlation join vocabulary: `mitre_predictions` keys MUST be **technique-IDs** (e.g. `T1059`), not tactic-names — legacy Vigil paths drift; all new producers use technique-IDs so red↔blue correlation can join.
- Env prefix for coordinator: `REDBLUE_`.
- Tenants: `tenant_id` threaded everywhere; never-auto rule keys off tenant/control-plane boundary.

---

## 8. CANONICAL DECISION — Phased roadmap (phase numbers are global)

| Phase | Name | Exit criteria | Primary docs |
|---|---|---|---|
| **P0** | Prereqs & standalone | Docker/uv/Ollama up; each engine runs standalone on Ollama | 01, 02, 03 |
| **P1** | Sovereignty | Both engines answer with **zero external egress** (verified) | 03 |
| **P2** | Sensor plane | Target range instrumented; Wazuh/Suricata/Falco alert → Vigil finding | 04, 05 |
| **P3** | Red→Blue seam | Decepticon findings+events+KG readable by Vigil/coordinator | 05, 06 |
| **P4** | Coordinator MVP | One manual engagement → scored scorecard (attacked vs detected) | 06, 07 |
| **P5** | Governance | Tiered-autonomy engine + immutable evidence + kill switch live | 08 |
| **P6** | AI-native defense | vigil-llm MCP hardening + hard verification gate | 08 |
| **P7** | Continuous + UI | CART continuous mode; unified console + posture dashboard | 07, 09 |
| **P8** | Multi-tenant + demo | Per-tenant isolation, hardening, demo script, eval metrics | 08, 09 |

Each doc carries its own detailed task breakdown; this table is the spine.

---

## 9. The 10 planning documents (index)

| # | File | Scope |
|---|---|---|
| 00 | `00_MASTER_PLAN.md` | **This file** — vision, canonical decisions, port map, phasing |
| 01 | `01_REPO_STRUCTURE_AND_SUBMODULES.md` | Repo org, submodule init/vendoring (empty vigil submodules), monorepo vs subtree, patch strategy, env/venv, build order |
| 02 | `02_INFRA_COMPOSE_AND_PORTS.md` | Unified Docker Compose topology, networks, volumes, health checks, resource/GPU sizing, bring-up order |
| 03 | `03_SOVEREIGNTY_LOCAL_LLM.md` | Ollama, per-role model tiers, wiring LiteLLM+Bifrost to one Ollama, disabling cloud, air-gap verification, quality mitigations |
| 04 | `04_TELEMETRY_SENSOR_PLANE.md` | Wazuh/Suricata/Falco + target range, alert→Vigil flow, mapping, target env options |
| 05 | `05_DATA_CONTRACTS_AND_SCHEMAS.md` | Canonical schemas: Vigil finding, Decepticon event/KG, coordinator engagement/scorecard, sensor→finding maps, approval/evidence records |
| 06 | `06_RED_BLUE_SEAMS_AND_CONNECTORS.md` | DecepticonIngestionService, shared-Neo4j bridge, blue-reads-red, MCP decepticon-driver tool + tool-tier fix, engine patch set |
| 07 | `07_COORDINATOR_LANGGRAPH.md` | Coordinator design: loop state machine, CART continuous mode, driving both engines, scoring (MTTD/MTTR), API + data model |
| 08 | `08_GOVERNANCE_AUTONOMY_AND_AI_DEFENSE.md` | Tiered-autonomy policy engine, per-tenant scoping, unifying red+blue gates, immutable evidence, kill switch, vigil-llm defense, verification gate |
| 09 | `09_UI_OBSERVABILITY_TESTING_ROADMAP.md` | Unified console (extend Vigil FE), observability, testing strategy, milestones, effort, risks, demo script |

---

## 10. Success criteria & non-negotiables

- **Sovereign:** demonstrable zero foreign-API egress (packet-capture proof).
- **Closed loop:** an attack Decepticon runs is independently detected by Vigil via sensors, and the
  coordinator produces a scorecard (what was attacked, what was detected, MTTD/MTTR, gaps).
- **Safe:** no containment action crosses a tenant boundary or touches the control plane without a
  human; every red action is RoE-scoped and logged; a working kill switch.
- **Evidenced:** every red action, blue verdict, and response is in a tamper-evident audit store.
- **Grounded:** no finding/verdict ships without a reproducible artifact or cited log lines.
- **Efficient to build:** reuse engines; new code confined to coordinator/telemetry/deploy.

## 11. Top risks (tracked in detail in 09)

1. **Sovereignty & quality (03)** — local-LLM quality drop vs cloud, worsened because Vigil's extended-thinking (9/13 agents) is **silently dropped** on the Ollama path; AND there are **silent cloud/embedding fallback paths** (Vigil `DEFAULT_MODEL`→Claude, `resolve_model_for_component` terminal Anthropic fallback, skillogy/KG `openai` embeddings, Vigil's 768-dim finding vectors) that MUST be explicitly closed or the zero-egress guarantee (§10) breaks.
2. Decepticon safety gates off-by-default + `isolate_host` mock in Vigil (must fix — `06`, `08`).
3. Empty Vigil submodules + Decepticon's disabled KG pipeline (integration cost — `01`, `06`).
4. Two LLM gateways / two Postgres / port collisions (managed via this doc + `02`).
5. Sensor-tuning noise vs signal; target-range realism (`04`).
6. **Vigil multi-tenancy gap** — `force_manual_approval` is **system-wide, not per-tenant**, and `approval_actions` has **no `tenant_id`** column. The coordinator MUST own per-tenant policy and treat Vigil's knob as a fail-closed global floor; a `tenant_id` column is a required engine patch (`06`). (per doc 08)
