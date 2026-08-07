# 07 — The RedBlue Coordinator (LangGraph brain that closes the loop)

> **Status:** Planning (pre-code). **Owner:** ESDS RedBlue AI team. **Date:** 2026-08-05.
> **Conforms to:** `00_MASTER_PLAN.md` (AUTHORITATIVE). This doc designs the
> `redblue-coordinator/` service named in 00 §3, on port **:8900** (00 §4), tech
> stack per 00 §6, phases **P4** (Coordinator MVP) and **P7** (Continuous + UI) per 00 §8.
> **Depends on** `05_DATA_CONTRACTS_AND_SCHEMAS.md` (canonical finding / event / KG /
> engagement / scorecard schemas + correlation keys) and `06_RED_BLUE_SEAMS_AND_CONNECTORS.md`
> (DecepticonIngestionService, shared-Neo4j bridge, decepticon-driver MCP tool, engine patch set).
> **05 and 06 are not yet written** — where this doc needs a schema or a connector from them it
> cites the memory ground-truth (`redblue-integration-seams`) and marks the dependency `⟶ 05` / `⟶ 06`.
> Governance policy engine + immutable evidence WORM design are owned by `08` — this doc calls
> *into* them and defines only the coordinator-side contract. Conflicts with 00 are listed in §9.

This doc is a **plan with skeletons**, not final code. Every code block is a signature/shape sketch
to fix contracts, not an implementation.

---

## 0. Ground-truth this design is built on (verified in code)

| Claim used below | Verified in |
|---|---|
| Decepticon control plane is the **LangGraph Platform HTTP API on :2024**; `langgraph.json` registers graph `decepticon` (orchestrator) + 18 others; `http.multitask_strategy="interrupt"`; `http.app` mounts `server/plugins_api.py:app` with bundle toggles `POST /_decepticon/bundles/{name}/{enable\|disable}`. | `Decepticon/langgraph.json`, `packages/decepticon/decepticon/server/plugins_api.py` |
| **CART** ships `ChangeEvent`, `EngagementSnapshot.from_graph`, `diff_snapshots→SnapshotDelta(affected_techniques)`, `ReplayRunner(opplan_adapter, snapshot_provider, record_path, dry_run=True, dispatcher).plan()/.execute()`, `make_replay_dispatcher(invoke_agent)`, `Watcher(runner, prev_snapshot).subscribe()/handle_event()`, and the polling `AttackGraphProtocol.revision(engagement=)/snapshot(engagement=)`. Module **does not own the webhook receiver** ("HTTP endpoint on the langgraph service"), **does not write Neo4j**, **does not gate actions**, and `ReplayRunner` **defaults to dry-run**. | `packages/decepticon/decepticon/runtime/cart.py` |
| Red engagement telemetry = append-only **`engagements/<id>/events.jsonl`**; `EventType` ∈ {`engagement.start/end/checkpoint`, `agent.turn`, `tool.call`, `tool.result`, `llm.call`, `llm.response`, `finding.created`, `opplan.update`}; each `EngagementEvent(ts, type, agent, payload)`, `read_events()` skips torn lines. | `packages/decepticon/decepticon/runtime/event_log.py` |
| Vigil REST surface the coordinator drives (all under `_CONTEXT_PATH`): workflows/approvals mounted at `/api`, orchestrator at `/api/orchestrator`, ingest at `/api/ingest`, vstrike at `/api/integrations/vstrike`. | `vigil/backend/main.py` L337-402 |
| `POST /api/workflows/{id}/execute {finding_id\|case_id\|context\|hypothesis}` (one-shot for the 5 file playbooks), run history `GET /api/workflows/runs/{run_id}`, `POST /api/workflows/runs/{run_id}/{resume\|cancel}`. | `vigil/backend/api/workflows.py` |
| `POST /api/orchestrator/investigations {workflow_id, finding_ids, case_id, hypothesis, priority}`, `GET /status`, `POST /enable\|disable\|kill`, `GET /investigations/{id}/chain-of-custody`. | `vigil/backend/api/orchestrator.py` |
| `POST /api/ingest/ingest-string (Form: data, format=json, data_type=finding)` and background `POST /api/ingest/upload → poll /api/ingest/jobs/{id}`. | `vigil/backend/api/ingestion.py` |
| HITL surface: `GET /api/approvals[/pending]`, `POST /api/approvals/{id}/{approve\|reject}`; approving a workflow-linked action auto-resumes the paused run. | `vigil/backend/api/approvals.py` |
| Service-to-service auth gap: workflows / approvals / orchestrator / ingest routers all carry `AUTH_DEPENDENCY` (cookie-JWT, **`DEV_MODE=true` bypasses all auth**). Only `vstrike /findings` has a dedicated **Bearer `VSTRIKE_INBOUND_API_KEY`** service path. | `vigil/backend/main.py`, `vigil/backend/api/vstrike.py` |

---

## 1. Why LangGraph (and why not the alternatives), and the package layout

### 1.1 Decision: the coordinator IS a LangGraph `StateGraph`

Both engines are LangGraph / agent-SDK-native (Decepticon *is* a LangGraph Platform app; Vigil is
Claude-Agent-SDK + MCP). Building the coordinator as a LangGraph `StateGraph` gives us, for free, the
four properties this loop actually needs:

1. **Durable checkpointing.** A closed loop is long-running (red engagement minutes→hours, then a
   telemetry settle window, then scoring). A LangGraph **checkpointer** (SQLite MVP → Postgres, 00 §6)
   persists loop state at every node boundary, so a coordinator restart resumes mid-engagement instead
   of re-attacking. The engagement `thread_id` = the idempotency anchor (§2.5).
2. **Native human-in-the-loop.** LangGraph `interrupt()` / `interrupt_before` pauses the graph at
   `decide_response` and parks a durable checkpoint until an approval arrives via the API — exactly the
   tiered-autonomy gate (00 §, `redblue-strategic-moat`). No bespoke pause/resume plumbing.
3. **One runtime, one skillset.** We deploy/observe/trace the coordinator the same way as Decepticon.
   Streaming (`astream`) drives the live console (09).
4. **License-clean.** 00 §6 forbids building on **Shuffle (AGPLv3)** — an MSSP landmine. LangGraph
   (MIT) + our Apache-2.0 code keeps the license story clean.

### 1.2 Alternatives considered (and rejected)

| Option | Why not |
|---|---|
| **Shuffle** SOAR | AGPLv3 (00 §6 hard-no for an MSSP product); YAML-graph, not agentic; another runtime. |
| **Temporal** | Excellent durability, but a heavyweight Go/Java control plane + workers = a second orchestration substrate to run sovereign; overkill for one graph. Revisit only if we outgrow LangGraph checkpointing. |
| **Airflow / Prefect** | Batch/DAG schedulers; no first-class agent interrupt/streaming; awkward for an event-driven, human-gated loop. |
| **Plain FastAPI + asyncio** | No durable state → a restart mid-engagement loses the loop; we'd re-build checkpointing + HITL resume badly. |

**LangGraph wins on durability + HITL + runtime parity + license.** FastAPI still fronts it (§6) as the
control/API plane; LangGraph is the loop engine behind it.

### 1.3 Package layout — `redblue-coordinator/redblue/` (conforms to 00 §3)

```
redblue-coordinator/
├── pyproject.toml                # Python 3.13, uv; deps: langgraph, langgraph-checkpoint-*, fastapi,
│                                 #   httpx, langgraph-sdk, neo4j, sqlalchemy, pydantic, tenacity, apscheduler
├── redblue/
│   ├── loop/                     # THE state machine (§2)
│   │   ├── graph.py              #   build_graph() -> CompiledStateGraph ; wires nodes+edges+checkpointer
│   │   ├── state.py              #   LoopState (TypedDict) — the channel schema
│   │   ├── edges.py              #   conditional routing (route_after_score, route_after_decide, ...)
│   │   ├── checkpointer.py       #   SqliteSaver (MVP) -> PostgresSaver (later) factory
│   │   └── nodes/
│   │       ├── plan_engagement.py
│   │       ├── trigger_red.py
│   │       ├── await_telemetry.py
│   │       ├── collect_detections.py
│   │       ├── score.py
│   │       ├── decide_response.py
│   │       ├── report_evidence.py
│   │       └── watch_drift.py     # continuous-mode entry (§5)
│   ├── connectors/               # all engine/infra I/O (§3) — every call idempotent + retried
│   │   ├── decepticon.py         #   LangGraph :2024 client (langgraph-sdk) + decepticon-driver MCP (⟶06)
│   │   ├── vigil.py              #   Vigil REST client (workflows/orchestrator/ingest/approvals)
│   │   ├── neo4j_kg.py           #   engagement-scoped KG reader (bolt :7687) — attacked ground-truth
│   │   ├── sensors.py            #   optional direct sensor queries (Wazuh API) for coverage oracle (⟶04)
│   │   └── auth.py               #   Vigil session/JWT mint + Decepticon key + REDBLUE service identity
│   ├── scoring/                  # attacked-vs-detected (§4)
│   │   ├── correlate.py          #   join red attacks ⟷ blue detections on (engagement, technique, entity, window)
│   │   ├── metrics.py            #   detection-rate, MTTD, MTTR, ATT&CK coverage, gap list
│   │   ├── scorecard.py          #   Scorecard model + builder
│   │   └── attack_catalog.py     #   ATT&CK tactic/technique reference (coverage denominator)
│   ├── governance/               # thin client into the 08 policy engine (§2.6, §6)
│   │   ├── policy.py             #   evaluate_action(action, tenant) -> Decision{tier, requires_human}
│   │   └── gate.py               #   maps Decision -> LangGraph interrupt vs auto-execute
│   ├── evidence/                 # coordinator-side append-only writer; WORM/hash-chain spec ⟶08
│   │   ├── store.py              #   append(record) -> prev_hash chain ; verify_chain()
│   │   └── records.py            #   EvidenceRecord model + record kinds
│   ├── store/                    # ⚠ ADDITION to 00 §3 list — see §9 conflict C1
│   │   ├── models.py            #   SQLAlchemy: engagements, engagement_runs, drift_events, correlations,
│   │   │                        #     scorecards, response_actions, evidence, tenants
│   │   └── db.py                 #   engine/session factory (SQLite MVP -> Postgres)
│   ├── api/                      # FastAPI :8900 (§6)
│   │   ├── app.py               #   create_app(); mounts routers, health, prom metrics (:8902)
│   │   ├── deps.py              #   get_graph(), get_store(), get_settings(), service-auth guard
│   │   ├── schemas.py           #   request/response pydantic models
│   │   └── routes/
│   │       ├── engagements.py    #   start/stop/status/list
│   │       ├── scorecards.py     #   get scorecard, detections table
│   │       ├── evidence.py       #   list/verify evidence chain
│   │       ├── approvals.py      #   approve/reject a decide_response or CART replay (resumes interrupt)
│   │       ├── drift.py          #   CART change-event webhook (continuous)
│   │       └── health.py
│   ├── config/                   # settings + per-tenant policy (00 §7 REDBLUE_ prefix)
│   │   ├── settings.py           #   Pydantic BaseSettings, env REDBLUE_*
│   │   └── tenants.py            #   per-tenant RoE defaults, budgets, force_manual_approval
│   └── __init__.py
└── tests/
```

**Note on the two governance-adjacent packages.** `governance/` and `evidence/` live in the
coordinator (00 §3 lists both) but their *policy semantics* and *WORM hash-chain* are owned by **08**.
Here they are **thin adapters**: `governance/policy.py` calls the 08 policy engine; `evidence/store.py`
implements the append/verify contract 08 specifies. This doc pins the *call sites and record shapes*,
not the policy math.

---

## 2. The loop state machine

### 2.1 Node graph (LangGraph `StateGraph`)

```
            ┌──────────────────────── on-demand entry (POST /engagements) ─────────────────────────┐
            ▼                                                                                        │
   ┌─────────────────┐   ┌─────────────┐   ┌───────────────┐   ┌────────────────────┐   ┌────────┐  │
   │ plan_engagement │──▶│ trigger_red │──▶│ await_telemetry│──▶│ collect_detections │──▶│ score  │  │
   └─────────────────┘   └─────────────┘   └───────────────┘   └────────────────────┘   └───┬────┘  │
     scope/RoE/budget      drive Decepticon    poll Vigil +        query Vigil findings         │      │
     per tenant            via :2024 / MCP     sensors in window   + Decepticon KG (Neo4j)       ▼      │
                                                                                        ┌─────────────────┐
                                                                                        │ decide_response │
                                                                                        │  (GOVERNANCE    │
                                                                                        │   GATE + HITL)  │
                                                                                        └───┬────────┬────┘
                                                                             auto/approved │        │ needs-human
                                                                                            ▼        ▼ interrupt()
                                                                                   ┌────────────────────┐ (park on
                                                                                   │  report_evidence   │  durable
                                                                                   └─────────┬──────────┘  checkpoint)
                                                                                             │
                              on_demand ────────────────────────────────────────────────────┤
                                                                                             ▼
   ┌────────────┐  drift ChangeEvent (POST /engagements/{id}/drift)                     ┌─────────┐
   │ watch_drift│◀──────────────────────────────────────────────────────────────────── │  END /  │
   └─────┬──────┘  continuous mode: CART Watcher→ReplayRunner (dry-run→HITL→live)       │ CONTINUE│
         │  re-enters trigger_red with delta objectives ───────────────────────────────└─────────┘
         └──────────────────────────────────────────────────────────────────────────────────────▲
```

`build_graph()` registers the eight nodes, the conditional edges below, and the checkpointer.
Continuous engagements do not `END` after `report_evidence`; they route to `watch_drift`, which blocks
on the drift channel (fed by the API webhook) and, on a ChangeEvent, loops back into `trigger_red`.

### 2.2 `LoopState` (channel schema, `loop/state.py`)

```python
class LoopState(TypedDict, total=False):
    # identity / config
    engagement_id: str            # eng-<tenant>-<YYYYMMDD>-<short> (00 §7; matches DECEPTICON_ENGAGEMENT regex)
    tenant_id: str
    mode: Literal["on_demand", "continuous"]
    scope: dict                   # targets, in-scope CIDRs/hosts, RoE ref, sandbox_url (⟶05)
    budget: dict                  # max_cost_usd, max_wallclock_s, max_replays_per_hour
    # red side
    red_run: dict                 # {thread_id, run_id, graph:"decepticon", status, started_at, ended_at}
    red_objectives: list[str]     # full run, or delta objectives on a CART re-entry
    events_path: str              # engagements/<id>/events.jsonl (read-only tail)
    # telemetry window
    window: dict                  # {t_start, t_end, settle_deadline}  (epoch seconds)
    # blue side
    detections: list[dict]        # correlated Vigil findings (finding_id, technique, entity, ts)
    attacks: list[dict]           # attacked ground-truth from KG + events.jsonl (technique, entity, ts)
    # results
    scorecard: dict               # §4 model (nullable until score node runs)
    pending_actions: list[dict]   # decide_response outputs awaiting gate/HITL
    # control
    attempt: dict                 # per-node retry counters
    errors: list[dict]            # non-fatal node errors (for park/report)
    evidence_head: str            # last evidence hash (chain tip)
```

State reducers: `detections`/`attacks`/`errors` use `operator.add` (append-merge across retries);
scalar fields last-write-wins.

### 2.3 Node contracts (inputs → effects → outputs), timeouts, retries

| Node | Reads | Does | Writes | Timeout | Retry / idempotency |
|---|---|---|---|---|---|
| **plan_engagement** | request body, `config/tenants.py`, RoE (⟶05/08) | Validate `engagement_id` against Decepticon regex; resolve tenant scope + budget + `force_manual_approval`; **assert RoE `enforce` + `DECEPTICON_HITL__ENABLED` per tenant** (decepticon-safety-gates); write `engagements` + first evidence record (`engagement.planned`). | `scope`, `budget`, `window.t_start`, `evidence_head` | none | Pure/validating; safe to re-run — upsert on `engagement_id`. |
| **trigger_red** | `scope`, `red_objectives` | Drive Decepticon (§3.1): create thread + start run on graph `decepticon` with `config.configurable={engagement_name, workspace_path, sandbox_url}`; record `red_run.{thread_id,run_id}`. | `red_run`, `events_path` | start-call: 30s | On retry, **reuse `thread_id`** (idempotency key = `engagement_id`); if a run already active on the thread, attach not re-launch (multitask=`interrupt`). |
| **await_telemetry** | `red_run`, `window`, `budget` | Poll red run status **and** the settle timer. Red "done" = `engagement.end` in events.jsonl OR run status terminal. Then hold for a **settle window** (`REDBLUE_TELEMETRY_SETTLE_S`, default 120s) so late detections land. | `red_run.status`, `window.{t_end,settle_deadline}` | hard cap = `budget.max_wallclock_s` | Poll loop is idempotent; on coordinator restart the checkpointer resumes the poll; deadline is absolute wall-clock, not elapsed. |
| **collect_detections** | `engagement_id`, `window`, `events_path` | Pull **attacked** ground-truth (Neo4j KG + events.jsonl, §3.3) and **detected** (Vigil findings, §3.2) inside `[t_start, settle_deadline]`. | `attacks`, `detections` | 60s per source | Read-only; retried per-source with backoff; partial success tolerated (records source gaps in `errors`). |
| **score** | `attacks`, `detections`, `attack_catalog` | Correlate + compute metrics (§4). Write `scorecards` row (versioned) + evidence record (`scorecard.produced`). | `scorecard`, `evidence_head` | 30s | Deterministic given inputs; re-run overwrites same `(engagement_id, version)`. |
| **decide_response** | `scorecard`, `scope`, tenant policy | For each gap/detected-live-threat, propose a response action; run each through the **governance gate** (§2.6). Auto-tier → execute via Vigil; human-tier → `interrupt()`. | `pending_actions` | gate: 10s; HITL: `REDBLUE_APPROVAL_TTL_S` (default 1h) | Each action carries a deterministic `action_id`; re-entry after resume skips already-decided actions. |
| **report_evidence** | everything | Assemble the engagement report (scorecard + evidence chain refs + red chain-of-custody + blue chain-of-custody); seal evidence chain segment; emit `engagement.completed`. | `evidence_head` | 30s | Idempotent; report keyed by `(engagement_id, scorecard.version)`. |
| **watch_drift** (continuous) | `engagement_id`, `scope`, `budget` | Block on drift channel; on ChangeEvent build a CART `ReplayPlan` (§5), gate it (dry-run→HITL), set `red_objectives` = delta objectives, route back to `trigger_red`. | `red_objectives`, `drift_events` | idle (event-driven) | Debounce/rate-limit ChangeEvents (§5.3); each drift keyed by `ChangeEvent.resource_id`+revision. |

**Retry policy (shared, `connectors/*`):** `tenacity` exponential backoff (0.5s→8s, jitter), retry on
network + HTTP 5xx + 429; **never** retry 4xx (surface as node error). A node exhausting retries routes
to a **park** pseudo-state: writes an evidence `node.failed` record, sets engagement status `parked`,
and surfaces via `GET /engagements/{id}` — the loop does not silently die.

### 2.4 Edges (`loop/edges.py`)

```python
add_conditional_edges("score", route_after_score, {
    "respond": "decide_response",      # scorecard has actionable gaps / live threats
    "report":  "report_evidence",      # report-only (P4 default; no auto-response yet)
})
add_conditional_edges("decide_response", route_after_decide, {
    "await_human": END,                # interrupt() already parked the checkpoint; API resumes it
    "report":      "report_evidence",  # all actions auto-executed or none proposed
})
add_conditional_edges("report_evidence", route_after_report, {
    "continue": "watch_drift",         # mode == continuous
    "done":     END,                   # mode == on_demand
})
add_edge("watch_drift", "trigger_red") # a drift event re-enters the loop with delta objectives
```

### 2.5 Idempotency model (the three keys)

- **Engagement idempotency** = `thread_id` == `engagement_id`. The LangGraph checkpointer keys the whole
  loop on it; `POST /engagements` with an existing id is a no-op-or-attach, never a double-run.
- **Red-run idempotency** = Decepticon `thread_id` reused across `trigger_red` retries; the LangGraph
  Platform `interrupt` multitask strategy guarantees a second start on a live thread interrupts rather
  than forks.
- **Blue-ingest idempotency** = the canonical `finding_id = f-<YYYYMMDD>-<sha256_16>` (05/00 §7;
  `ID_HASH_WIDTH=16`) **plus** the authoritative `(data_source, external_id)` unique key; duplicate
  ingests are skipped by Vigil (`ingest_finding` de-dupes on both). The coordinator recomputes the same
  sha256 (and the same `external_id="<engagement_id>:<red_action_id>"`) from the same attack event, so
  replays don't inflate detection counts.

### 2.6 Where human-in-the-loop sits

Two interrupt points, both durable (parked checkpoint, resumed by API):

1. **`decide_response`** — the tiered-autonomy gate (§3.4, 08). `Never-auto` (tenant boundary / control
   plane) and `human-approval-gated` (isolate prod, kill proc, WAF/firewall, patch) actions call
   `interrupt()`. The coordinator **mirrors** the pending action into Vigil's approvals queue
   (`POST` a `requires_approval` action) so the SOC's existing approvals UI (a "ready HITL surface",
   vigil-architecture) is the human's screen; the coordinator resumes when either its own
   `POST /engagements/{id}/approve` or the mirrored Vigil approval fires.
2. **`watch_drift` → CART replay** — `ReplayRunner` defaults `dry_run=True` (verified in cart.py). The
   first replay of any engagement is **always** dry-run and requires a human `approve` before the runner
   flips to live (`dry_run=False`). This is the CART safety default, honored, not overridden.

---

## 3. Driving red & blue (concrete connector calls)

### 3.1 Red — drive Decepticon (`connectors/decepticon.py`)

Two interchangeable drive paths; the connector picks per `REDBLUE_RED_DRIVER`:

**(A) LangGraph Platform HTTP :2024 (default, verified surface).** Use the `langgraph-sdk` client:

```python
from langgraph_sdk import get_client
client = get_client(url="http://decepticon-langgraph:2024")   # 00 §4 host port 2024

async def start_red(engagement_id, workspace_path, sandbox_url, objectives):
    thread = await client.threads.create(thread_id=engagement_id,   # idempotency anchor (§2.5)
                                          if_exists="do_nothing")
    run = await client.runs.create(                                  # or runs.stream for live console
        thread["thread_id"], assistant_id="decepticon",             # the orchestrator graph
        input={"objectives": objectives},
        config={"configurable": {
            "engagement_name": engagement_id,                       # Neo4j partition key + RoE scope
            "workspace_path":  workspace_path,                      # where events.jsonl / FIND-*.md land
            "sandbox_url":     sandbox_url,                          # per-run Kali sandbox (multi-tenant fan-out)
        }},
        multitask_strategy="interrupt",
    )
    return {"thread_id": thread["thread_id"], "run_id": run["run_id"], "graph": "decepticon"}
```

The Decepticon orchestrator **builds an OPPLAN and waits for operator approval before any `task()`**
(decepticon-architecture). The coordinator is that operator: it auto-adjudicates the engagement-level
approval by writing Decepticon's HITL wire files (`approvals/decisions.jsonl` — `allow|deny|redirect`,
decepticon-safety-gates) **only within the pre-approved RoE**; anything outside RoE → `interrupt()` back
to a human. Poll progress by tailing `events_path` (`read_events`) and/or `client.runs.get(...)`.

**(B) `decepticon-driver` MCP tool (⟶06).** For a uniform tool surface the connector can instead call
the MCP `decepticon_*` tool that 06 defines. **Governance note (vigil-governance-gates):** the verbs
`launch`/`exploit`/`attack` are **not** in Vigil's `TOOL_TIERS`, so a decepticon-driver tool defaults to
auto-executable — **06 must register it `requires_approval`.** The coordinator refuses to load a
decepticon-driver tool that isn't tiered (fail-closed).

**Auth:** the LangGraph :2024 API uses Decepticon's own auth (`DECEPTICON_AUTH_*`); the connector sends
the configured platform token. No Vigil JWT here.

**Errors:** thread-create 409 → treat as existing (attach). Run-start 5xx → retry (reuse thread).
Sandbox unreachable → fail plan_engagement early with a clear "sandbox_url not provisioned" park.

### 3.2 Blue — drive Vigil (`connectors/vigil.py`)

Base URL `http://vigil-backend:6987`. Prefixes verified in `main.py`. Three call families:

```python
# 1. INGEST red attacks as canonical findings (push red→blue), so blue investigates for real.
#    Cleanest = the DecepticonIngestionService webhook (⟶06). Fast existing paths the connector uses today:
POST /api/integrations/vstrike/findings           # Bearer VSTRIKE_INBOUND_API_KEY (service auth exists here!)
POST /api/ingest/ingest-string  (Form: data=<finding-json>, format=json, data_type=finding)
POST /api/ingest/upload         (batch; poll GET /api/ingest/jobs/{job_id})

# 2. RUN a blue playbook / investigation against a finding (drive detection→response):
POST /api/workflows/{workflow_id}/execute   {"finding_id": "..."}         # 5 file playbooks = ONE-SHOT
POST /api/orchestrator/investigations       {"workflow_id","finding_ids","priority"}  # autonomous, phased

# 3. RESPONSE gate / HITL:
GET  /api/approvals/pending
POST /api/approvals/{action_id}/approve     {"approved_by":"redblue-coordinator"}
POST /api/approvals/{action_id}/reject      {"reason":"..."}

# 4. Evidence pull for the report:
GET  /api/orchestrator/investigations/{id}/chain-of-custody
```

**Which blue path when:** for a scored engagement the coordinator does **not** need to *run* blue — blue
runs autonomously via its daemon the moment findings land (vigil-architecture: store-first → background
triage → forks high-signal to responder + orchestrator). The coordinator's job is to **ingest red
ground-truth as findings** (family 1) and then **read** what blue independently detected (§3.3, §4).
Family 2 is used only for **on-demand deep-dive** (e.g. force a `full-investigation` on a specific gap)
and for eval reproducibility. **Honesty rule (redblue-strategic-moat):** never score blue on a finding
the coordinator *told* it about via a red self-report if that finding would let blue "detect" without the
sensor plane — the scored detection must originate from a **sensor** (04), not from our own ingest. So
family-1 ingest is tagged `data_source="decepticon"` and is **excluded from the detection numerator**;
it exists for correlation/context and blue-side enrichment, not for credit. (See §4.4.)

**Auth — the real gap (verified).** Families 2-4 sit behind `AUTH_DEPENDENCY` = cookie-JWT with
`DEV_MODE=true` bypass. The coordinator is server-to-server:

- **MVP / enclave (P4):** run Vigil with `DEV_MODE=true` inside the isolated enclave (vigil-architecture
  says this is acceptable in an isolated enclave, must be off before exposure).
- **Hardened (P5+):** `connectors/auth.py` mints/holds a **Vigil service JWT** (HS256, the same secret)
  for a `redblue-coordinator` service principal, sent as the auth cookie/header. **This requires a small
  Vigil patch (⟶06):** either a service-token issuer or extending the `vstrike` Bearer pattern to the
  workflows/orchestrator routers. Flagged as **C2** in §9.

**Errors:** ingest 413 (too large) → chunk to `/upload`. Workflow-execute 500 → surface, don't retry the
side-effecting call blindly (it may have partially run — check `GET /workflows/runs`). Approvals 404 →
the mirrored action was already resolved in Vigil; reconcile and continue.

### 3.3 Attacked ground-truth (`connectors/neo4j_kg.py` + events.jsonl)

The **attacked** set (denominator context, and the "what did red actually do" truth) comes from two
places, both engagement-scoped:

- **Decepticon Neo4j** (bolt :7687, 00 §5 = single source of truth). Engagement-scoped Cypher:
  `MATCH (n) WHERE n.engagement = $engagement RETURN n` — the KG already carries native purple node/edge
  kinds `DETECTION_FIRED` / `DEFENSE_ACTION` / `DETECTED` / `USES_RULE` (decepticon-architecture), so the
  coordinator can read *both* red actions and any blue-observed detections that made it into the graph.
  The coordinator reads via the same shape CART's `AttackGraphProtocol` uses (`revision()` for change,
  `snapshot()` to materialize) but for scoring it issues direct Cypher (cheaper, no in-engine call).
- **`events.jsonl`** (`read_events`) for the ordered, timestamped attack timeline — `tool.call`,
  `finding.created`, `opplan.update` events carry `ts` (epoch seconds) used for **attack timestamps** in
  MTTD. This is the authoritative red clock.

`⟶ 05` owns the exact KG node property names and the events.jsonl payload schema; §4 below assumes the
memory-level shape and marks the coupling.

### 3.4 Response execution + the governance gate (`governance/`)

`decide_response` builds candidate actions (e.g. `block_ip` the C2 IP a gap exposed, `isolate_host` a
popped box) and passes each to `governance/policy.py::evaluate_action(action, tenant)` which returns the
tiered-autonomy `Decision` (08 owns the policy engine; coordinator holds the thin client):

- **auto** (reversible, low blast-radius: enrich, ticket, time-boxed IP block w/ auto-expiry) → execute
  immediately through Vigil (map to Vigil `ActionType`, confidence ≥ 0.90 auto-path).
- **human-gated** (isolate prod, kill proc, WAF/firewall, patch) → `interrupt()` + mirror to Vigil
  approvals queue.
- **never-auto** (crosses a **tenant boundary** or touches the **control plane**) → hard refuse, evidence
  `action.blocked`, always human.

⚠ Two verified caveats the gate must encode: Vigil's `isolate_host` is still a **mock** (only Cloudflare
`waf_block`/`gateway_block`/`access_revoke` actually execute) — so `report_evidence` must label an action
**simulated vs real** (vigil-governance-gates). And Vigil's tool-tier list omits red verbs (§3.1).

---

## 4. The scoring engine (`scoring/`)

### 4.1 The correlation join (`correlate.py`)

Scoring is an **attacked-vs-detected diff**. `⟶ 05` is authoritative for the correlation keys; the
working key (from `redblue-integration-seams`) is:

```
correlate on:  engagement_id
        AND    mitre technique_id            (red: KG/opplan technique tag ; blue: finding.mitre_predictions keys)
        AND    entity                         (red: target host/IP ; blue: finding.entity_context.{src_ip,dst_ip,host})
        WITHIN a time window                  (blue.detection_ts ∈ [attack_ts, attack_ts + settle])
```

Produces, per (technique, entity) **attack instance**, a match state:

| Match state | Meaning |
|---|---|
| `detected` | ≥1 sensor-origin Vigil finding correlates (technique+entity+window). |
| `missed` | red attacked, no correlating finding → detection gap. |
| `sensor_blind` | no sensor covers this entity/technique at all (from the coverage oracle, §4.4) → **not** a blue miss. |
| `false_positive` | blue finding with no correlating red attack (only meaningful under held-out eval, redblue-strategic-moat). |

### 4.2 Metrics (`metrics.py`)

- **Per-technique detection rate** = `detected / (detected + missed)` — `sensor_blind` excluded from the
  denominator (you can't miss what you can't see; it's a *coverage* gap, reported separately).
- **MTTD** (mean time to detect) per attack instance = `first_correlating_detection_ts − attack_ts`;
  aggregated mean/median/p90 over the engagement. `attack_ts` from events.jsonl (red clock); detection ts
  from `finding.timestamp` (blue clock). ⚠ **Clock-skew risk** (§7): correlate on a common NTP source;
  where possible use the sensor's own event time, not Vigil ingest time.
- **MTTR** (mean time to respond/contain) = `containment_action.executed_at − first_detection_ts`, read
  from Vigil `approval_actions.executed_at` (the containment audit trail). Only counts **real** (non-mock)
  containment (§3.4 caveat).
- **ATT&CK coverage** = attacked techniques ∪ detected techniques over the ATT&CK matrix
  (`attack_catalog.py`): `attacked_coverage` (how much of the matrix red exercised),
  `detected_coverage` (how much blue caught), and the **gap set** = attacked − detected − sensor_blind.
- **Gap list** = ordered `missed` instances with severity, technique, entity, and the
  suggested sensor/rule that would have caught it (from KG `USES_RULE` where present).

### 4.3 Scorecard data model (`scorecard.py`)

```python
class TechniqueScore(BaseModel):
    technique_id: str            # e.g. T1071.001
    tactic: str                  # ATT&CK tactic
    attacked: int                # # attack instances red ran
    detected: int
    missed: int
    sensor_blind: int
    detection_rate: float | None # None when denominator == 0 (all sensor_blind)
    mttd_seconds: float | None   # mean over detected instances

class GapItem(BaseModel):
    technique_id: str
    entity: str
    severity: str
    first_attack_ts: float
    suggested_control: str | None   # rule/sensor that would have caught it (KG USES_RULE)

class Scorecard(BaseModel):
    scorecard_id: str            # sc-<engagement_id>-v<N>
    engagement_id: str
    tenant_id: str
    version: int                 # re-scored engagements (CART re-runs) bump this
    window: dict                 # {t_start, t_end}
    totals: dict                 # {attacked, detected, missed, sensor_blind}
    detection_rate_overall: float | None
    mttd: dict                   # {mean, median, p90}  seconds
    mttr: dict                   # {mean, median, p90}  seconds (real containments only)
    attack_coverage: dict        # {attacked_pct, detected_pct} of ATT&CK matrix
    per_technique: list[TechniqueScore]
    gaps: list[GapItem]
    evidence_refs: list[str]     # hash-chain ids proving each number (redblue-strategic-moat honesty gate)
    created_at: float
```

Every number carries `evidence_refs` back into the evidence chain — no metric ships without a
reproducible artifact / cited log line (the strategic-moat "hard verification gate").

### 4.4 The sensor-coverage oracle (honesty)

To distinguish `missed` (blue failed) from `sensor_blind` (no telemetry existed), `collect_detections`
consults a **coverage oracle**: which (entity, technique) pairs the sensor plane (04) actually observes.
MVP = a static map from the telemetry config (Wazuh/Suricata/Falco rule coverage). This is what keeps the
scorecard *honest* per the moat: an undetected attack on an uninstrumented host is a **coverage** finding,
not a blue **detection** failure — and both are reported, separately. `⟶ 04` owns the coverage source.

---

## 5. Continuous mode (CART-driven re-runs)

### 5.1 Who owns what (the verified seam)

`cart.py` is explicit: it **does not own the webhook receiver** ("an HTTP endpoint that lives on the
langgraph service"), it **does not write Neo4j**, it **does not gate actions**, and `ReplayRunner`
**defaults to dry-run**. So responsibilities split cleanly:

- **Coordinator (this doc):** hosts the drift **webhook receiver** `POST /engagements/{id}/drift`
  (§6), constructs a `ChangeEvent`, debounces/rate-limits, and gates the replay (dry-run→HITL→live).
- **Decepticon (⟶06 patch):** to actually *replay* with fidelity, `ReplayRunner`/`Watcher` need the
  compiled graph + a `Dispatcher` (`make_replay_dispatcher(invoke_agent)`), which only exist **in-engine**.
  06 must expose a thin `/cart/replay` HTTP surface on the langgraph service that wires
  `Watcher(ReplayRunner(...), prev_snapshot).handle_event(change_event)` and returns the `ReplayPlan`.
  The coordinator POSTs the `ChangeEvent` there and receives the plan to gate.

Two implementation options, recommend **A**:

- **A — in-engine replay (fidelity).** Coordinator → `/cart/replay` (06) → `ReplayRunner.plan()` returns
  the `ReplayPlan` (delta summary + `selected_objectives`); coordinator gates it; on approval →
  `ReplayRunner.execute(plan)` (live) reuses `ReplayMiddleware` for deterministic replay of the recorded
  chain. Preserves record/replay determinism.
- **B — coordinator-side re-trigger (fallback).** Coordinator polls KG `revision()`; on change it
  `diff_snapshots` itself and re-`trigger_red` with the affected objectives via §3.1. Simpler, no engine
  patch, but loses `ReplayMiddleware` determinism. Use only if A slips.

### 5.2 The continuous loop

```
drift feed (CloudTrail / K8s audit / Terraform apply / GH deploy)
      │  external event
      ▼
POST /engagements/{id}/drift  ──▶ build ChangeEvent(source,event_type,resource_id,resource_kind,
                                                     technique_tags, raw_payload, observed_at)
      │  debounce + rate-limit (§5.3)
      ▼
watch_drift node ──▶ [Option A] POST decepticon:/cart/replay(change_event)
                          └─▶ ReplayPlan{delta_summary, selected_objectives, dry_run=True}
      │  gate: FIRST replay always dry_run → interrupt() → human approve → dry_run=False
      ▼
set state.red_objectives = plan.selected_objectives  ──▶ re-enter trigger_red (§2.1)
      ▼
... await_telemetry → collect_detections → score (version += 1) → decide_response → report_evidence
      ▼
back to watch_drift  (posture is now continuously re-scored on infra drift)
```

### 5.3 Scheduling, concurrency, budget caps

- **On-demand vs continuous** is a per-engagement `mode` field. On-demand ends after one loop; continuous
  parks in `watch_drift`. A tenant may also schedule **periodic** re-runs (no drift needed) via
  `APScheduler` in `config/` — a cron that injects a synthetic ChangeEvent.
- **Debounce:** collapse ChangeEvents on the same `resource_id` within `REDBLUE_DRIFT_DEBOUNCE_S`
  (default 300s) — infra feeds are chatty; one Terraform apply is many events.
- **Concurrency caps:** `REDBLUE_MAX_CONCURRENT_ENGAGEMENTS` (per tenant) and a global
  `REDBLUE_MAX_CONCURRENT_RED_RUNS` (Decepticon Platform capacity). A semaphore in the graph gate;
  over-cap engagements queue (status `queued`).
- **Budget caps:** per-engagement `max_cost_usd` / `max_wallclock_s` (mirror Vigil's
  `ORCHESTRATOR_MAX_COST=5` / `MAX_HOURLY_COST=20`); CART `max_replays_per_hour` to stop a drift storm
  from burning budget. Exceeding a cap → engagement `parked` + evidence `budget.exceeded`.

---

## 6. Coordinator API (FastAPI, :8900) + store

### 6.1 Endpoints (`api/routes/`)

| Method + path | Body / query | Effect |
|---|---|---|
| `POST /api/engagements` | `{tenant_id, scope, mode, red_objectives?, budget?, roe_ref}` | Validate + create engagement; start the LangGraph loop on `thread_id=engagement_id`. Returns `{engagement_id, status}`. Idempotent (§2.5). |
| `POST /api/engagements/{id}/stop` | `{reason}` | Kill the loop: cancel Decepticon run (`client.runs.cancel`), `POST /api/orchestrator/kill` if blue deep-dive running, park checkpoint. |
| `GET /api/engagements` | `?tenant_id&status` | List engagements (from store). |
| `GET /api/engagements/{id}` | — | Status: current loop node, `red_run`, `window`, latest `scorecard.version`, `pending_actions`, parked?/errors. |
| `GET /api/engagements/{id}/scorecard` | `?version` | Latest (or versioned) `Scorecard` (§4.3). |
| `GET /api/engagements/{id}/detections` | — | The correlated attack-vs-detect table (match states, §4.1). |
| `GET /api/engagements/{id}/evidence` | `?verify=true` | Evidence chain records; `verify=true` re-checks the hash chain. |
| `POST /api/engagements/{id}/approve` | `{action_id, approved_by}` | Approve a parked `decide_response` action **or** a CART replay plan → **resumes the LangGraph interrupt** (`Command(resume=...)`). |
| `POST /api/engagements/{id}/reject` | `{action_id, reason}` | Reject → resume interrupt with denial. |
| `POST /api/engagements/{id}/drift` | `ChangeEvent` fields | Continuous-mode drift webhook (§5); feeds `watch_drift`. Service-auth guarded. |
| `GET /api/health` | — | Liveness + connector reachability (Decepticon :2024, Vigil :6987, Neo4j :7687, Ollama). |
| `GET /metrics` | — | Prometheus (exposed on **:8902**, 00 §4). |

Auth on `:8900`: a single `REDBLUE_SERVICE_TOKEN` bearer for machine callers (drift feeds, the console
proxy) via `api/deps.py`; human approvals go through the console which holds the token. Per-tenant scoping
is enforced in every route (`tenant_id` in path filters + policy).

### 6.2 The coordinator store (SQLite MVP → Postgres 16 + pgvector, 00 §5/§6)

LangGraph's checkpointer owns its own tables (loop state). The **application store** (`store/models.py`)
owns the durable business records:

```
tenants            (tenant_id PK, name, roe_defaults JSON, budget JSON,
                    force_manual_approval BOOL, created_at)
engagements        (engagement_id PK, tenant_id FK, mode, status,           -- status: planned|running|
                    scope JSON, budget JSON, roe_ref,                        --   awaiting_telemetry|scoring|
                    thread_id, created_at, updated_at)                       --   awaiting_human|parked|completed
engagement_runs    (run_id PK, engagement_id FK, engine ENUM(red,blue),
                    external_id,          -- Decepticon {thread_id/run_id} OR Vigil workflow_run_id/investigation_id
                    graph_or_workflow, status, cost_usd, started_at, ended_at)
drift_events       (drift_id PK, engagement_id FK, source, event_type,
                    resource_id, resource_kind, technique_tags JSON,
                    replay_plan_id, dry_run BOOL, observed_at)
correlations       (id PK, engagement_id FK, technique_id, entity,
                    attack_ts, detection_finding_id, detection_ts,
                    match_state ENUM(detected,missed,sensor_blind,false_positive))
scorecards         (scorecard_id PK, engagement_id FK, version,
                    totals JSON, detection_rate REAL, mttd JSON, mttr JSON,
                    attack_coverage JSON, per_technique JSON, gaps JSON,
                    evidence_refs JSON, created_at)     -- UNIQUE(engagement_id, version)
response_actions   (action_id PK, engagement_id FK, action_type, tier
                    ENUM(auto,human,never), status ENUM(proposed,pending,
                    approved,rejected,executed,blocked,simulated),
                    vigil_action_id,      -- mirrored Vigil approval_actions.action_id
                    approver, evidence_ref, created_at, executed_at)
evidence           (evidence_id PK, engagement_id FK, kind, payload_ref,
                    hash, prev_hash, created_at)        -- append-only hash chain; WORM spec ⟶08
```

`evidence` is the coordinator-side append-only, hash-chained log (`evidence/store.py`
`append()`/`verify_chain()`); **08 owns the WORM/tamper-evidence hardening** — here we pin the chain
shape and the `evidence_refs` linkage from every scorecard number.

---

## 7. Sequence diagrams, acceptance, risks

### 7.1 One full on-demand loop (P4)

```
Operator/Console   Coordinator(:8900)   LangGraph loop        Decepticon(:2024)   Sensors(04)   Vigil(:6987)   Neo4j(:7687)
      │  POST /engagements    │                │                     │                │             │             │
      │──────────────────────▶│  create thread=eng-id                                                             │
      │                       │───────────────▶│ plan_engagement                                                  │
      │                       │                │  assert RoE enforce+HITL; write engagements + evidence           │
      │                       │                │ trigger_red                                                       │
      │                       │                │──runs.create(configurable{engagement,workspace,sandbox})────────▶│
      │                       │                │                     │ attacks target range ─────▶│              │
      │                       │                │                     │                │ alerts ────▶│ (daemon      │
      │                       │                │                     │ writes events.jsonl + KG ───────────────────▶│
      │                       │                │ await_telemetry (poll run + settle window)          ingest+triage)│
      │                       │                │ collect_detections                                                │
      │                       │                │──read events.jsonl + Cypher(engagement=eng-id)──────────────────▶│
      │                       │                │──GET /api/findings (sensor-origin, in window)──────▶│             │
      │                       │                │ score → Scorecard v1 (rate/MTTD/MTTR/coverage/gaps) + evidence   │
      │                       │                │ decide_response → (P4: report-only) route→report                 │
      │                       │                │ report_evidence: seal chain, engagement.completed               │
      │  GET /scorecard       │◀───────────────│ END (mode=on_demand)                                             │
      │◀──────────────────────│ Scorecard v1 (+ evidence_refs)                                                    │
```

### 7.2 Continuous mode (P7)

```
Drift feed        Coordinator(:8900)     watch_drift        Decepticon /cart/replay(06)     ... loop ...
    │ CloudTrail/K8s/TF event  │              │                      │
    │──POST /engagements/{id}/drift──────────▶│ build ChangeEvent                             │
    │                          │ debounce/rate-limit                 │
    │                          │──────────────▶│ POST /cart/replay(change_event)              │
    │                          │               │─────────────────────▶│ ReplayRunner.plan()   │
    │                          │               │◀─ ReplayPlan{selected_objectives, dry_run=T} │
    │  (FIRST replay) interrupt→ human approve  │                      │
    │◀─ approve ───────────────│──Command(resume)─▶ set red_objectives=plan.objectives        │
    │                          │               │── re-enter trigger_red (live, dry_run=False)─▶│ replay chain
    │                          │               │  await_telemetry→collect→score (v+1)→report  │
    │                          │◀──────────────│  park back in watch_drift (await next drift) │
```

### 7.3 P4 / P7 acceptance criteria

**P4 — Coordinator MVP (00 §8: "one manual engagement → scored scorecard"):**
- `POST /api/engagements` for one tenant drives a real Decepticon engagement via :2024 with
  `configurable={engagement,workspace,sandbox}`.
- Red attacks the **sensor-instrumented target range** (04) — not only the isolated Kali sandbox
  (see risk R3); sensors alert; Vigil ingests them as findings independently of red's self-report.
- `collect_detections` correlates attacked (KG + events.jsonl) vs detected (sensor-origin Vigil findings);
  `score` produces a `Scorecard v1` with per-technique detection-rate, MTTD, ATT&CK coverage, and a gap
  list; `GET /engagements/{id}/scorecard` returns it.
- Every scorecard number has `evidence_refs` into a verifiable hash chain (`GET .../evidence?verify=true`).
- Loop survives a coordinator restart mid-engagement (checkpointer resumes).

**P7 — Continuous + UI (00 §8: "CART continuous mode; unified console"):**
- A `mode=continuous` engagement parks in `watch_drift`; a `POST /drift` ChangeEvent produces a CART
  `ReplayPlan`; first replay is dry-run + human-approved; live replay re-scores to `Scorecard v2`.
- Debounce, concurrency, and budget caps demonstrably hold under a drift burst.
- Posture (scorecards over time, gaps, MTTD/MTTR trend) renders in the unified console (09).

### 7.4 Risks

| # | Risk | Mitigation |
|---|---|---|
| **R1** | **Vigil service-auth gap** — workflows/orchestrator/ingest sit behind cookie-JWT/`DEV_MODE`; only vstrike has a service Bearer. | P4 runs `DEV_MODE=true` in the enclave; **06 must add a service-token path** (extend the vstrike Bearer pattern) before exposure (§3.2, C2). |
| **R2** | **CART needs in-engine graph/dispatcher** — `ReplayRunner`/`make_replay_dispatcher` can't run coordinator-side. | 06 exposes `/cart/replay` on the langgraph service (Option A); Option B fallback re-triggers via :2024. |
| **R3** | **Closed-loop honesty** — if red runs only in the isolated `sandbox-net` (never joined to `redblue-shared`, 00 §5), sensors never see it and MTTD is fiction. | Engagement scope MUST target the instrumented range; the **coverage oracle** (§4.4) separates `missed` from `sensor_blind`; family-1 red-ingest excluded from the detection numerator (§3.2). |
| **R4** | **Clock skew** inflates/deflates MTTD/MTTR (red clock = events.jsonl; blue clock = finding.timestamp). | Shared NTP; prefer sensor event-time over ingest-time; record both clocks in evidence. |
| **R5** | **Vigil `isolate_host` is a mock**; only Cloudflare actions execute. | `decide_response` labels actions **simulated vs real**; MTTR counts real containments only (§3.4, §4.2). |
| **R6** | **Safety gates off by default** — RoE `audit`, HITL disabled (decepticon-safety-gates). | `plan_engagement` refuses to start unless the tenant sets RoE `enforce` + `DECEPTICON_HITL__ENABLED` + budget; never-auto tier hard-refuses tenant/control-plane crossings (08). |
| **R7** | **One-shot file playbooks** — the 5 Vigil file playbooks run single-shot (no per-phase HITL). | Use `POST /orchestrator/investigations` (phased, cost-guarded) or DB-authored custom workflows when phase-level approval is needed. |
| **R8** | **Local-LLM latency** on both engines inflates MTTD/MTTR vs a cloud baseline. | Report model-inference latency separately in evidence; eval vs human baseline (09) uses the same sovereign stack. |
| **R9** | **Drift storm** burns budget via runaway replays. | Debounce + `max_replays_per_hour` + concurrency semaphore (§5.3). |

---

## 8. Build order (maps to 00 phases)

1. **P4a** `store/` + `config/` + `api/app.py` skeleton (health, create/get engagement) — no loop yet.
2. **P4b** `connectors/decepticon.py` (drive :2024) + `loop/` with `plan_engagement`+`trigger_red`+
   `await_telemetry`; checkpointer (SQLite).
3. **P4c** `connectors/neo4j_kg.py` + events.jsonl reader + `connectors/vigil.py` (ingest + findings read)
   → `collect_detections`.
4. **P4d** `scoring/` (correlate + metrics + scorecard) + `evidence/store.py` → `score`+`report_evidence`;
   **P4 acceptance met** (report-only, `decide_response` no-op).
5. **P5** `governance/` gate + real `decide_response` + HITL interrupt + Vigil approvals mirror (with 08).
6. **P7** `loop/nodes/watch_drift.py` + `api/routes/drift.py` + 06's `/cart/replay` → continuous mode;
   scheduler, caps; console wiring (09). **P7 acceptance met.**

---

## 9. Conflicts / deltas vs `00_MASTER_PLAN.md`

- **C1 (additive — needs a 00 §3 line).** 00 §3 lists the coordinator package as
  `loop/, connectors/, scoring/, governance/, evidence/, api/, config/`. Engagements/scorecards/
  correlations/evidence need an ORM home; this doc adds a **`store/`** subpackage (§1.3/§6.2). Proposing
  00 §3's list gain `store/`. (Alternatively fold into `config/db.py`, but a dedicated package is
  cleaner.) **Low-risk, flagged for a 00 edit.**
- **C2 (cross-doc dependency, not a contradiction).** Driving blue over the general REST
  (workflows/orchestrator/ingest) hits `AUTH_DEPENDENCY` (cookie-JWT / `DEV_MODE` bypass) — there is **no
  service-token path** except vstrike's Bearer. 00 §6 names "Vigil JWT / DEV_MODE"; this doc confirms that
  works for P4 in-enclave but **06 must ship a service-token issuer** before P5 exposure (§3.2, R1). No
  change to 00 needed; tracked as a 06 deliverable.
- **C3 (cross-doc dependency).** Continuous mode requires an in-engine `/cart/replay` HTTP surface on the
  Decepticon langgraph service, because `cart.py` deliberately does not own the receiver and `ReplayRunner`
  needs the in-process graph/dispatcher. This is new engine surface for **06's patch set** (§5.1, R2). 00
  §8 already scopes CART to P7; no 00 change, but 06/06-patchset must add it.
- **No port/naming/tech conflicts.** :8900 API + :8902 metrics, `redblue` package, `REDBLUE_` env,
  `eng-<tenant>-<YYYYMMDD>-<short>` id, Python 3.13/uv/LangGraph/FastAPI, SQLite→Postgres+pgvector — all
  conform to 00 §3/§4/§6/§7.
```
