# 06 — RED→BLUE Seams & Connectors (the engine glue + patch set)

> **Status:** Planning (pre-code). **Phase:** P3 (red→blue seam) → P4 (coordinator MVP).
> **Conforms to:** `00_MASTER_PLAN.md` (layout §3 additive-patch rule, port map §4, networks §5,
> naming §7, phasing §8). Deviations/conflicts are flagged in **§7 Conflicts with 00** at the end.
> **Depends on:** `05_DATA_CONTRACTS_AND_SCHEMAS.md` for the canonical finding/graph/event schemas.
> `05` is not yet written at authoring time, so the schemas below are pinned directly to code
> (cited `file:line`) and MUST be reconciled with `05` when it lands — `05` is authoritative on
> field names; this doc is authoritative on *wiring*.

This is the core integration document. It plans every concrete connector that turns two independent
engines — 🔴 **Decepticon** (`Decepticon/`, LangGraph :2024) and 🔵 **Vigil** (`vigil/`, FastAPI :6987) —
into a closed purple-team loop, plus the small tracked patch set each engine needs. Everything new
lives in `redblue-coordinator/` and is captured as an **additive** engine patch per `00 §3`.

---

## 0. Seam inventory & mechanism table

| # | Seam | Direction | Mechanism | New code lives in | Engine patch? |
|---|------|-----------|-----------|-------------------|---------------|
| 1 | **Findings connector** | red→blue | `DecepticonIngestionService(SIEMIngestionService)` + `/api/webhooks/decepticon/*` route (clone Darktrace) **or** coordinator pushes to `/api/ingest/ingest-string` | `vigil` (tracked patch) + `redblue-coordinator` (pusher) | additive file |
| 2 | **Shared attack graph** | blue reads red | Coordinator opens a **read-only** neo4j driver to Decepticon's engagement-scoped Neo4j (`MATCH (n) WHERE n.engagement=$e`) | `redblue-coordinator/connectors/kg_reader.py` | none |
| 3 | **Blue-reads-red event stream** | blue reads red | Tail Decepticon `engagements/<id>/events.jsonl` (`EventType` enum) as a live signal | `redblue-coordinator/connectors/event_tail.py` | none |
| 4 | **Drive Decepticon** | coordinator→red | LangGraph `:2024` `runs.stream` (`config.configurable`) **and** a Vigil MCP `decepticon-driver` tool (gated `requires_approval`) | `redblue-coordinator/connectors/red_driver.py` + `vigil/tools/decepticon_driver.py` | additive MCP + `tool_manager` patch |
| 5a | **Patch: `isolate_host`** | — | Implement `AutonomousResponseService._execute_isolation` (real EDR/MCP) instead of the mock | `vigil` (tracked patch) | in-place patch |
| 5b | **Patch: offensive verbs** | — | Add red-driver verbs/tool-names to `TOOL_TIERS` + `_ACTION_VERB_TOKENS` | `vigil` (tracked patch) | in-place patch |
| 5c | **Patch: KG vuln-research** | — | **Bridge** (not restore) Decepticon's disabled KG pipeline via a coordinator KG reader + blue_cell trigger | `redblue-coordinator` (additive) | additive (see §7 conflict) |
| 5d | **Patch: RoE+HITL on** | — | Per-tenant `roe.json` `machine_enforcement=enforce` + `DECEPTICON_HITL__ENABLED=1` + auto-adjudication | config/workspace (no code) | config-only |

**No new host port is claimed** by any seam in this doc — connectors ride Vigil `:6987`, the coordinator
`:8900`, and Decepticon `:2024`/`:7687` from `00 §4`. Seam 3 and 5d require a **shared volume** onto
Decepticon's engagement workspace (see `02`); that mount contract is specified in §3.3 / §5.4.

---

## 1. Findings connector (red → blue)

### 1.1 Canonical target schema (pinned to code)

Every red finding must become a Vigil **canonical finding**. The persisted columns are the ORM
`Finding` (`vigil/database/models.py:62-145`) and the create signature is
`vigil/database/service.py:49-98`:

```
finding_id (PK, str≤50) · embedding vector(768) · mitre_predictions JSONB(nonnull)
· anomaly_score float · timestamp · data_source · external_id · description
· entity_context JSONB · evidence_links JSONB · cluster_id · severity · status(default "new")
· ai_enrichment JSONB (blue writes later)
```

Two idempotency layers to exploit:
1. **`finding_id`** — deterministic `f-<YYYYMMDD>-<sha256[:16]>` (matches the corrected `00 §7`/`05`;
   `ID_HASH_WIDTH=16`, `vigil/services/ingestion_service.py:40` — the 8-hex SHA1 form was abandoned as
   collision-prone), so the same red event replays to the same id and `IngestionService.ingest_finding`
   skips the duplicate (`vigil/services/ingestion_service.py:207-213`).
2. **`uniq_findings_source_extid`** — a partial UNIQUE index on `(data_source, external_id)`
   (`vigil/database/models.py:136-144`). Set `external_id = "<engagement_id>:<red_action_id>"` (the
   engagement slug + the Decepticon-native `FIND-*` id / `events.jsonl` payload key) and
   `data_source="decepticon"`. **This `(data_source, external_id)` pair is the authoritative idempotency
   key** — it is what actually dedupes, and it survives even a `finding_id` hashing change.

⚠️ **Schema-drift trap** (`redblue-integration-gotchas`): `ingest_finding` only forwards the 13
canonical fields (`ingestion_service.py:219-233`). Put IPs/hosts/creds in **`entity_context`**,
techniques in **`mitre_predictions`** (`{"T1071.001": 0.7, ...}`), and back-links in
**`evidence_links`**. Anything else is dropped.

### 1.2 The pattern to clone

`vigil/services/darktrace_ingestion.py` (a `SIEMIngestionService` subclass, base at
`vigil/services/siem_ingestion_service.py:17`) + its webhook `vigil/backend/api/darktrace_webhook.py`
are the exact template. Note the reusable helpers there:
- `_finding_id(prefix, stable_key, ts)` (`darktrace_ingestion.py:28-35`) is the shape to clone, **but
  widen it to `f-<YYYYMMDD>-<sha256[:16]>`** (`ID_HASH_WIDTH=16`, `ingestion_service.py:40`) to match the
  corrected canonical id in `00 §7`/`05` — the Darktrace helper's own 8-hex SHA1 form was abandoned as
  collision-prone.
- Deterministic **SHA-1** fallback over sorted JSON, *not* `hash()`, to survive worker restarts
  (`darktrace_ingestion.py:242-247`).
- HMAC-SHA256 body verification, fail-closed when no secret, body-size cap
  (`darktrace_webhook.py:77-108`), `asyncio.to_thread` around the sync `ingest_finding`
  (`darktrace_webhook.py:179-184`).

### 1.3 New file — `vigil/services/decepticon_ingestion.py`

```python
# vigil/services/decepticon_ingestion.py   (ADDITIVE — tracked patch, per 00 §3)
"""Transform Decepticon findings/events into Vigil canonical findings."""
import hashlib, json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from services.siem_ingestion_service import SIEMIngestionService

DATA_SOURCE = "decepticon"
DEFAULT_EMBEDDING_DIM = 768

ID_HASH_WIDTH = 16   # matches vigil ingestion_service.py:40 — 8-hex SHA1 abandoned as collision-prone
def _finding_id(stable_key: str, ts: datetime) -> str:            # widened clone of darktrace helper
    digest = hashlib.sha256(f"decepticon:{stable_key}".encode()).hexdigest()[:ID_HASH_WIDTH]
    return f"f-{ts.strftime('%Y%m%d')}-{digest}"

class DecepticonIngestionService(SIEMIngestionService):
    def __init__(self):
        super().__init__()
        self.siem_name = "Decepticon"

    async def fetch_alerts(self, *a, **k) -> List[Dict[str, Any]]:  # push-only; no polling
        return []

    def transform_alert_to_finding(self, alert: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        # dispatch by payload kind: "finding" (FIND-*.md JSON) | "event" (events.jsonl line)
        kind = alert.get("kind")
        if kind == "finding":
            return self._transform_finding(alert)
        if kind == "event":
            return self._transform_event(alert)
        return self._transform_finding(alert)  # default: treat as a FIND-* record

    def _transform_finding(self, a: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        native_id = a.get("finding_id") or a.get("id")   # FIND-<...> from the workspace
        if not native_id:
            return None
        ts = _parse_ts(a.get("timestamp"))
        engagement = a.get("engagement") or a.get("engagement_name")
        score = _sev_to_anomaly(a.get("severity"))
        return {
            "finding_id": _finding_id(f"{engagement}:{native_id}", ts),
            "external_id": f"{engagement}:{native_id}",   # THE dedup key: (data_source, external_id) UNIQUE
            "embedding": [0.0] * DEFAULT_EMBEDDING_DIM,   # LogLM re-embeds later if desired
            "mitre_predictions": _mitre_map(a.get("techniques") or a.get("mitre")),
            "anomaly_score": score,
            "timestamp": ts.isoformat(),
            "data_source": DATA_SOURCE,
            "description": a.get("title") or a.get("summary") or "Decepticon finding",
            "entity_context": _entity_context(a, engagement),   # SEE the rules below
            "evidence_links": _evidence_links(a),
            "severity": (a.get("severity") or "medium").lower(),
            "status": "new",
        }
```

**`entity_context` / `mitre_predictions` rules to avoid the drift trap** (the crux of this seam):

```python
def _entity_context(a: Dict[str, Any], engagement: str) -> Dict[str, Any]:
    ctx: Dict[str, Any] = {"engagement": engagement, "red_source": "decepticon"}
    # IPs/hosts/creds live HERE, never as top-level finding fields.
    for k_src, k_dst in (("target_ip","src_ip"), ("host","hostname"),
                         ("dst_ip","dst_ip"), ("user","username")):
        if a.get(k_src): ctx[k_dst] = a[k_src]
    # KG cross-reference so blue can jump to the shared graph (§2):
    if a.get("kg_node_key"): ctx["kg_node_key"] = a["kg_node_key"]      # e.g. "Host::10.0.0.5"
    if a.get("attack_path"): ctx["attack_path"] = a["attack_path"]      # ordered node keys
    return ctx

def _mitre_map(techniques) -> Dict[str, float]:
    # Decepticon emits technique IDs (T1071.001, ...). Default 0.7 confidence; red is ground truth
    # so a red-attributed technique is high-confidence but NOT self-scored 1.0 (leave room for
    # blue's own mitre_analyst). Keep only well-formed MITRE IDs.
    out: Dict[str, float] = {}
    for t in (techniques or []):
        tid = t.get("id") if isinstance(t, dict) else t
        if isinstance(tid, str) and tid.startswith("T") and tid[1:].split(".")[0].isdigit():
            out[tid] = float((t.get("confidence") if isinstance(t, dict) else None) or 0.7)
    return out
```

> **Design rule (anti-drift):** red is *ground truth of what was attacked*, but it must NOT poison
> blue's *detection* metric. So the connector sets `anomaly_score` from red severity but leaves
> `ai_enrichment` empty — blue's daemon re-triages and only *its* verdict counts toward
> detection-rate/MTTD in the scorecard (`07`). The `entity_context.red_source="decepticon"` tag lets
> the coordinator exclude red-origin findings from the "independently detected" numerator.

### 1.4 New webhook route — `vigil/backend/api/decepticon_webhook.py`

Clone `darktrace_webhook.py` structure, gated off-by-default exactly like Cloudflare Cloudy
(`vigil/backend/api/cloudflare_webhooks.py:34-55` + mount at `vigil/backend/main.py:456`).

```python
# vigil/backend/api/decepticon_webhook.py   (ADDITIVE)
router = APIRouter()
_SIG_HEADER = "X-Decepticon-Signature"                 # hex HMAC-SHA256 of raw body
# secret via secrets_manager("DECEPTICON_WEBHOOK_SECRET") → env fallback (clone darktrace _get_secret)

@router.get("/health")
async def health(): return {"status": "ok", "receiver": "decepticon",
                            "secret_configured": _get_secret() is not None}

@router.post("/findings", status_code=202)             # batch or single FIND-* records
async def findings(request: Request,
                   sig: Optional[str] = Header(default=None, alias=_SIG_HEADER)):
    raw = await _read_and_verify(request, sig)          # clone darktrace _read_and_verify (HMAC+size)
    payload = _parse_json(raw)
    return await asyncio.to_thread(_ingest_batch, payload)

@router.post("/events", status_code=202)               # forwarded events.jsonl lines (optional)
async def events(request: Request, sig=Header(default=None, alias=_SIG_HEADER)):
    ...

def _ingest_batch(payload) -> Dict:
    svc = DecepticonIngestionService()
    items = payload if isinstance(payload, list) else payload.get("findings", [payload])
    accepted = []
    for item in items:
        f = svc.transform_alert_to_finding(item)
        if f and svc.ingestion_service.ingest_finding(f):
            accepted.append(f["finding_id"])
    return {"accepted": len(accepted), "finding_ids": accepted}
```

**Mount** — patch `vigil/backend/main.py` (mirror the Darktrace block at `main.py:441-449`):

```python
from api.decepticon_webhook import router as decepticon_webhook_router
if os.environ.get("DECEPTICON_INGESTION_ENABLED", "false").lower() == "true":
    app.include_router(decepticon_webhook_router,
                       prefix=f"{_CONTEXT_PATH}/api/webhooks/decepticon", tags=["decepticon"])
```
Add `/api/webhooks/decepticon/*` semantics like the other inbound webhooks (own HMAC dependency; the
route-auth test `tests/security/test_route_auth_coverage.py` expects either `AUTH_DEPENDENCY` or a
`PUBLIC_API_PATHS` entry — add the receiver paths there, `main.py:120-135`). New env vars in
`env.example`: `DECEPTICON_INGESTION_ENABLED`, `DECEPTICON_WEBHOOK_SECRET`, `DECEPTICON_WEBHOOK_MAX_BODY_KB`.

### 1.5 Coordinator-push alternatives (no Vigil patch)

For the P4 MVP where you don't yet want to patch Vigil, the coordinator can push findings to
**existing** endpoints (still map to the canonical shape first, per §1.1):

- **`POST /api/ingest/ingest-string`** (form-encoded `data`=JSON, `format=json`, `data_type=finding`) —
  `vigil/backend/api/ingestion.py:159-180`. Accepts a single canonical finding dict or a list. This is
  the cleanest zero-patch path; it still runs the same `ingest_finding` dedup.
- **`POST /api/ingest/upload`** (multipart file, background job) — `ingestion.py:103-141` for batch
  JSONL of many findings.
- **`POST /api/integrations/vstrike/findings`** (Bearer `VSTRIKE_INBOUND_API_KEY`) —
  `vigil/backend/api/vstrike.py:130-282`. ⚠️ **Not recommended for net-new red findings**: it is
  *update-biased* — it merges enrichment into `entity_context["vstrike"]` for an existing finding and
  only *creates* with `data_source="vstrike"` (wrong provenance) when `timestamp`+`anomaly_score` are
  present (`vstrike.py:196-226`). Use it only if red output should *enrich* an existing blue finding.

**Recommendation:** dedicated webhook (§1.4) for production (HMAC, gated, correct `data_source`);
`ingest-string` for the P4 MVP. Kafka topic (Vigil's `KAFKA_*` connector, `env.example:567-582`) is the
right choice only once red runs continuously (P7/CART).

### 1.6 Acceptance test (P3)

Mirror `vigil/tests/unit/test_darktrace_webhook.py` (HMAC sign + `TestClient`):

```python
def test_decepticon_finding_ingests_idempotently(client):
    payload = {"kind":"finding","finding_id":"FIND-0007","engagement":"eng-acme-20260805-x1",
               "timestamp":"2026-08-05T10:00:00Z","severity":"high",
               "techniques":[{"id":"T1190","confidence":0.9}],
               "target_ip":"10.10.0.5","kg_node_key":"Host::10.10.0.5"}
    r1 = _post(client, "/api/webhooks/decepticon/findings", payload)   # signed
    assert r1.status_code == 202 and r1.json()["accepted"] == 1
    fid = r1.json()["finding_ids"][0]
    r2 = _post(client, "/api/webhooks/decepticon/findings", payload)   # replay
    assert r2.json()["accepted"] in (0, 1)                             # dedup, no new row
    # DB assert: exactly one finding_id == fid, data_source=="decepticon",
    # entity_context["src_ip"]=="10.10.0.5", mitre_predictions=={"T1190":0.9}
```
Pass criteria: `data_source="decepticon"`, technique in `mitre_predictions`, IP in `entity_context`,
replay does not create a second row (both `finding_id` and `(data_source, external_id)` dedup).

---

## 2. Shared attack graph bridge (blue reads red Neo4j)

### 2.1 Decision (conforms to `00 §5`)

Decepticon's **engagement-scoped Neo4j** (`:7687`) is the single source of truth. Vigil's own
`graph_builder_service` is ephemeral/in-memory (`vigil-architecture`), so **do not build a third graph** —
the coordinator reads red's KG directly. The node/edge vocabulary is already purple-native
(`Decepticon/packages/decepticon-core/decepticon_core/types/kg.py`): `NodeKind.DETECTION_FIRED`
(`kg.py:87`), `DEFENSE_ACTION` (`kg.py:88`), plus edges `DETECTED` (`kg.py:170`) and `USES_RULE`
(`kg.py:171`). Attack-surface `Technology` nodes fingerprint Ollama/vLLM/LiteLLM (`kg.py:122`,
`TechnologyCategory` `kg.py:259-278`).

### 2.2 Read path & scope safety

Every scoped query MUST bind `$engagement` — Decepticon's own `KGStore._check_scoped_cypher` enforces
this on its side (`Decepticon/.../middleware/kg_internal/store.py:182-187`), and the coordinator reader
follows the same rule so a read can never span tenants:

```python
# redblue-coordinator/redblue/connectors/kg_reader.py   (NEW, additive — coordinator owns this)
import neo4j
class RedKGReader:
    """Read-only view of Decepticon's Neo4j, engagement-scoped."""
    def __init__(self, uri, user, password, database="neo4j"):
        self._driver = neo4j.GraphDatabase.driver(uri, auth=(user, password))  # READ-ONLY neo4j role
        self._db = database

    def _read(self, cypher: str, engagement: str, **params):
        assert "$engagement" in cypher, "every KG read must be engagement-scoped"
        with self._driver.session(database=self._db, default_access_mode=neo4j.READ_ACCESS) as s:
            return s.execute_read(lambda tx: [dict(r) for r in tx.run(cypher, engagement=engagement, **params)])

    def attacked_surface(self, engagement: str):
        # what red actually touched: Findings + the Hosts/Services they hang off
        return self._read(
            "MATCH (f:Finding) WHERE f.engagement=$engagement "
            "OPTIONAL MATCH (f)<-[:REACHES|LEADS_TO*0..2]-(h:Host) "
            "RETURN f.key AS finding, f.label AS label, collect(DISTINCT h.key) AS hosts",
            engagement)

    def detection_coverage(self, engagement: str):
        # blue_cell ground truth: DetectionFired -[:DETECTED]-> Finding/Technique, -[:USES_RULE]-> rule
        return self._read(
            "MATCH (d:DetectionFired)-[:DETECTED]->(t) WHERE d.engagement=$engagement "
            "OPTIONAL MATCH (d)-[:USES_RULE]->(a:DefenseAction) "
            "RETURN t.key AS caught, d.key AS detection, a.label AS rule", engagement)

    def detection_gaps(self, engagement: str):
        # Findings with NO inbound DETECTED edge = what red did that nothing caught
        return self._read(
            "MATCH (f:Finding) WHERE f.engagement=$engagement "
            "AND NOT (f)<-[:DETECTED]-(:DetectionFired) RETURN f.key AS undetected", engagement)
```

**Credentials:** create a dedicated **read-only Neo4j role** for the coordinator (Neo4j server config,
tracked in `02`/`telemetry`). The coordinator env vars follow the `REDBLUE_` prefix (`00 §7`):
`REDBLUE_DECEPTICON_NEO4J_URI` / `_USER` / `_PASSWORD` / `_DATABASE`. (Decepticon's own writer reads the
un-prefixed `DECEPTICON_NEO4J_*`, `store.py:68-84` — keep the two credential sets distinct so a
compromised coordinator token cannot write the graph.)

### 2.3 How the coordinator consumes DETECTION_FIRED / DEFENSE_ACTION

- **Scorecard (P4):** `detection_coverage()` vs `attacked_surface()` → detection-rate; join
  `DetectionFired.firstseen`−`Finding.firstseen` (both written by blue_cell/KGStore provenance,
  `store.py:344-347`) → **MTTD** on the red-graph side. Cross-check against Vigil's own
  `findings`/`approval_actions` for the blue-side MTTD (`07`).
- **DEFENSE_ACTION** nodes are the rule artifacts blue_cell proposes for each gap; the coordinator
  surfaces them as "recommended detections" in the scorecard.

### 2.4 Annotate-back? — **No (v1).** Keep the read read-only.

Writing blue verdicts back into red's Neo4j would (a) require a write role that violates the isolation
in §2.2 and (b) collide with Decepticon's `KGStore` provenance-injection + the *disabled*
`graph_transaction` write path (§5.3). Instead, the coordinator holds the join in **its own store**
(`00 §5`: SQLite→Postgres) keyed by `(engagement, kg_node_key)` — the `entity_context.kg_node_key` the
connector stamped in §1.3 is the bridge back. Revisit write-back only after §5.3's KG redesign lands.

### 2.5 Acceptance test (P3)

Against a seeded engagement Neo4j (docker `neo4j:5` with a fixture graph):
`RedKGReader.detection_gaps("eng-test-...")` returns exactly the Finding keys with no `DETECTED` edge;
a query missing `$engagement` raises `AssertionError`; the read role cannot run a write
(`CREATE (:X)` → `neo4j.exceptions.Forbidden`).

---

## 3. Blue-reads-red event stream (tail `events.jsonl`)

### 3.1 The signal

Decepticon writes an append-only, file-locked `events.jsonl` per engagement
(`Decepticon/packages/decepticon/decepticon/runtime/event_log.py`). Path is
`engagements/<id>/events.jsonl` (`event_log.py:154-155`) or, via `EventLog.for_workspace`,
`<workspace_dir>/events.jsonl` (`event_log.py:205-218`). The `EventType` enum (`event_log.py:87-99`)
is the dispatch key:

```
engagement.start · engagement.end · engagement.checkpoint · agent.turn
· tool.call · tool.result · llm.call · llm.response · finding.created · opplan.update
```

Each line is `{"ts": float, "type": str, "agent": str?, "payload": {...}}`
(`EngagementEvent`, `event_log.py:102-130`). `read_events(path)` yields in order and **skips torn/
malformed lines** (`event_log.py:275-288`) — safe to tail a file being actively written.

### 3.2 Reader design — `redblue-coordinator/.../connectors/event_tail.py`

A follow-the-file tailer (offset-checkpointed, so a coordinator restart resumes; append-only + the
writer's fsync-under-lock make this race-free):

```python
# redblue-coordinator/redblue/connectors/event_tail.py   (NEW, additive)
import json, time
from pathlib import Path

FINDING = "finding.created"; ENG_END = "engagement.end"; TOOL_CALL = "tool.call"

class EventTail:
    def __init__(self, events_path: str, from_offset: int = 0):
        self._path = Path(events_path); self._offset = from_offset

    def poll(self):
        """Yield new EngagementEvent-shaped dicts since last poll; advance checkpoint."""
        if not self._path.exists(): return
        with self._path.open("rb") as fh:
            fh.seek(self._offset)
            for raw in fh:
                if not raw.endswith(b"\n"): break          # torn final line: wait for next poll
                self._offset = fh.tell()
                try: yield json.loads(raw)
                except ValueError: continue                # mirror read_events tolerance

    async def run(self, on_event, interval=1.0):
        while True:
            for ev in self.poll(): await on_event(ev)
            await asyncio.sleep(interval)
```

### 3.3 Wiring & use

- **Live push to blue:** on `finding.created`, the coordinator forwards the payload to the §1 webhook
  (`kind="finding"`) — this is the *low-latency* red→blue path; the workspace `FIND-*.md` scrape is the
  *durable* reconciliation path. On `engagement.end`, the coordinator closes the scorecard and flips
  the loop to scoring (`07`).
- **Mount contract:** the coordinator container mounts Decepticon's engagement workspace **read-only**
  for `events.jsonl` + `findings/FIND-*.md` (write access is only needed for §5.4's `approvals/` and
  `plan/roe.json`). Declared in `deploy/docker-compose.redblue.yml` (`02`) as a named volume shared
  between the `langgraph` and `redblue-coordinator` services on `redblue-shared`.
- **Alternative (no shared volume):** patch Decepticon's `EventLog.append` to also POST to the
  coordinator — rejected for v1 (violates `00 §3` additive rule; the file tail is zero-touch).

### 3.4 Acceptance test (P3)

Write a synthetic `events.jsonl` with 3 lines incl. a torn final line; `EventTail.poll()` yields the 2
complete events and holds the torn one until it's completed on the next write; the `finding.created`
event triggers exactly one webhook POST (assert via a stub ingest endpoint).

---

## 4. Driving Decepticon from the coordinator

Two mechanisms, both used: (A) the coordinator's own LangGraph SDK driver for the closed loop; (B) a
Vigil MCP `decepticon-driver` tool so a blue agent/operator can launch red from the SOC console — the
one that **must** be gated.

### 4.1 (A) Coordinator → LangGraph `:2024` via `runs.stream`

The engines are LangGraph-native; the canonical driving pattern is `langgraph_sdk.get_client(...).runs.stream(...)`
with `config.configurable`. Verified call shapes in-repo:

- **Background run (MCP bridge):** `Decepticon/.../mcp_server/engagements.py:135-147` —
  `client.threads.create()` then `client.runs.create(thread_id, assistant_id=assistant, input=..., config={"configurable":{"engagement_name":...,"scan_mode":...}})`.
- **Streaming run (headless CLI):** `Decepticon/.../cli/scan.py:227-270` —
  `client.runs.stream(thread["thread_id"], assistant_id=assistant, input=state_input, config=config, stream_mode=["values","updates","custom"])`.
- **Richest configurable (benchmark):** `Decepticon/benchmark/dreadgoad/harness.py:366-408` — the shape
  to copy for a real engagement:

```python
config={"configurable":{
    "engagement_name": scenario.name, "engagement_id": scenario.name, "org_id": "<tenant>",
    "workspace_path": f"/workspace/{scenario.name}",
    "target_url": ..., "target_domain": ..., "target_creds": ...,
    "sandbox_url": ..., "sandbox_token": ...,        # per-run sandbox fan-out
}}
```

Server-side, `configurable.sandbox_url`/`sandbox_token` are resolved **per-run** in
`Decepticon/.../backends/factory.py:48-52` (the multi-tenant fan-out hook); `workspace_path` in
`middleware/filesystem.py:283-284` + `middleware/engagement.py:152,190`; `engagement_name` in
`decepticon_core/utils/engagement_scope.py` (env `DECEPTICON_ENGAGEMENT` fallback, `:68`).

```python
# redblue-coordinator/redblue/connectors/red_driver.py   (NEW, additive)
from langgraph_sdk import get_client

class RedDriver:
    def __init__(self, url="http://langgraph:2024"):        # 00 §4 host :2024
        self._client = get_client(url=url)

    async def launch(self, *, engagement: str, workspace: str, sandbox_url: str,
                     sandbox_token: str, tenant: str, assistant="decepticon",
                     operator_instruction: str, target: dict):
        assert _valid_engagement(engagement)                # 00 §7 regex (see §5.4)
        thread = await self._client.threads.create()
        run_id = None
        async for chunk in self._client.runs.stream(
            thread["thread_id"], assistant_id=assistant,
            input={"messages":[{"role":"user","content":operator_instruction}],
                   "engagement_name": engagement},
            config={"configurable":{
                "engagement_name": engagement, "engagement_id": engagement, "org_id": tenant,
                "workspace_path": workspace, "sandbox_url": sandbox_url,
                "sandbox_token": sandbox_token, **target}},
            stream_mode=["values","updates","custom"]):
            # bridge chunk.event/chunk.data into the coordinator's evidence store + scorecard
            ...
        return thread["thread_id"]
```

Config knobs (all default to `http://localhost:2024`): env var is `DECEPTICON_API_URL` in the Python/TS
clients (`mcp_server/config.py:15,37,88`) or `LANGGRAPH_API_URL` in the web layer; the coordinator uses
`REDBLUE_LANGGRAPH_URL` (`00 §7` prefix). `orchestrator=decepticon` waits for operator approval before
any `task()` (`decepticon-architecture`) — the coordinator's approval is written via §5.4's HITL wire.

### 4.2 (B) Vigil MCP `decepticon-driver` tool (the gated surface)

So a blue operator/agent can start a scoped red engagement from the SOC console, add a new MCP server to
Vigil (loaded by `MCPService` from `mcp-config.json`, `vigil/services/mcp_service.py:340-491`):

```python
# vigil/tools/decepticon_driver.py   (NEW MCP server, additive)
# Tool NAMES deliberately carry a destructive verb token so the verb-floor gates them (see 4.3):
#   red_launch_engagement(engagement, targets, scan_mode, tenant) -> {thread_id}
#   red_exploit_target(engagement, target)     # explicit exploit dispatch
#   red_stop_engagement(engagement, thread_id) # cancel (runs.cancel)
# Each wraps langgraph_sdk get_client(REDBLUE_LANGGRAPH_URL).runs.create/stream/cancel,
# forcing config.configurable.engagement_name to a coordinator-validated, tenant-scoped slug.
```

Register in `vigil/mcp-config.json` (`mcpServers` block, same shape as the `vstrike`/`cloudflare`
entries at `mcp-config.json:270-354`):

```json
"decepticon-driver": {
  "command": "python3", "args": ["tools/decepticon_driver.py"], "cwd": "${workspaceFolder}",
  "env": { "REDBLUE_LANGGRAPH_URL": "${REDBLUE_LANGGRAPH_URL}",
           "DECEPTICON_DRIVER_TOKEN": "${DECEPTICON_DRIVER_TOKEN}" }
}
```
It defaults **disabled** (not in `MCPService._DEFAULT_ENABLED`, `mcp_service.py:260`) — must be toggled
on explicitly, and only the daemon/agents that should ever drive red get it in their
`recommended_tools`.

### 4.3 CRITICAL — gate the driver in `tool_manager` (else it auto-executes)

Vigil's tool-tier gate is **verb-blind to `launch`/`exploit`/`attack`** (`vigil-governance-gates`):
`get_tool_tier` does exact-name → post-first-underscore suffix → destructive-verb floor `_has_action_verb`
→ else `"unknown"` (auto-executable) (`vigil/services/tool_manager.py:212-232`). The verb set
`_ACTION_VERB_TOKENS` (`tool_manager.py:151-178`) has isolate/block/quarantine/... but **not**
launch/exploit/attack/engage. An MCP tool arrives double-prefixed (`decepticon-driver_red_launch_engagement`);
neither the exact nor the suffix lookup reaches a generic tier name, so **without a patch it resolves to
`unknown` and the daemon runs it with no approval** (`daemon/agent_runner.py:1203,1255-1269`;
`openai_agent_service.py:557-565`).

**Patch `vigil/services/tool_manager.py` (ADDITIVE — belt-and-suspenders, both levers):**

```python
# 1) add offensive verbs to the destructive-verb floor (tool_manager.py:151)
_ACTION_VERB_TOKENS = frozenset({ ...existing...,
    "launch", "exploit", "attack", "engage", "detonate", "pwn", "c2", "beacon",
})
# 2) name the driver tools explicitly in the requires_approval tier (tool_manager.py:123)
"requires_approval": [ "isolate_host","block_ip","disable_user","quarantine_file","close_case",
    "red_launch_engagement", "red_exploit_target", "red_stop_engagement",
    "decepticon_start_engagement", "decepticon_send_message",     # if the MCP names differ
],
```

Because tool names carry `launch`/`exploit`, `_has_action_verb("decepticon-driver_red_launch_engagement")`
tokenizes to `{decepticon, driver, red, launch, engagement}` → `launch` matches → `requires_approval`,
even for a driver name the explicit list missed. **Do NOT** put the driver under `_UNGATED_PREFIXES`
(`mempalace_`/`skill_`, `tool_manager.py:209`). Confirm it never lands in `"safe"`/`"managed"`.

> Governance layering (`08`): the tier gate is the *first* choke point; the 0.90 confidence gate
> (`approval_service.create_action`, `vigil-governance-gates`) and per-tenant `force_manual_approval`
> are the second. A red-launch is a control-plane action → it should map to `ActionType.custom` and,
> per `00 §10`, **never auto** across a tenant boundary. The coordinator's tiered-autonomy policy
> (`08`) sets the tenant default to human-gated for all `red_*` verbs.

### 4.4 Driving the blue side (for completeness / the response half of the loop)

- One-shot playbook: `POST /api/workflows/{id}/execute {finding_id}` (`vigil/backend/api/workflows.py:285-322`,
  `WorkflowsService.execute_workflow(..., triggered_by="decepticon"|"coordinator")`,
  `services/workflows_service.py:428-459`).
- Autonomous investigation: `POST /api/orchestrator/investigations` (`vigil/backend/api/orchestrator.py:396`).
- ⚠️ The 5 file playbooks run **one-shot** (single Claude call) — for real phased purple-team playbooks
  with `approval_required` pauses you need **DB-authored custom workflows** AND to register their step
  titles in `daemon/plan_generator.WORKFLOW_STEP_MAP` (`vigil/daemon/plan_generator.py:14-58`) +
  `select_workflow` (`plan_generator.py:70-89`) so the autonomous orchestrator can plan them
  (`vigil-governance-gates`, `redblue-integration-gotchas`). Detailed in `07`/`08`.

### 4.5 Acceptance test (P4)

1. `get_tool_tier("decepticon-driver_red_launch_engagement") == "requires_approval"` (unit, no server).
2. Against a live LangGraph `:2024` (dockerized `decepticon` graph, dummy sandbox), `RedDriver.launch(...)`
   creates a thread, streams ≥1 `values` chunk, and the run appears in `client.runs.list(thread_id)`.
3. The MCP tool invoked by the daemon with `dry_run=false` produces a **PENDING** `approval_action`
   (never auto-executes) — assert a row in `approval_actions` with `status="pending"`.

---

## 5. The engine patch set (additive, tracked — per `00 §3`)

Each patch is tracked in `01`'s patch series (`patches/vigil/*.patch`, `patches/decepticon/*.patch`) so
upstream stays mergeable.

### 5a. Implement Vigil `isolate_host` (kill the mock)

**Problem:** `AutonomousResponseService._execute_isolation` returns a hard-coded mock
(`vigil/services/autonomous_response_service.py:406-438`, literally `"...successfully (MOCK)"`). Only
the Cloudflare actions (`waf_block`/`gateway_block`/`access_revoke`) truly execute
(`autonomous_response_service.py:719-779`). So an auto-approved isolate at ≥0.90 confidence does
**nothing** — a silent-failure safety hole (`00 §11.2`).

**Patch (in-place, tracked):** wire `_execute_isolation` to a real EDR through the existing MCP layer,
mirroring `_execute_cloudflare_action`'s "integration must be enabled" guard
(`autonomous_response_service.py:719-751`):

```python
def _execute_isolation(self, ip_address, hostname, reason, confidence) -> Dict:
    from core.config import is_integration_enabled
    # Prefer a real EDR MCP tool already in mcp-config.json (crowdstrike falcon-mcp / sentinelone
    # purple-mcp / microsoft-defender). Fail CLOSED — a disabled integration must NOT report success.
    if is_integration_enabled("crowdstrike"):
        return _call_mcp("crowdstrike", "cs_isolate_host", {"hostname": hostname, "ip": ip_address})
    if is_integration_enabled("sentinelone"):
        return _call_mcp("sentinelone", "isolate_endpoint", {"hostname": hostname})
    return {"success": False, "error": "no_edr_integration_enabled",
            "message": "Enable CrowdStrike/SentinelOne/Defender to execute isolate_host."}
```
Also reconcile the stale **0.85** thresholds in `_get_recommendation`/`investigate_and_respond`
(`autonomous_response_service.py:284-291,547`) to the authoritative **0.90** (`vigil-governance-gates`).
**Risk:** touches an execution path; must default fail-closed and stay behind the tenant
`force_manual_approval` knob until a real EDR is enabled. For the ESDS enclave with no CrowdStrike, wire
to the sensor plane instead (a Wazuh/Falco active-response host-isolation script, `04`).
**Acceptance:** with no EDR enabled, an approved `isolate_host` returns `success:false` and the
`approval_action` is `mark_failed`, not `mark_executed`.

### 5b. Add offensive verbs to `_ACTION_VERB_TOKENS` / `TOOL_TIERS`

Covered in **§4.3**. Standalone patch: `vigil/services/tool_manager.py` — extend the frozenset
(`:151-178`) and the `requires_approval` list (`:123-129`). **Risk:** low (additive to a frozenset);
verify no legitimate benign tool name contains these tokens (`engage` could false-match — audit current
tool names; none in `mcp-config.json` do). Add a unit test asserting each `red_*` name → `requires_approval`.

### 5c. Restore-or-**bridge** Decepticon's disabled KG vuln-research pipeline

**State (verified):** the 5-stage `vulnresearch` plugin family
(`Decepticon/.../agents/plugins/{scanner,detector,verifier,patcher,exploiter}.py` + orchestrator
`vulnresearch.py`) is **off by default** (bundle `plugins`, gated `is_bundle_enabled("plugins")`,
`vulnresearch.py:200-201`; registry `graph_registry.py:57-70`; enable via
`DECEPTICON_PLUGINS=standard,plugins`). Its **KG surface is stripped**: verifier/patcher ship
**bash-only** with explicit "removed pending the Neo4j middleware redesign" comments
(`verifier.py:66-74`, `patcher.py:61-70`, `scanner.py:62-73`, `detector.py:62-75`, `exploiter.py:64-82`).
The functions still exist but are unwired: `validate_finding` (`tools/research/tools.py:1792`, in
`RESEARCH_TOOLS` `:2425`), `patch_propose`/`patch_verify` (`tools/research/patch.py:55,136`). They route
through the **broken** `graph_transaction` legacy shim (`tools/research/_state.py:324-337`) that
`KGStore` (`middleware/kg_internal/store.py`) was built to replace but the plugins were never migrated to.
The same shim is what `tools/defense/blue_cell.py:216` uses to write `DetectionFired`/`DefenseAction`.

**Recommendation — BRIDGE, do not restore (respects `00 §3`).** Un-gutting the plugins means editing
upstream Decepticon plugin files (a non-additive change → conflict with `00 §3`, flagged in §7). For the
platform we do **not** need red's internal patch pipeline; we need the **detection-coverage** half. Plan:

1. **Enable only what's additive & working:** turn on the `plugins` bundle where the loop needs it via
   config (`DECEPTICON_PLUGINS=standard,plugins` or the runtime API
   `POST /_decepticon/bundles/plugins/enable`, `Decepticon/.../server/plugins_api.py:162-200`) — no code
   change. The scanner/detector CVE lookups work without KG.
2. **Drive the working `blue_cell`** (standard bundle, `agents/standard/blue_cell.py`) to write the
   `DetectionFired`/`DEFENSE_ACTION`/`DETECTED`/`USES_RULE` nodes — that path *does* run today (writes at
   `tools/defense/blue_cell.py:105-137`), just on the legacy shim. The coordinator reads those nodes via
   §2's `RedKGReader.detection_coverage()`. This gives the purple loop its coverage metric **without**
   depending on the disabled `validate_finding`/`patch_*` tools.
3. **Track (not own) the Neo4j redesign** as an upstream dependency: when Decepticon migrates
   `validate_finding`/`patch_*`/`blue_cell` off `graph_transaction` onto `KGStore`, drop any bridge shim.
   The unwired SIEM/EDR push tools (`tools/defense/tools.py:201-208`: `sigma_to_splunk/sentinel/elastic`,
   `yara_to_defender_xdr/crowdstrike`) are the *future* auto-remediation seam (red proposes a Sigma rule →
   blue deploys it) but are attached to **no roster agent** today — out of scope for P3/P4, noted for `08`.

**Risk:** if a future phase truly needs red's internal patch verification, restoring it is a larger
upstream migration (KGStore rewrite of `tools/research/*`), not a config flip — budget it separately.

### 5d. Turn on Decepticon RoE-enforce + HITL per tenant (config-only, no code)

Decepticon's two strongest gates ship **OFF** (`decepticon-safety-gates`). Per-engagement bring-up
(all verified):

1. **RoE enforce + egress boundary** — write `<workspace>/plan/roe.json` with
   `{"machine_enforcement":{"mode":"enforce","in_scope":[...],"testing_window":...}}`. `mode` enum is
   `EnforcementMode` `audit|warn|enforce` (`decepticon-core/.../types/roe.py:51-54`, default **audit**);
   only `enforce` short-circuits denied tool calls (`middleware/roe.py:351-395`) and provisions the
   **nftables + DNS-allowlist** egress boundary (`middleware/roe.py:470-508` →
   `sandbox_kernel/egress.py:334`). IMDS `169.254.169.254` + `.gov/.mil/.edu/.int` are default-denied
   (`types/roe.py:57-71`) unless `allow_cloud_metadata`/`allow_sensitive_tlds`. The HMAC-chained ledger
   auto-writes to `<workspace>/audit/roe-decisions.jsonl` (`middleware/_audit_sink.py:79-165`); set a
   **per-tenant `DECEPTICON_AUDIT_HMAC_KEY`** to bind the chain (feeds the evidence store, `08`).
2. **HITL approval** — set `DECEPTICON_HITL__ENABLED=1` (+ `DECEPTICON_ENGAGEMENT_ID`); the slot is
   skipped for falsy values (`agents/middleware_slots.py:363-390`). Wire format is
   `<workspace>/approvals/{requests,decisions}.jsonl` (`middleware/hitl.py:179-255`). **The coordinator
   auto-adjudicates** by appending to `decisions.jsonl` keyed by the `request_id` from `requests.jsonl`:
   ```json
   {"kind":"approval_decision","request_id":"<uuid>","action":"allow|deny|redirect","operator_note":"...","decided_at":<epoch>}
   ```
   The middleware polls every 0.25s and unblocks (`hitl.py:247-255`). Note HITL sits **above** RoE — an
   operator `allow` still passes through enforce-mode RoE/egress (`hitl.py:48-52`).
3. **Budget ceilings** — `DECEPTICON_BUDGET__ENGAGEMENT_USD` / `__PER_AGENT_USD` (>0 to arm),
   `middleware/budget.py:148-204`.
4. **Lock gates on** — do **not** set `DECEPTICON_ALLOW_SAFETY_OVERRIDES`; leaving it unset makes
   `build.py:_check_safety_gate` (`agents/build.py:287-333`) raise `SafetyOverrideViolation` if any
   plugin disables the safety-critical slots (incl. `HITL_APPROVAL`, `ROE_GUARDRAIL`).
5. **Engagement label** — `DECEPTICON_ENGAGEMENT=<slug>` must match
   `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$` (`decepticon-core/.../utils/engagement_scope.py:31`). The
   coordinator's `eng-<tenant>-<YYYYMMDD>-<short>` (`00 §7`) satisfies it (starts alphanumeric,
   hyphen-safe) — the coordinator **must validate** before every driver call (§4.1).

Config keys use the pydantic-settings nested delimiter `__` under env prefix `DECEPTICON_`
(`decepticon-core/.../utils/config.py:52-69`). **Risk:** enforce-mode egress requires the sandbox to run
`nft` (privileged netns); verify in the Kali sandbox image (`02`). All of this is per-tenant workspace/env
— **no engine code changes**, so fully compatible with `00 §3`.

---

## 6. The full loop, end-to-end, and P3/P4 acceptance

### 6.1 Sequence

```
Coordinator (:8900)
  1. mint engagement slug  eng-<tenant>-<YYYYMMDD>-<short>   (validate 00 §7 regex / DECEPTICON regex)
  2. write <ws>/plan/roe.json {machine_enforcement.mode=enforce, in_scope=[tenant CIDRs]}   [§5d]
     set DECEPTICON_HITL__ENABLED=1, DECEPTICON_BUDGET__*, DECEPTICON_AUDIT_HMAC_KEY(tenant)
  3. RedDriver.launch(engagement, workspace, sandbox_url, sandbox_token, target)   [§4.1]
        └─ POST :2024 runs.stream(assistant="decepticon", config.configurable=...)
  4. Decepticon runs scoped attack → sandbox (:9999, sandbox-net isolated)
        ├─ writes findings/FIND-*.md + events.jsonl (finding.created, tool.call, ...)   [§3]
        ├─ writes engagement-scoped Neo4j (Host/Service/Finding/Technique...)           [§2]
        └─ on high-risk tool call → approvals/requests.jsonl  → coordinator writes decisions.jsonl [§5d]
  5. TARGET + SENSORS (Wazuh/Suricata/Falco, telemetry-net) observe the REAL attack    [04]
        └─ sensor alerts → Vigil canonical findings (data_source=wazuh/suricata/falco) [04/05]
  6. EventTail sees finding.created → POST /api/webhooks/decepticon/findings           [§1,§3]
        └─ DecepticonIngestionService → canonical finding (data_source=decepticon)
  7. Vigil daemon triages/investigates BOTH streams (sensor + red-reported)             [vigil]
        └─ blue verdict, approval_actions, workflow_runs
  8. blue_cell (red side) writes DetectionFired/DETECTED/DefenseAction into Neo4j       [§5c]
  9. Coordinator scores:  attacked_surface (§2) vs blue detections (Vigil findings +
     RedKGReader.detection_coverage) → detection-rate, MTTD, MTTR, gaps  → scorecard    [07]
 10. engagement.end → close scorecard, write evidence store (RoE ledger + approvals)    [08]
```

Ground-truth integrity (`00 §10`): the **detection** metric counts only Vigil verdicts on
**sensor-origin** findings (`entity_context.red_source != "decepticon"`), so red's self-report can't
inflate the score — red findings are the *what-was-attacked* denominator, sensor+blue findings are the
*what-was-detected* numerator.

### 6.2 P3 exit (red→blue seam) — acceptance suite

- **T1 (§1.6):** signed webhook post of a FIND-* record → one canonical finding, `data_source="decepticon"`,
  technique in `mitre_predictions`, IP in `entity_context`, idempotent replay.
- **T2 (§3.4):** `EventTail` yields complete events, tolerates torn lines, fires exactly one webhook on
  `finding.created`.
- **T3 (§2.5):** `RedKGReader` returns detection gaps for a seeded engagement; unscoped query rejected;
  read role cannot write.
- **T4 (§4.5-1):** `get_tool_tier("decepticon-driver_red_launch_engagement") == "requires_approval"`.
- **T5:** Decepticon started with `roe.json mode=enforce` provisions egress (IMDS blocked — assert a
  sandbox `curl 169.254.169.254` fails) and `roe-decisions.jsonl` verifies (`_audit_sink.verify_ledger`).

### 6.3 P4 exit (coordinator MVP) — acceptance

- **T6:** one **manual** engagement driven end-to-end (§6.1 steps 1-10) produces a scorecard row with
  `attacked_count`, `detected_count`, `detection_rate`, `mttd_seconds`, and a non-empty `gaps` list
  (Findings with no `DETECTED` edge).
- **T7:** the red-launch MCP tool run by the blue daemon yields a **PENDING** `approval_action` and does
  not execute until the coordinator/operator approves (§4.5-3).
- **T8:** HITL round-trip — a Decepticon high-risk tool call blocks on `approvals/requests.jsonl`; the
  coordinator writes an `allow` to `decisions.jsonl`; the run continues (assert `tool.result` event
  follows the `tool.call` after the decision timestamp).
- **T9 (safety):** with tenant `force_manual_approval=true`, **no** containment auto-executes and **no**
  red action crosses the tenant's `in_scope` CIDRs (egress denies out-of-scope — assert an
  `[ROE_REFUSED]` entry in `roe-decisions.jsonl`).

---

## 7. Conflicts / deviations flagged back to `00`

1. **§5c non-additive tension (RESOLVED to additive).** Restoring Decepticon's disabled KG
   vuln-research pipeline would edit upstream plugin files, violating `00 §3`'s additive-patch rule.
   **Resolution:** we **bridge** (config-enable the working bundle + read blue_cell's KG output from the
   coordinator) rather than restore. If a later phase truly needs red's internal patch verification, `00
   §3` must grant an exception for a tracked upstream migration — surface it then, not now.
2. **In-place Vigil patches (5a, 5b, §4.3).** `autonomous_response_service.py` and `tool_manager.py` are
   edited in place (not new files). `00 §3` permits "a small, tracked patch set"; these qualify and are
   captured in `01`'s `patches/vigil/`. Flagging that these are *edits*, not purely additive new files —
   they should be minimal and upstream-mergeable (frozenset extension, one method body).
3. **Coordinator Neo4j credentials naming.** `00 §7` sets env prefix `REDBLUE_`; Decepticon's writer uses
   un-prefixed `DECEPTICON_NEO4J_*` (`store.py:68-84`). This doc introduces
   `REDBLUE_DECEPTICON_NEO4J_URI/USER/PASSWORD/DATABASE` for the coordinator's **read-only** role — add
   this row to `00 §4`/env registry so the two credential sets (writer vs reader) stay distinct.
4. **Shared workspace volume (new infra requirement).** Seams 3 & 5d require the coordinator to mount
   Decepticon's engagement workspace (read for `events.jsonl`/`FIND-*.md`; write for
   `approvals/decisions.jsonl` + `plan/roe.json`). `00 §5` lists data stores but not this mount — `02`
   must add a shared named volume on `redblue-shared` between `langgraph` and `redblue-coordinator`. The
   Kali `sandbox-net` stays isolated (`00 §5`) — the coordinator never mounts the sandbox, only the
   workspace.
5. **finding_id hash width (RECONCILED).** `00 §7` was corrected via `05` (which read the real Vigil
   code) to the canonical `f-<YYYYMMDD>-<sha256[:16]>` (`ID_HASH_WIDTH=16`, `ingestion_service.py:40`);
   the 8-hex SHA1 form was explicitly abandoned as collision-prone. This connector uses the 16-hex
   SHA-256 form throughout, and the `(data_source, external_id)` UNIQUE index — with
   `external_id="<engagement_id>:<red_action_id>"` — is the authoritative dedup key regardless of hash
   width. No remaining conflict.
6. **No new ports** — confirmed; this doc claims none, consistent with `00 §4`. New env vars only
   (`DECEPTICON_INGESTION_ENABLED`, `DECEPTICON_WEBHOOK_SECRET`, `REDBLUE_LANGGRAPH_URL`,
   `REDBLUE_DECEPTICON_NEO4J_*`, `DECEPTICON_DRIVER_TOKEN`).
```
