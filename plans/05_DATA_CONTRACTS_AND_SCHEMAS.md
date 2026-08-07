# 05 — Data Contracts & Schemas (canonical)

> **Status:** Planning (pre-code). **Owner:** ESDS RedBlue AI team.
> **This document is the single source of truth for every schema that crosses a
> component boundary.** The coordinator, the Decepticon→Vigil connector, the
> sensor-plane mappers, the governance engine, and the UI all code against the
> shapes defined here. Where a schema already exists in a reused engine, this
> doc *transcribes the real code* (with `file:line` provenance) rather than
> inventing — accuracy vs. the running code is paramount. Where a schema is new
> (coordinator, governance, evidence), this doc *defines* it and the named
> downstream doc implements it.
>
> Conforms to **`00_MASTER_PLAN.md`** (authoritative). One naming conflict with
> `00 §7` was found in the real code and is flagged in **§0** and **§2** — `00`
> should be corrected.

---

## 0. Conformance & conflicts with `00_MASTER_PLAN.md`

| Topic | `00` says | Real code says | Resolution |
|---|---|---|---|
| Engagement id | `eng-<tenant>-<YYYYMMDD>-<short>`, must match Decepticon regex | Regex is `^[A-Za-z0-9][A-Za-z0-9._\-]{0,127}$` (`Decepticon/packages/decepticon-core/decepticon_core/utils/engagement_scope.py:31`) | **No conflict.** `eng-t01-20260805-ab12` matches. Keep `00 §7`. |
| Finding id from red | `f-<YYYYMMDD>-<sha1_8>` (`00 §7`) | Vigil ingestion mints `f-<YYYYMMDD>-<sha256[:16]>` (`vigil/services/ingestion_service.py:40,659-660,840-841,942-943`; `ID_HASH_WIDTH = 16`, algorithm is **sha256**, width **16 hex / 64 bits**). The 8-char/32-bit form was explicitly abandoned as collision-prone (comment at `ingestion_service.py:38-40`). | **CONFLICT → correct `00 §7`.** Canonical is **`f-<YYYYMMDD>-<sha256_16>`** (see §2). `00` conflated the KG node hash (`sha1[:16]`, `kg.py:344`) with the finding hash. |
| Red-finding dedup | (unspecified) | Vigil has a DB-level unique key `(data_source, external_id)` (`vigil/database/models.py:136-144`) that dedupes independently of `finding_id`. | **Add to `00 §7`:** the connector MUST set `external_id` to a stable per-red-action key; that, not the hash, is the authoritative idempotency guarantee (§2, §8). |
| Blue reads red KG | `MATCH (n) WHERE n.engagement=$e` | Exactly this; `$engagement` binding is *enforced* (`Decepticon/.../kg_internal/store.py:186-187,233`). | **No conflict.** Confirmed (§4). |
| `data_source="decepticon"` | `00 §7` | `data_source` column is `String(50)` (`models.py:85`); free-form. | **No conflict.** Confirmed. |

Everything else in this doc conforms to `00` as written.

---

## 1. Vigil canonical finding schema (the ingest contract)

**This is the most important contract in the platform** — every sensor alert and
every red action becomes one of these rows before blue can act on it.

### 1.1 Provenance

- Persisted by `DatabaseService.create_finding(...)` — `vigil/database/service.py:49-98`.
- Called with exactly these keys by `IngestionService.ingest_finding(...)` — `vigil/services/ingestion_service.py:219-233`.
- Table = ORM model `Finding` (`__tablename__ = "findings"`) — `vigil/database/models.py:62-145`. **The table is created by SQLAlchemy `create_all`, not by a hand-written SQL file** (`01_init_schema.sql` only enables extensions), so `models.py` is the authoritative column list.

### 1.2 The 13 ingest fields (+ 3 system-managed)

`create_finding` accepts 6 positional args + `**kwargs`; `ingest_finding` supplies
the following **13 logical fields**. Anything outside this set passed to a direct
ingest is **silently dropped** (see §1.5).

| # | Field | Type (PG) | Req? | Default | Notes / provenance |
|---|---|---|---|---|---|
| 1 | `finding_id` | `VARCHAR(50)` PK | **yes** | — | `f-<YYYYMMDD>-<sha256_16>` (§2). Missing → row rejected (`ingestion_service.py:198-202`). |
| 2 | `embedding` | `vector(768)` | **yes** | `[0.0]*768` | `EMBEDDING_DIM = 768` (`models.py:33,70`). Padded/truncated to 768 by `_normalize_embedding` (`service.py:78`). Red/sensor findings that have no LogLM embedding send the 768-zero vector. |
| 3 | `mitre_predictions` | `JSONB` | **yes** | `{}` | `{ <key>: <score float 0-1> }` — see §1.4. NOT NULL at the DB (`models.py:71`); send `{}` not null. |
| 4 | `anomaly_score` | `FLOAT` | **yes** | `0.0` | 0.0–1.0. Drives daemon triage + severity derivation. NOT NULL (`models.py:72`). |
| 5 | `timestamp` | `TIMESTAMP` | **yes** | `utcnow()` | **Event time**, not ingest time. The correlation clock (§8). Parsed by `parse_timestamp` (`ingestion_service.py:143-186`). NOT NULL (`models.py:84`). |
| 6 | `data_source` | `VARCHAR(50)` | **yes** | `"imported"` | Origin label: `"decepticon"`, `"wazuh"`, `"suricata"`, `"falco"`, `"flow"`… Half of the dedup key. NOT NULL (`models.py:85`). |
| 7 | `external_id` | `VARCHAR(255)` | no | `null` | Source-native id. `(data_source, external_id)` is a **UNIQUE index when both non-null** (`models.py:136-144`) — the real dedup key. |
| 8 | `description` | `TEXT` | no | `null` | Human-readable. GIN-trigram indexed for search (`models.py:130-135`). |
| 9 | `entity_context` | `JSONB` | no | `null` | The extensibility bag — IPs, ports, host, and **all non-canonical metadata** (§1.3, §1.5). |
| 10 | `evidence_links` | `JSONB` (`List[dict]`) | no | `null` | Pointers to artifacts (log lines, pcaps, KG nodes, FIND-*.md). |
| 11 | `cluster_id` | `VARCHAR(50)` | no | `null` | Attack-cluster grouping. Indexed (`idx_finding_cluster_id`). **We reuse it as `engagement_id` for `data_source="decepticon"`** (§8). |
| 12 | `severity` | `VARCHAR(20)` | no | `null` | `critical`/`high`/`medium`/`low` (free-form string; not enum-enforced at DB). Indexed. |
| 13 | `status` | `VARCHAR(20)` | **yes** | `"new"` | `new`/`unscored`/…; free-form. NOT NULL default `new` (`models.py:91-93`). |
| — | `ai_enrichment` | `JSONB` | (system) | `null` | **Written by blue post-ingest**, never at ingest. Holds the blue AI's technique conclusions + verdict. The coordinator reads this for "what blue concluded" (§6, §8). (`models.py:96`) |
| — | `created_at` / `updated_at` | `TIMESTAMP` | (system) | `now()` | Ingest/modify wall-clock; distinct from `timestamp`. (`models.py:99-108`) |

### 1.3 `entity_context` sub-structure

`entity_context` is schemaless `JSONB`, but the ingestion transformers establish a
**de-facto convention** all producers SHOULD follow so the UI and correlator find
fields in predictable places. Column-name aliasing is codified in
`ENTITY_FIELD_ALIASES` (`ingestion_service.py:53-60`).

> **Canonical = SINGULAR scalars** (`src_ip`, `dst_ip`, `src_port`, `dst_port`, `proto`). The
> correlator (§8) reads these scalars. Vigil's native SIEM/Kafka paths additionally carry
> **plural-list** forms (`src_ips`, `dest_ips`, `hostnames`, `usernames`); sensor + red connector
> transforms MUST populate the scalar canonical and MAY also carry the plural list. The coordinator's
> correlator normalizes plural→scalar (`src_ip or src_ips[0]`) so either shape joins (doc 04 §4.3).

```jsonc
entity_context = {
  // network 5-tuple (canonical keys; producers map their own names in)
  "src_ip":   "10.20.0.5",     // aliases: source_ip, srcip, ip1, saddr, focal_ip
  "dst_ip":   "10.20.0.9",     // aliases: dest_ip, destination_ip, dstip, ip2, daddr, engaged_ip
  "src_port": 51544,           // aliases: source_port, sport
  "dst_port": 445,             // aliases: destination_port, dport
  "proto":    "tcp",           // aliases: protocol, ip_proto

  // producer-specific (examples pulled from the real transformers)
  "sequence_id":      "…",     // Tempo/LogLM row identity  (ingestion_service.py:685,893)
  "confidence_score": 0.87,    // normalized 0-1            (ingestion_service.py:686,891)
  "raw_features":     { … },   // whole source row, generic path (ingestion_service.py:951)

  // OPTIONAL bounded source-evidence envelope (services/source_evidence.py)
  "source_evidence": {
    "version": 1,
    "telemetry_kind": "netflow",          // netflow|dns|http_session|generic_log
    "schema_id": "netflow.v1",
    "status": "available",                // available|not_in_artifact|redacted|invalid
    "provenance": "embedded"              // embedded|joined
  }
}
```

Real transformer outputs (use as the reference for what "well-formed" looks like):
- **Tempo CSV** → `src_ip, dst_ip, sequence_id, confidence_score, event_end, user_feedback` (`ingestion_service.py:682-696`)
- **LogLM parquet** → `src_ip(focal_ip), dst_ip(engaged_ip), incident_pred, confidence_score, sequence_id, event_start_time, event_end_time, row_count, source_evidence` (`ingestion_service.py:887-906`)
- **Generic** → `src_ip, dst_ip, src_port, dst_port, proto, raw_features` (`ingestion_service.py:945-952`)

### 1.4 `mitre_predictions` shape — and the key-vocabulary drift

`mitre_predictions` is `{ <key>: <float 0-1> }`, but **the key vocabulary is not
uniform across producers** in the current code — a real drift the platform must
police:

| Producer | Key form | Value | Provenance |
|---|---|---|---|
| Generic finding CSV | **Technique ID** `T1071.001` | supplied score | `ingestion_service.py:600-612` (`T1071.001:0.85` or JSON dict) |
| Tempo CSV | **Tactic NAME** `"Command and Control"` | `1.0` | `ingestion_service.py:663-666` |
| LogLM parquet | **Tactic NAME** (via `MITRE_TACTIC_MAP`) | softmax prob | `ingestion_service.py:850-868`, map at `:31-36` |

**Canonical rule for RedBlue (all NEW producers — Decepticon connector + sensor
mappers):** keys MUST be **ATT&CK technique IDs** (`T####` / `T####.###`), values
`0.0-1.0`. Tactic names are tolerated on legacy DeepTempo paths only. The
coordinator's technique correlation (§8) keys off technique IDs; a tactic-name-only
finding cannot be joined to a red `Technique` node and is scored as "detected but
untechnique-mapped."

```jsonc
mitre_predictions = { "T1190": 1.0, "T1059.004": 0.9 }   // canonical
```

### 1.5 The schema-drift trap (MUST-follow rules)

`create_finding` persists **only** the 16 columns in §1.2. There is **no
`engagement_id` column, no `tenant_id` column, no `host`/`rule_id`/`technique`
column.** Any such field sent at the top level of a finding JSON to
`/api/ingest/*` is **silently discarded** — the ingest reads named kwargs and drops
the rest (`ingestion_service.py:219-233`). This is the single biggest integration
hazard (flagged in memory `redblue-integration-seams §1`).

**Rules — where non-canonical data MUST live:**

1. **Engagement / tenant / red-action linkage** → `entity_context.engagement_id`,
   `entity_context.tenant_id`, `entity_context.red_action_id`; ALSO mirror
   `engagement_id` into `cluster_id` (indexed) and encode it into `external_id`
   (§2, §8). Never assume a top-level column exists.
2. **Techniques** → `mitre_predictions` (technique-ID keys, §1.4). Not a stray
   `technique` field.
3. **Any sensor/host/rule metadata** (Wazuh rule id, Suricata signature id, Falco
   pod, agent hostname) → nested inside `entity_context`.
4. **Artifact pointers** (pcap path, FIND-*.md, KG node id, raw log line) →
   `evidence_links` (a `List[dict]`), not free-form top-level keys.
5. **Never send `null` for the three NOT-NULL JSON/scalar fields** —
   `mitre_predictions` (`{}`), `embedding` (`[0.0]*768`), `anomaly_score` (`0.0`).

> Transport note (detail belongs to `06`): the low-drift path is a dedicated
> `DecepticonIngestionService` that builds this exact dict; fast manual paths are
> `POST /api/ingest/ingest-string` (form `data`, `format=json`, `data_type=finding`)
> and `POST /api/integrations/vstrike/findings`. All of them funnel through
> `create_finding`, so the drift rules above are universal.

---

## 2. Decepticon → Vigil finding mapping

A red action/finding becomes one canonical finding. Decepticon's own `Finding`
model (`Decepticon/packages/decepticon-core/decepticon_core/types/engagement.py:134-201`)
is the richest source; a live attack **event** (`events.jsonl`, §5) or a KG
`Finding` node can also be the trigger.

### 2.1 `finding_id` (conforms to Vigil ingestion, NOT `00 §7` sha1_8)

```
finding_id = "f-" + <event_ts as %Y%m%d> + "-" + sha256(unique_key)[:16]
```
- 16 hex chars = 64 bits, matching Vigil's `ID_HASH_WIDTH` and algorithm
  (`ingestion_service.py:40,659-660`). **This supersedes `00 §7`'s `sha1_8`.**
- `unique_key` = a stable per-red-action string: `f"{engagement_id}:{red_action_id}"`
  where `red_action_id` = Decepticon `Finding.id` (`FIND-001`), or the KG node id,
  or `f"{technique}:{target}:{event_ts_bucket}"` when neither exists.
- **Idempotency is guaranteed by the DB, not the hash:** set
  `external_id = "{engagement_id}:{red_action_id}"` and `data_source="decepticon"`;
  the `(data_source, external_id)` unique index (`models.py:136-144`) makes re-ingest
  a no-op regardless of hash.

### 2.2 Field-by-field map

| Canonical finding | ← Decepticon source | Rule |
|---|---|---|
| `finding_id` | derived (§2.1) | `f-<date>-<sha256_16>` |
| `data_source` | constant | `"decepticon"` (`00 §7`) |
| `external_id` | `engagement_id` + `Finding.id` | `"{engagement_id}:{FIND-xxx}"` — dedup key |
| `timestamp` | `Finding.discovered_at` / event `ts` / KG `lastupdated` | event time; ISO 8601 or epoch |
| `mitre_predictions` | `Finding.mitre[]` (e.g. `["T1190"]`) | `{ tid: confidence }`; confidence from `Finding.confidence` (verified=1.0, probable=0.7, unverified=0.4) |
| `severity` | `Finding.severity` (`FindingSeverity`) | direct: `critical/high/medium/low/informational→low` |
| `anomaly_score` | `Finding.cvss_score`/10, else severity map | 0-1 (critical≈0.95, high≈0.8, medium≈0.5, low≈0.2) |
| `description` | `Finding.title` + `Finding.description` | truncate title into one line |
| `cluster_id` | `engagement_id` | reuse indexed column for cheap per-engagement filter (§8) |
| `status` | constant | `"new"` |
| `embedding` | none | `[0.0]*768` |
| `entity_context` | `Finding.affected_target`, `.affected_component`, agent, phase, **linkage keys** | see below |
| `evidence_links` | `Finding.evidence[]` (`Evidence`: type/path/sha256/collected_at) | list of `{type, path, sha256, collected_at}` + KG node ref |

```jsonc
// entity_context for a decepticon-origin finding (linkage keys are MANDATORY, §1.5)
entity_context = {
  "engagement_id":  "eng-t01-20260805-ab12",   // AUTHORITATIVE copy
  "tenant_id":      "t01",
  "red_action_id":  "FIND-014",                 // Decepticon Finding.id / KG node id
  "src_ip":         "<attacker/source>",        // AttackPathStep.source or agent sandbox
  "dst_ip":         "10.20.0.9",                // Finding.affected_target (resolved to IP)
  "affected_target":"web01.range.local",
  "affected_component": "nginx :443 /upload",
  "phase":          "initial-access",           // ObjectivePhase
  "agent":          "exploit",                  // discovering sub-agent
  "objective_id":   "OBJ-003",
  "kg_node_id":     "<sha1_16 KG Finding node>",
  "attack_path_id": "PATH-001"
}
```

> The red `Finding.detected` / `detection_notes` fields
> (`engagement.py:175-180`) are **red's self-report** and are deliberately NOT
> trusted for scoring — the coordinator computes detection from independent blue
> findings (§6). Carry them into `entity_context.red_self_report` for audit only.

---

## 3. Sensor → canonical finding mappings

The sensor plane is NEW (built in `04`); these tables are the **contract `04`
implements**. Each sensor's native alert becomes one canonical finding via the
same `create_finding` path (so §1.5 drift rules apply). Native alert schemas are
well-known (Wazuh/OSSEC JSON, Suricata EVE JSON, Falco JSON).

### 3.1 Wazuh alert → finding (`data_source="wazuh"`)

| Canonical | ← Wazuh field | Notes |
|---|---|---|
| `external_id` | `id` (alert id) or `rule.id`+`@timestamp` | dedup key |
| `timestamp` | `@timestamp` / `timestamp` | event time |
| `severity` | `rule.level` (0-15) | ≥12 critical, ≥8 high, ≥4 medium, else low |
| `anomaly_score` | `rule.level / 15.0` | normalize |
| `mitre_predictions` | `rule.mitre.id[]` (T-codes) | `{ tid: 1.0 }` |
| `description` | `rule.description` | |
| `entity_context` | `agent.name`/`agent.ip` (host), `data.srcip`, `data.dstip`, `rule.id`, `rule.level`, `rule.groups` | host lives here |
| `evidence_links` | `full_log` / `location` | `[{type:"log", path, …}]` |

### 3.2 Suricata EVE (`event_type=="alert"`) → finding (`data_source="suricata"`)

| Canonical | ← Suricata EVE field | Notes |
|---|---|---|
| `external_id` | `flow_id` + `alert.signature_id` | dedup key |
| `timestamp` | `timestamp` | event time |
| `severity` | `alert.severity` (1=high…3=low) | invert to critical/high/med |
| `anomaly_score` | derived from `alert.severity` | |
| `mitre_predictions` | `alert.metadata.mitre_technique_id[]` | `{ tid: 1.0 }` |
| `description` | `alert.signature` (+ `alert.category`) | |
| `entity_context` | `src_ip`, `dest_ip`(→`dst_ip`), `src_port`, `dest_port`(→`dst_port`), `proto`, `flow_id`, `alert.signature_id`, `app_proto` | full 5-tuple |
| `evidence_links` | `pcap`/`payload` ref | |

### 3.3 Falco event → finding (`data_source="falco"`)

| Canonical | ← Falco field | Notes |
|---|---|---|
| `external_id` | `rule` + `time` (+ `output_fields.container.id`) | dedup key |
| `timestamp` | `time` | event time |
| `severity` | `priority` (Emergency…Debug) | Emergency/Critical→critical, Error/Warning→high… |
| `anomaly_score` | derived from `priority` | |
| `mitre_predictions` | `tags[]` (filter `T####`/`mitre_*`) | `{ tid: 1.0 }` |
| `description` | `output` / `rule` | |
| `entity_context` | `output_fields`: `proc.name`, `proc.cmdline`, `container.id`, `container.name`, `k8s.pod.name`, `fd.name`, `user.name`; host from node | container/pod runtime context |
| `evidence_links` | raw event json ref | |

---

## 4. Shared attack-graph schema (Decepticon Neo4j)

**Single source of truth for ground truth.** Blue reads it; blue may annotate it.
Vigil's own `graph_builder` is ephemeral/in-memory — do **not** build a third graph.
Provenance: `Decepticon/packages/decepticon-core/decepticon_core/types/kg.py` (enums
+ in-memory model) and `Decepticon/packages/decepticon/decepticon/middleware/kg_internal/store.py`
(the Neo4j `KGStore`).

### 4.1 Node & edge object shape (`kg.py:324-378`)

```jsonc
Node = { "id": "<sha1_16>", "kind": <NodeKind>, "label": "…",
         "props": { … }, "created_at": <float>, "updated_at": <float> }
Edge = { "id": "<sha1_16>", "src": "<nodeid>", "dst": "<nodeid>",
         "kind": <EdgeKind>, "weight": 1.0, "props": { … }, "created_at": <float> }
```
- Deterministic ids: `Node.id = sha1("<kind>::<key>")[:16]`, `key` defaults to
  `label` (`kg.py:334-347`); `Edge.id = sha1("<src>-><kind>-><dst>::<key>")[:16]`
  (`kg.py:361-378`). Dedup is by id (append-mostly).
- **Neo4j-native labels:** `NodeKind` values are the PascalCase Neo4j labels;
  `EdgeKind` values are the UPPER_CASE relationship types — used *directly*, no
  translation layer.

### 4.2 Engagement scoping (the tenancy property)

Every node carries reserved provenance props injected by `KGStore`
(`store.py:13-16`):

| Prop | Meaning |
|---|---|
| `engagement` | **multi-tenant scope label** = the `engagement_id` (§0). |
| `firstseen` | epoch on first `MERGE` (`ON CREATE`) |
| `lastupdated` | epoch on every touch — powers the `revision()` / CART drift token |
| `created_by` | agent role string (e.g. `"analyst"`) |

**Scope is enforced, not advisory:** every read/write must bind `$engagement` or
`KGStore` raises `"Neo4j query rejected: missing $engagement scope"`
(`store.py:182-187`). The blue-read query is exactly:
```cypher
MATCH (n) WHERE n.engagement = $engagement RETURN n     // store.py:233,252
```

### 4.3 `NodeKind` (enumerated, `kg.py:46-122`)

- **Infrastructure:** `Host, Network, Domain, Service, URL, CloudResource, Container`
- **Identity:** `User, Group, Credential, Secret, Session`
- **Vulnerability:** `Vulnerability, CVE, Misconfiguration, Weakness`
- **Code:** `Repository, SourceFile, CodeLocation, Contract`
- **Attack Progression:** `Technique, Entrypoint, CrownJewel, AttackPath, Finding`
- **Analysis:** `Candidate, Hypothesis, Patch`
- **🔵 Defense (natively purple):** **`DetectionFired`, `DefenseAction`**
- **Active Directory (BloodHound 5.x):** `ADUser, ADComputer, ADGroup, ADDomain, ADGPO, ADOU, ADContainer, ADCertTemplate, ADEnterpriseCA, ADRootCA, ADAIACA, ADNTAuthStore, ADIssuancePolicy, ADLocalGroup`
- **Solidity (Slither):** `Function, StateVar, Event, CustomError, Enum, Struct, Pragma`
- **AI attack surface:** `Technology` (with closed `TechnologyCategory`: `ai-runtime, ai-proxy, ai-framework, ai-sdk-client, web-server, web-framework, cms, language-runtime, database` — `kg.py:259-279`; fingerprints Ollama/vLLM/LiteLLM).

### 4.4 `EdgeKind` (the purple-relevant subset; full list `kg.py:125-256`)

- **Topology:** `HOSTS, RESOLVES_TO, CONTAINS, EXPOSES, ROUTES_TO, PART_OF, MANAGES, RUNS`
- **Access:** `AUTHENTICATES_TO, HAS_SESSION, MEMBER_OF, CAN_ACCESS, ADMIN_TO, OWNS, GRANTS`
- **Exploitation:** `AFFECTS, HAS_VULN, EXPLOITS, ENABLES, LEAKS, LEADS_TO, DEFINED_IN, INSTANCE_OF`
- **Kill chain:** `PIVOTS_TO, ESCALATES_TO, REACHES, STARTS_AT, STEP, USES`
- **Validation:** `VALIDATES, DERIVED_FROM, PATCHES, MAPS_TO`
- **🔵 Defense (natively purple):** **`DETECTED, USES_RULE`**
- (+ large AD/ADCS-ESC and Solidity `CALLS` sets — not consumed by the loop MVP.)

### 4.5 How blue reads and annotates (the purple contract)

- **Read ground truth:** what red actually touched = `by_kind(Technique)` +
  `Host`/`Service`/`CrownJewel` reached, scoped by `$engagement`. This is the
  denominator for detection-rate (§6).
- **Annotate detections (write-back):** for each blue detection, blue (via the
  coordinator) MERGEs a **`DetectionFired`** node and a **`(:DetectionFired)-[:DETECTED]->(:Technique|:Host)`**
  edge, plus **`-[:USES_RULE]->(:Service{rule})`** for the firing rule. Any
  containment becomes a **`DefenseAction`** node. Because these kinds already exist
  in the closed enum, blue write-back needs **no schema change** — only that every
  write carries `engagement=$engagement`, `created_by="vigil"`, and the reserved
  provenance props. Suggested props on a `DetectionFired` node:
  `{ finding_id, data_source, rule_id, detected_at, mttd_seconds, confidence }`.

---

## 5. Decepticon event schema (the blue-observable stream)

Provenance: `Decepticon/packages/decepticon/decepticon/runtime/event_log.py`.
One append-only `events.jsonl` per engagement at
`engagements/<engagement_id>/events.jsonl` (or `<workspace>/events.jsonl` via
`EventLog.for_workspace`), POSIX `flock`-guarded, torn-line-tolerant on read.

### 5.1 Line shape (`EngagementEvent`, `event_log.py:102-130`)

```jsonc
{ "ts": 1754390400.123, "type": "tool.call", "agent": "exploit",
  "payload": { … } }        // "agent" omitted when null; "payload" always present
```
| Field | Type | Notes |
|---|---|---|
| `ts` | `float` | seconds since epoch (wall clock) — the red-action clock for MTTD |
| `type` | `string` | one of `EventType` (kept as raw str on disk for forward-compat) |
| `agent` | `string?` | emitting sub-agent; absent if unknown |
| `payload` | `object` | type-specific, intentionally untyped (forward-compatible) |

### 5.2 `EventType` enum (10 values, `event_log.py:87-99`)

`engagement.start`, `engagement.end`, `engagement.checkpoint`, `agent.turn`,
`tool.call`, `tool.result`, `llm.call`, `llm.response`, **`finding.created`**,
`opplan.update`.

**Coordinator consumption:** tail this file; `tool.call`/`tool.result` +
`finding.created` are the red-action timeline the coordinator diffs against blue
findings. `engagement.start`/`end` bound the scoring window (§6/§8);
`opplan.update` tracks objective progress. Consumers dispatch on `type` and never
parse free-form text.

---

## 6. Coordinator schemas (NEW — defined here, implemented in `07`)

The coordinator owns its own small store (SQLite MVP → Postgres, `00 §5`). These
are the definitions `07` codes against.

### 6.1 `Engagement`

```jsonc
Engagement = {
  "engagement_id": "eng-t01-20260805-ab12",   // PK; regex ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ (§0)
  "tenant_id":     "t01",                       // scoping key, threaded everywhere (00 §7)
  "name":          "Q3 external range test",
  "engagement_type":"external",                 // Decepticon EngagementType: external|internal|hybrid|assumed-breach|physical
  "roe_ref":       "engagements/eng-…/plan/roe.json",          // pointer to Decepticon RoE bundle (§7.3)
  "enforcement_mode":"enforce",                 // roe.py EnforcementMode: audit|warn|enforce
  "scope": {                                     // mirror of RoE machine_enforcement (roe.py:100-114)
     "in_scope":  ["10.20.0.0/24"],
     "out_of_scope": ["10.20.0.1"],
     "blackout_windows": ["2026-08-05T22:00:00+05:30/PT8H"]
  },
  "target":        { "range": "range.local", "entrypoints": ["web01:443"] },
  "status":        "running",                   // see vocab below
  "decepticon": {                               // handles from LangGraph :2024 (mcp_server/models.py)
     "thread_id": "…", "run_id": "…", "assistant": "decepticon",
     "workspace_path": "engagements/eng-…"
  },
  "created_at": "…", "updated_at": "…"
}
```

**Status vocabulary** (coordinator lifecycle; superset that maps onto Decepticon's
run `status`/`run_status` strings from `mcp_server/models.py:39,61,108`):
`scheduled → running → awaiting_telemetry → scoring → completed | aborted | failed`.

### 6.2 `Scorecard`

```jsonc
Scorecard = {
  "engagement_id": "eng-t01-20260805-ab12",
  "tenant_id":     "t01",
  "generated_at":  "…",
  "window":        { "start": <epoch>, "end": <epoch> },   // from engagement.start/end (§5)

  "attacked_techniques": ["T1190","T1059.004","T1071.001"], // from KG Technique nodes + events (§4,§5)
  "detected_techniques": ["T1190","T1071.001"],             // from blue findings mitre_predictions + ai_enrichment
  "gaps":                ["T1059.004"],                      // attacked − detected

  "detection_rate":  0.67,                                   // |detected ∩ attacked| / |attacked|
  "attack_coverage": { "attacked": 3, "detected": 2 },
  "att_ck_coverage": {                                       // per-tactic rollup vs ATT&CK
      "TA0001": {"attacked": 1, "detected": 1},
      "TA0002": {"attacked": 1, "detected": 0}
  },

  "per_finding": [
    { "technique": "T1190",
      "target": "10.20.0.9",
      "red_action_id": "FIND-014",
      "red_action_ts": <epoch>,                 // events.jsonl ts / discovered_at
      "blue_finding_id": "f-20260805-<sha256_16>",
      "blue_detect_ts":  <epoch>,               // finding.timestamp / created_at
      "detected": true,
      "mttd_seconds": 42,                        // blue_detect_ts − red_action_ts
      "response_action_id": "action-20260805-…", // approval_actions.action_id (§7.1)
      "response_ts": <epoch>,
      "mttr_seconds": 180,                       // response_ts − blue_detect_ts
      "linkage": "engagement_id+technique+target+Δt"   // how the join was made (§8)
    }
  ],

  "mttd_p50_seconds": 42, "mttd_p95_seconds": 210,
  "mttr_p50_seconds": 180, "mttr_p95_seconds": 900
}
```

- **MTTD** per finding = `blue_detect_ts − red_action_ts` (both event-time clocks:
  finding.`timestamp` vs `events.jsonl.ts`). **MTTR** = `response_ts − blue_detect_ts`
  where `response_ts` = the linked `approval_actions.executed_at` (§7.1).
- Denominator (`attacked_techniques`) comes from **ground truth** (KG + events), never
  from red's self-report `Finding.detected`.

---

## 7. Governance records (NEW data — enforcement logic deferred to `08`)

This section defines the *shapes*; the tiered-autonomy policy engine and the
WORM evidence store that produce/consume them are specified in `08`.

### 7.1 Existing Vigil approval record (transcribed — the HITL substrate)

Provenance: `ActionType`/`ApprovalService.create_action` —
`vigil/services/approval_service.py:35-48,244-308`; table
`vigil/database/init/13_approval_actions.sql:18-42`.

**`ActionType` enum (11):** `isolate_host, block_ip, block_domain, quarantine_file,
disable_user, execute_spl_query, workflow_phase, waf_block, gateway_block,
access_revoke, custom`.

**`approval_actions` table:**

| Column | Type | Notes |
|---|---|---|
| `action_id` | `VARCHAR(80)` PK | `action-YYYYMMDD-HHMMSS-ffffff` |
| `action_type` | `VARCHAR(40)` | `ActionType` value |
| `title`, `description`, `reason` | `TEXT` | |
| `target` | `TEXT` | IP / hostname / username / run_id |
| `confidence` | `NUMERIC(4,3)` | 0.000–1.000 |
| `evidence` | `JSONB` (`[]`) | finding ids / refs |
| `requires_approval` | `BOOLEAN` (true) | **gate:** set `= confidence < 0.90` (`approval_service.py:264-267`) |
| `status` | `VARCHAR(16)` | CHECK `pending|approved|rejected|executed|failed` |
| `created_at`/`created_by` | `TIMESTAMP`/`VARCHAR(100)` | |
| `approved_at`/`approved_by` | `TIMESTAMP`/`VARCHAR(100)` | |
| `executed_at` | `TIMESTAMP` | → `Scorecard.per_finding.response_ts` (§6) |
| `execution_result` | `JSONB` | |
| `rejection_reason` | `TEXT` | |
| `parameters` | `JSONB` (`{}`) | |
| `workflow_run_id` | `VARCHAR(80)` FK→`workflow_runs` | null for daemon actions |
| `workflow_phase_id` | `TEXT` | |

**Confidence gate (authoritative):** `requires_approval = confidence < 0.90`;
per-tenant `force_manual_approval=true` forces everything to `pending`
(`approval_service.py:264-267`, `_load_config`). ⚠️ Stale helpers
`should_auto_approve`/`get_action_decision` still hard-code `0.85`
(`approval_service.py:197,208-213`) — **reconcile to 0.90** (tracked for `08`).
⚠️ Tool-tier gap: verbs `launch`/`exploit`/`attack` are absent from Vigil's
`TOOL_TIERS`, so a Decepticon-driver MCP tool defaults auto-executable and MUST be
registered `requires_approval` (memory `vigil-governance-gates`; fix in `06`/`08`).

### 7.2 Tiered-autonomy decision record (NEW)

The per-decision audit row the policy engine (`08`) emits for **every** gated
action, red or blue:

```jsonc
TieredAutonomyDecision = {
  "decision_id":   "dec-20260805-…",
  "ts":            <epoch>,
  "engagement_id": "eng-t01-20260805-ab12",
  "tenant_id":     "t01",
  "actor":         "vigil",              // red | vigil | coordinator | human
  "subject":       { "kind": "action", "action_type": "isolate_host", "target": "10.20.0.9" },
  "tier":          "human",              // auto | human | never   (the tiered model, moat memory)
  "inputs": {
     "confidence":            0.83,      // vs 0.90 gate (§7.1)
     "tool_tier":             "requires_approval",   // tool_manager.py tier
     "roe_decision":          "IN_SCOPE",            // roe.py Decision.reason_code
     "force_manual_approval": false,
     "crosses_tenant_boundary": false,               // → forces never/human (00 §10)
     "touches_control_plane":   false                // → forces never (00 §10)
  },
  "outcome":       "pending",            // allowed | pending | denied
  "approval_action_id": "action-20260805-…",  // link to §7.1 row when HITL
  "approver":      null,
  "rationale":     "confidence 0.83 < 0.90 → HITL",
  "evidence_ref":  "ev-000123"           // → §7.3 chain seq
}
```
The `tier` decision precedence (defined fully in `08`): `never` (tenant-boundary
or control-plane) > forbidden tool-tier > `force_manual_approval` > confidence gate
> RoE `Decision.allow`.

### 7.3 Hash-chained evidence record (NEW — WORM audit; `00 §5`, `08`)

Append-only, tamper-evident chain. Every red action, blue verdict, and response
gets one record; `this_hash` links to `prev_hash` so any edit breaks the chain.

```jsonc
EvidenceRecord = {
  "seq":           123,                    // monotonic per store
  "ts":            <epoch>,
  "engagement_id": "eng-t01-20260805-ab12",
  "tenant_id":     "t01",
  "actor":         "vigil",               // red | vigil | coordinator | human | sensor
  "record_type":   "blue_finding",        // red_action|red_finding|sensor_alert|blue_finding|
                                          // detection|decision|response|kg_annotation|scorecard
  "ref": {                                 // pointer(s) into the source-of-truth stores
     "finding_id":  "f-20260805-<sha256_16>",
     "action_id":   null,
     "kg_node_id":  null,
     "event_ts":    null
  },
  "payload_hash":  "sha256:<hex>",         // sha256 of the canonical (sorted-key) payload
  "prev_hash":     "sha256:<hex>",         // this_hash of seq-1 (genesis = 64 zeros)
  "this_hash":     "sha256:<hex>"          // sha256(prev_hash + payload_hash + seq + ts + record_type)
}
```
- **RoE provenance link:** `roe_ref` in the `Engagement` (§6.1) points at
  Decepticon's `plan/roe.json` bundle
  (`EngagementBundle.save` layout, `engagement.py:1031-1081`); its
  `machine_enforcement` block (`roe.py:100-114`) is the enforceable scope the
  decision record's `roe_decision` is computed from
  (`roe.py:evaluate_target/command/time_window`).
- Chain verification, WORM storage backend, and the kill switch are specified in
  `08`; this doc fixes only the record shape so producers agree on it now.

---

## 8. ID & correlation strategy (red action ↔ blue detection ↔ response)

**The join problem:** Vigil has **no** engagement/tenant/technique columns (§1.5),
so correlation keys must be *carried inside* the finding and *reconstructed* by the
coordinator. Four keys, in priority order:

| Key | Red side (source of truth) | Blue side (where it lands) |
|---|---|---|
| **`engagement_id`** | KG `node.engagement` (`store.py`); `events.jsonl` path; `Engagement` (§6.1) | `entity_context.engagement_id` **and** `cluster_id` (indexed) **and** encoded in `external_id` (§2) |
| **`technique`** (ATT&CK `T####`) | `Finding.mitre[]`; KG `Technique` node; `AttackPathStep.mitre` | `mitre_predictions` keys (technique-ID form, §1.4); blue conclusions in `ai_enrichment` |
| **`target entity`** (IP/host) | `Finding.affected_target`; KG `Host`/`Service` label; `AttackPathStep.target` | `entity_context.dst_ip`/`src_ip`/`affected_target` |
| **`timestamp window`** | `events.jsonl.ts`; `Finding.discovered_at`; KG `lastupdated` | `finding.timestamp` (event time), `created_at` (ingest time) |

**Correlation rule (coordinator, §6/§7):** a blue finding *detects* a red action iff
```
blue.entity_context.engagement_id == red.engagement_id            // hard scope
AND technique ∈ (blue.mitre_predictions ∪ blue.ai_enrichment.techniques)
                 ∩ red.mitre                                       // technique match
AND target_entity matches (blue.entity_context.{src_ip,dst_ip} ⊇ red.target)
AND |blue.timestamp − red_action_ts| ≤ CORRELATION_WINDOW          // default ≤ 15 min
```
- **Belt-and-suspenders for `data_source="decepticon"`:** the connector stamps
  `cluster_id = engagement_id` (cheap indexed engagement filter),
  `external_id = "{engagement_id}:{red_action_id}"` (idempotent dedup), and
  `entity_context.engagement_id` (authoritative). Independent-sensor findings
  (Wazuh/Suricata/Falco) carry `engagement_id` only in `entity_context` (set by the
  coordinator at scoring time via the timestamp window + target, since sensors don't
  know the engagement).
- **Chain:** `red_action (events.jsonl / KG)` → `blue_finding (findings)` →
  `detection (DetectionFired KG node + Scorecard.per_finding)` →
  `response (approval_actions.action_id)` → `evidence (EvidenceRecord.seq)`. Every
  hop carries `engagement_id` + `tenant_id`, giving a fully traceable purple loop
  and the per-tenant isolation `00 §10` requires.
- **MTTD/MTTR clocks** (§6.2): MTTD uses event-time (`finding.timestamp` −
  `events.jsonl.ts`); MTTR uses `approval_actions.executed_at` −
  `finding.timestamp`. Never mix ingest-time (`created_at`) into MTTD.

---

### Appendix A — File provenance index (every schema cited)

| Schema | File | Lines |
|---|---|---|
| Vigil finding ingest call | `vigil/services/ingestion_service.py` | 219-233 |
| Vigil finding id / hash width | `vigil/services/ingestion_service.py` | 38-40, 659-660, 840-841, 942-943 |
| `entity_context` conventions | `vigil/services/ingestion_service.py` | 53-60, 682-696, 887-906, 945-952 |
| `mitre_predictions` forms | `vigil/services/ingestion_service.py` | 31-36, 600-612, 663-666, 850-868 |
| `create_finding` signature | `vigil/database/service.py` | 49-98 |
| `Finding` ORM + unique index | `vigil/database/models.py` | 33, 62-145 |
| source-evidence envelope | `vigil/services/source_evidence.py` | (module) |
| `ActionType` + confidence gate | `vigil/services/approval_service.py` | 35-48, 185-213, 244-308 |
| `approval_actions` table | `vigil/database/init/13_approval_actions.sql` | 18-42 |
| KG `NodeKind`/`EdgeKind`/models | `Decepticon/.../decepticon_core/types/kg.py` | 46-256, 324-378 |
| KG engagement scope + provenance | `Decepticon/.../kg_internal/store.py` | 13-16, 182-187, 233, 252 |
| Decepticon `EventType`/`EngagementEvent` | `Decepticon/.../decepticon/runtime/event_log.py` | 87-130 |
| Decepticon `Finding`/`Evidence`/`AttackPath` | `Decepticon/.../decepticon_core/types/engagement.py` | 115-234 |
| Decepticon `RoE`/`EngagementBundle` | `Decepticon/.../decepticon_core/types/engagement.py` | 257-330, 1005-1081 |
| Machine-enforceable RoE | `Decepticon/.../decepticon_core/types/roe.py` | 51-114, 259-371 |
| Engagement label regex | `Decepticon/.../decepticon_core/utils/engagement_scope.py` | 31-33 |
| Decepticon run-status models | `Decepticon/.../decepticon/mcp_server/models.py` | 30-144 |
