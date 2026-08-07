# 04 — Telemetry & Sensor Plane

> **Status:** Planning (pre-code). **Phase:** P2 (Sensor plane). **Owner:** Detection engineering.
> **Conforms to:** `00_MASTER_PLAN.md` (AUTHORITATIVE) — sensor choice §6, port map §4,
> networks §5, phase table §8. Deviations/gaps are flagged inline as **[Δ00]** and collected
> in the final "Conflicts with 00" section.
> **Depends on / defers to:** `05_DATA_CONTRACTS_AND_SCHEMAS.md` owns the exact field-level
> sensor→finding schema. This doc specifies *which* sensor fires, *how* the alert reaches Vigil,
> and *which* canonical fields get populated — but the byte-level mapping is 05's job.

---

## 0. Purpose & the one non-negotiable

The sensor plane is the reason RedBlue AI is a *purple* platform and not a red tool wired to a
blue tool. Per `00 §1` and `§10`, **blue must detect red from independent telemetry, not from red's
self-report.** Decepticon already emits `events.jsonl`, `FIND-*.md`, and a Neo4j attack graph —
that is *ground truth* (the answer key), consumed by the coordinator for scoring (`06`/`07`). It is
**not** the detection signal. The detection signal comes from sensors watching the **target**,
producing alerts that flow into Vigil as canonical findings, entirely out-of-band from Decepticon.

```
   RED (Decepticon Kali sandbox :9999)          <-- attacker, on range-net only
            │ attacks (nmap / sqli / c2 / container-exec / AD)
            ▼
   TARGET RANGE  ──────────────────────────────  <-- instrumented victim(s)
    ├─ Wazuh agent (HIDS/FIM/logcollector/rootcheck/auditd)     ── host view
    ├─ Suricata (af-packet on range-net choke point, EVE JSON)  ── network view
    └─ Falco (eBPF, syscalls of target containers/pods)         ── runtime view
            │ alerts
            ▼
   SENSOR PLANE  (telemetry/)
    Wazuh manager + indexer(OpenSearch) + dashboard
            │  two lanes (see §4)
            ▼
   BLUE (Vigil :6987)  ── canonical finding → daemon triage → 13 agents → (gated) response
            │
            ▼
   COORDINATOR (:8900) scores  attacked (red KG ground-truth)  vs  detected (blue findings)
```

---

## 1. Sensor deployment (`telemetry/docker-compose.telemetry.yml`)

### 1.1 What each sensor is and *where it sits relative to the target*

The cardinal rule: **sensors instrument the TARGET, not Decepticon.** Optionally we *also* watch the
Kali sandbox to observe red tooling, but coverage is scored on target-side telemetry only.

| Sensor | Role (00 §6) | Sits where | Sees | Emits | License |
|---|---|---|---|---|---|
| **Wazuh** (manager + indexer + dashboard) | Host HIDS/FIM | central, on `telemetry-net` | agent-forwarded host events | alerts in `wazuh-alerts-*` (OpenSearch) + integrator hooks | GPLv2 |
| **Wazuh agent** | host sensor | **on every target host/VM/docker-host** | FIM, auth/sudo, auditd, rootcheck, app logs (nginx/apache/php/mysql), Sysmon (Windows) | events → manager (1514/tcp) | GPLv2 |
| **Suricata** | Network IDS | **choke point on `range-net`** (af-packet, promisc) | Kali→target + target→C2 + lateral | `eve.json` (EVE JSON) | GPLv2 |
| **Falco** | Container/K8s runtime | **on the container host / each K8s node** (eBPF probe) | syscalls of target workloads | JSON alerts → Falcosidekick | Apache-2.0 |
| **Falcosidekick** | Falco fan-out | co-located with Falco | — | Kafka / webhook out | Apache-2.0 |

Suricata has **no host-exposed port** (it passively sniffs a mirror and writes to disk) — which is
why `00 §4` lists no port for it. That is correct, not an omission.

### 1.2 Compose service inventory

`telemetry/docker-compose.telemetry.yml` (new, per `00 §3` layout — lives under `telemetry/`,
never edits the reused repos in place):

| Service | Image (pinned, official) | Host ports (00 §4) | Networks | Volumes |
|---|---|---|---|---|
| `wazuh.manager` | `wazuh/wazuh-manager` | `1514/1515` (agent), `55000` (API) | `telemetry-net`, `redblue-shared` | `wazuh_manager_data`, `wazuh_manager_etc` (rules/decoders/integrations) |
| `wazuh.indexer` | `wazuh/wazuh-indexer` (OpenSearch) | `9200` | `telemetry-net` | `wazuh_indexer_data` |
| `wazuh.dashboard` | `wazuh/wazuh-dashboard` | `8443`→443 (remapped, 00 §4) | `telemetry-net` | `wazuh_dashboard_config` |
| `suricata` | `jasonish/suricata` (or upstream) | none | `range-net` (see §1.3) | `suricata_logs` (eve.json), `suricata_rules` |
| `suricata.shipper` | `wazuh/wazuh-agent` (sidecar) | none | `telemetry-net` | mounts `suricata_logs` read-only |
| `falco` | `falcosecurity/falco` | none (gRPC `5060` optional, 00 §4) | host pid/net | host `/proc`, driver |
| `falcosidekick` | `falcosecurity/falcosidekick` | `2801` (internal only) | `telemetry-net`, `redblue-shared` | — |

Notes:
- **Wazuh** is deployed from the official single-node compose recipe (manager/indexer/dashboard),
  vendored as **image references only** — never fork the repo (license hygiene, §7).
- **Suricata shipper**: rather than teach Vigil to parse raw EVE, we mount `eve.json` into a
  co-located Wazuh agent that uses Wazuh's built-in Suricata decoders/rules. This funnels network
  alerts through the **same** Wazuh pipeline as host alerts (one connector to build, one MITRE map).
  See §4 for why Suricata routes through Wazuh rather than Filebeat→Elastic.
- **Falco** requires a kernel probe (modern eBPF preferred; kmod fallback) and runs privileged with
  host `/proc`. On K8s it is a DaemonSet; in the Docker demo it mounts `/var/run/docker.sock` +
  `/proc`. This is a real deployment constraint on the sovereign substrate (§8 risks).
- **Target range** lives in `telemetry/target-range/` (compose or a compose *profile*), §2.

### 1.3 The attack-path / network wiring problem **[Δ00]**

`00 §5` defines `telemetry-net` and says the Kali `sandbox-net` **"is never joined to
`redblue-shared`."** Good — but it does **not** define a network the *target range* lives on, and
Decepticon's Kali sandbox (which originates the attacks, from `sandbox-net`) must nonetheless be
able to *reach* the target for any of this to work. Resolution proposed here (flag to 00):

- Introduce **`range-net`** — the network the target range and Suricata's sniff interface share.
- The Kali sandbox joins **`range-net` as its ONLY additional attachment** (a deliberate, narrow
  attack path to the victim), and is **still not** on `redblue-shared`. This preserves 00's intent
  (Kali is isolated from the control plane) while giving red a route to the target.
- Suricata attaches to `range-net` in af-packet/promiscuous mode and therefore sees the full
  Kali→target→C2 conversation at the choke point.
- `wazuh.manager` and `falcosidekick` attach to **both** `telemetry-net` and `redblue-shared` so
  their *outbound* push can reach Vigil's backend (`:6987`) / Kafka (`:9092`). Nothing inbound is
  opened toward the sensors from red.

```
 sandbox-net ──(kali also joins)──▶ range-net ──[Suricata sniff]──▶ TARGET(s)
   (control-plane isolated)                                            │ wazuh-agent, falco
                                                                       ▼
                                              telemetry-net ── wazuh.manager/indexer/dashboard
                                                                       │ (manager + sidekick also on)
                                              redblue-shared ──────────┴──▶ Vigil :6987 / Kafka :9092
```

---

## 2. Target range

### 2.1 Options

| Range | Class | Exercises which Decepticon specialists | Primary sensor(s) | Effort | Sovereign-friendly |
|---|---|---|---|---|---|
| **DVWA** | Web (PHP/MySQL) | web recon, `contract_auditor`, SQLi/XSS/LFI/upload | Suricata (WEB sigs) + Wazuh (apache/php/mysql log rules) + Falco (if containerized) | **Low** | Yes (single container) |
| **OWASP Juice Shop** | Web (Node/SPA) | OWASP Top-10, `contract_auditor`, `analyst` | Suricata + Wazuh (nginx/node logs) + Falco | Low | Yes |
| **vulhub / per-CVE containers** | App CVEs | `reverser`, `contract_auditor`, exploit chain | Falco (exec/escape) + Suricata + Wazuh | Medium | Yes |
| **kubernetes-goat** (+ kind/k3s) | K8s cluster | **`cloud_hunter`**, container escape, IMDS/SSRF, RBAC abuse | **Falco (primary)** + Wazuh (node) + Suricata (pod net) | Med-High | Yes — closest to ESDS cloud |
| **GOAD** (Game of Active Directory) | AD lab (multi-Windows-VM) | **`ad_operator`** (kerberoast, ASREPRoast, DCSync, ACL abuse) | Wazuh + Sysmon (Windows) + Suricata (SMB/Kerberos) | **High** | Partial (Windows licensing + VM-heavy, not container-native) |
| metasploitable2/3 | Multi-service host | broad recon/exploit | Wazuh + Suricata | Medium | Yes |

### 2.2 Recommendation

- **v1 demo range (P2 exit, this doc):** **DVWA + one deliberately-vulnerable container** on a
  single Docker host, all three sensors on. Rationale: it gives a deterministic trip for *each*
  sensor class (Suricata scan sig, Wazuh web-log rule, Falco "terminal shell in container") and can
  prove the closed loop in a day. It is the smallest thing that exercises Suricata + Wazuh + Falco
  simultaneously.
- **Sovereign-cloud-representative range (phase after v1, feeds P7/P8):**
  **kubernetes-goat on a small k3s** (for `cloud_hunter` + Falco — the true ESDS-substrate story),
  paired with a **lightweight AD lab** for `ad_operator`. Because GOAD's Windows/VM footprint
  conflicts with the container-first, sovereign posture, prefer a **Samba-AD / Linux-AD emulation**
  first (kerberoast/DCSync coverage at the cost of some realism) and only stand up full GOAD if a
  customer scenario demands Windows fidelity. **[Δ00: 00 has no target-range spec — this section is
  the proposal; needs a row/note back in 00 §5/§6.]**

### 2.3 How the target is instrumented

- **Host/VM targets:** install the **Wazuh agent** (FIM on `/etc`,`/bin`,`/usr/bin`, webroot;
  `auditd` + Sigma-style rules; `rootcheck`; logcollector tailing app logs). Enroll to
  `wazuh.manager:1514`.
- **Containerized targets:** Wazuh agent on the **docker host** (watches docker events + host FIM);
  **Falco** watches the target containers' syscalls (not the Kali sandbox by default).
- **K8s targets:** Falco DaemonSet per node; Wazuh agent on nodes; Suricata on the pod bridge/CNI
  mirror.
- **Network:** Suricata reads `range-net` at the choke point (af-packet), `HOME_NET` scoped to the
  range CIDR so scan/ingress/egress direction logic is correct.
- **AD targets:** Sysmon + Windows Security channel forwarded by the Wazuh agent; Wazuh ships
  Sysmon/Sigma decoders for Kerberos/NTLM/DCSync-ish events.

---

## 3. Coverage mapping (kill-chain → sensor → expected alert)

Decepticon's specialists (`decepticon-architecture`) and the standard kill chain map to sensors as
follows. "Ground truth" for scoring always comes from Neo4j `DETECTION_FIRED`/`DETECTED` +
`events.jsonl` (`06`); this table is the *independent* detection side.

| Kill-chain step / specialist | Red action (via Kali `bash`/tools) | Sensor that catches it | Expected alert | Canonical `data_source` |
|---|---|---|---|---|
| **Recon / scanning** (all) | `nmap -sV`, `httpx`, `nuclei`, `masscan` | **Suricata** | ET SCAN (`2010935`+ port-scan), `nuclei`/`nmap` UA WEB sigs; Wazuh apache/nginx 404-burst rules | `suricata` |
| **Web exploit / initial access** (`contract_auditor`, web) | SQLi/XSS/LFI/RCE vs DVWA/Juice Shop | **Suricata** (ET WEB_SERVER SQLi/XSS) + **Wazuh** (web-log rules 31100–31599, mod_security) | web-attack alert w/ URI + payload | `suricata` / `wazuh` |
| **Privilege escalation** (linux) | sudo abuse, SUID, kernel exploit | **Wazuh** | rule groups: `syscheck`/`rootcheck`, auditd `execve`, "new sudoers/SUID" FIM, `sudo` auth rules | `wazuh` |
| **Persistence** | cron, systemd unit, authorized_keys, new user | **Wazuh** | FIM on `/etc/cron*`,`/etc/systemd`,`~/.ssh`; rule 5902/5901 new-user; 510xx rootcheck | `wazuh` |
| **Container escape** (`cloud_hunter`) | `docker exec`, breakout, mount host FS | **Falco** | default rules: *Terminal shell in a container*, *Launch privileged container*, *Change thread namespace*, *Write below /etc* | `falco` |
| **Cloud metadata / IMDS SSRF** (`cloud_hunter`) | curl `169.254.169.254` from pod | **Falco** (`Contact EC2/cloud IMDS`) + **Suricata** (link-local egress) | IMDS-contact runtime alert | `falco` |
| **C2 beaconing** | `ops_start c2-sliver`/`c2-havoc`, implant callback | **Suricata** (C2/ET MALWARE beacon sigs, JA3 anomaly, periodicity) + **Wazuh** (netstat/process rootcheck) | C2/beacon alert on egress | `suricata` |
| **Lateral movement** | SMB, SSH, WinRM, pivot | **Suricata** (internal scan/SMB) + **Wazuh** (auth/ssh 5710x, Windows 4624/4625) | lateral-auth / internal-scan alert | `suricata` / `wazuh` |
| **AD attacks** (`ad_operator`) | kerberoast, ASREPRoast, DCSync, ACL abuse | **Wazuh** (Sysmon/Windows Security: 4769 RC4 tickets, 4662 DS-Replication, 4768) + Suricata (Kerberos/DRSUAPI, limited) | Kerberos/DCSync rule | `wazuh` |
| **Exfiltration** | large egress, DNS tunneling | **Suricata** (ET exfil, DNS-tunnel sigs, byte-count anomaly) | exfil/DNS-tunnel alert | `suricata` |
| **Defense evasion** (log clearing) | `rm`/truncate logs, history tamper | **Wazuh** (FIM on log paths, "log cleared" 5104x, auditd) + **Falco** (write below `/var/log`) | tamper alert | `wazuh` / `falco` |

### 3.1 Blind spots (flagged — not covered by Wazuh/Suricata/Falco)

| Blind spot | Why | Compensating control |
|---|---|---|
| **LLM-layer attacks** (prompt injection vs the AI surface; Decepticon fingerprints Ollama/vLLM/LiteLLM `Technology` nodes) | Not a host/net/syscall event | **`vigil-llm` MCP** defense (`08`), not this plane |
| **Phishing** (`phisher`) | No mail target in a self-contained range | Out of scope for v1; needs a mail victim + mailflow sensor |
| **Wireless / mobile / IoT / ICS** (`wireless/mobile/iot/ics_operator`) | No RF/radio/fieldbus telemetry | Documented residual gap; specialist-specific sensors are future work |
| **Encrypted C2 over valid-cert TLS** (Sliver/Havoc HTTPS, domain-fronting) | Suricata can't read payload | Fall back to JA3/JA4 + beacon periodicity heuristics **and** host-side Wazuh/Falco process detection |
| **In-memory / fileless** | Weak for FIM | Falco (syscall) if containerized; auditd/Sysmon via Wazuh otherwise |
| **Cloud control-plane** (real CloudTrail/K8s audit at scale) | Sovereign lab lacks real cloud API log volume | Simulate via K8s audit log → Wazuh; CART `ChangeEvent` is red-side only |

---

## 4. Alert → Vigil flow (the wiring decision)

### 4.1 Verified constraints from Vigil's code (this is the load-bearing part)

I traced the ingestion path. Findings that drive the decision:

1. **Canonical sink** — every path ultimately calls
   `services/ingestion_service.py :: IngestionService.ingest_finding(dict)`, which requires a
   `finding_id`, dedups on it (DB `get_finding` existence check / `bulk_create_findings`), and
   writes the canonical finding (`embedding`, `mitre_predictions`, `anomaly_score`,
   `entity_context`, `data_source`, `severity`, `status`, …). All connectors converge here.
2. **SIEM pull base** — `services/siem_ingestion_service.py :: SIEMIngestionService(ABC)` gives
   `fetch_alerts()` + `transform_alert_to_finding()` + `normalize_severity()` + `extract_entities()`
   + upstream status sync. Concrete pull sources (`elastic_ingestion.py`, Sentinel, etc.) subclass
   it and are driven by the daemon via `daemon/federation/adapters/_siem_base.py`
   (`SIEMIngestionAdapter`, cursor-based, `register_adapter(...)`, **default interval 300 s**).
3. **⚠ Vigil's Elastic connector is NOT drop-in for Wazuh.** `services/elastic_service.py`
   fetches alerts via the **Kibana Detections API** (`POST /api/detection_engine/signals/search`)
   and **requires `kibana_url`**; `elastic_ingestion.py` reads the Elastic Security signals index
   `.alerts-security.alerts-default` and parses ECS/`kibana.alert.*` fields. **Wazuh's indexer is
   OpenSearch with no Kibana Detection Engine and a different alert schema (`wazuh-alerts-*`).** So
   option (a) below cannot reuse `ElasticIngestion` as-is. *However*, `ElasticService.search()` is a
   plain `_search` against **any** index — reusable for a new Wazuh connector.
4. **Inbound webhook receiver pattern exists** — `backend/api/darktrace_webhook.py` is the clone
   target: raw-body read, **HMAC-SHA256** verify (`X-*-Signature`), size cap, `transform → 
   IngestionService.ingest_finding`, `202 Accepted`. Mounted **gated** at
   `/api/webhooks/darktrace/*` (only when enabled) via `backend/main.py`.
5. **Fast generic ingest endpoints** — ingestion router is mounted at **`/api/ingest`**, so
   `POST /api/ingest/ingest-string` (form: `data`,`format=json`,`data_type=finding`) and batch
   `POST /api/ingest/upload` work today. (`backend/api/webhooks.py` is *only* outbound case-event
   webhook config — TODO stubs — **not** an inbound ingest receiver.)
6. **Kafka lane is first-class and already names Falco** — `docs/KAFKA_INGESTION.md`: JSON messages
   need only `finding_id`; everything else passes through to `ingest_finding`; `data_source`
   defaults to `kafka:<topic>`; Redis-backed dedup (24 h window). The doc explicitly lists **Falco**
   as a supported producer. Broker: host `:9092`, internal `kafka:29092`, `kafka` compose profile.
7. **`vstrike` inbound** (`/api/integrations/vstrike/findings`, Bearer `VSTRIKE_INBOUND_API_KEY`) is
   an **enrichment-merge** path (`data_source="vstrike"`, read-modify-write on `entity_context`),
   semantically wrong for a *new sensor* finding — don't use it as the sensor sink.

### 4.2 Decision

**Two lanes, chosen per sensor by latency need and least-build:**

| Sensor | Chosen path | Why |
|---|---|---|
| **Wazuh** (host) | **PUSH:** Wazuh **Integrator** (`ossec.conf <integration>` + custom script) → new gated receiver **`POST /api/webhooks/wazuh`** (clone `darktrace_webhook.py`, HMAC) → `WazuhIngestionService.transform_alert_to_finding` → `ingest_finding`. **PLUS backfill PULL:** new `WazuhIndexerIngestion(SIEMIngestionService)` reusing `ElasticService.search()` against `wazuh-alerts-*` + `register_adapter("wazuh", …)`. | Push = seconds not minutes → **MTTD is a scored metric** (`07`). Poll adapter reconciles anything the push dropped and lets agents do IOC search over `wazuh-alerts-*`. |
| **Suricata** (network) | **Funnel through Wazuh:** `eve.json` → co-located Wazuh agent (native Suricata decoders) → same Wazuh push/pull lanes. `data_source` set to `suricata` when the Wazuh rule group marks it IDS/Suricata. | One connector, one MITRE map, reuses Wazuh's aggregation. Avoids teaching Vigil to parse raw EVE. |
| **Falco** (runtime) | **Kafka:** Falco → **Falcosidekick** (native Kafka output) → topic `security.findings` → Vigil Kafka consumer. Sidekick shapes: `finding_id = sha1(rule+output_fields+time)`, priority→severity, Falco `tags`→`mitre_predictions`. | `KAFKA_INGESTION.md` already blesses Falco→Kafka; low-latency; keeps high-volume runtime events off the host-centric Wazuh funnel. Sidekick can *also* fan out to a webhook if Kafka is deferred. |

**Why push over Vigil's default poll for Wazuh:** the shipped SIEM adapters poll at 300 s
(`_siem_base` default). For a closed loop that scores MTTD/MTTR, a 0–5 min blind window is
unacceptable; the Integrator emits on alert. We keep the poll adapter, but tune its interval down
(30–60 s) and treat it as reconciliation/backfill, not the primary path.

**Why not "Wazuh indexer → Vigil Elastic connector" (option a):** as verified in §4.1(3), Vigil's
`ElasticIngestion` is bound to the Kibana Detection Engine and Elastic Security's signal schema,
neither of which Wazuh's OpenSearch indexer provides. Using it would mean pointing Vigil at a
Kibana that doesn't exist. The reusable piece is only `ElasticService.search()` (plain `_search`),
which the new `WazuhIndexerIngestion` wraps — so we get the SIEM-base benefits (cursor, dedup via
`(data_source, external_id)` unique index, batching) without the Kibana dependency.

### 4.3 Concrete pipelines

```
WAZUH (host) + SURICATA (via Wazuh):
  agent/eve.json ─▶ wazuh.manager ─▶ rule engine
     ├─(push, primary)  Integrator script ──HTTPS+HMAC──▶ POST /api/webhooks/wazuh
     │                                      └─ WazuhIngestionService.transform_alert_to_finding
     │                                         └─ IngestionService.ingest_finding ─▶ Postgres/pgvector
     └─(pull, backfill)  wazuh-alerts-* (OpenSearch :9200)
                          ◀── daemon SIEMIngestionAdapter("wazuh") every 30–60s
                              └─ WazuhIndexerIngestion(ElasticService.search) ─▶ ingest_finding

FALCO (runtime):
  falco ─▶ falcosidekick ──Kafka(security.findings)──▶ Vigil kafka consumer ─▶ ingest_finding
                         (data_source=falco; Redis dedup 24h)

Both lanes land as CANONICAL FINDINGS ─▶ daemon processor (store-first) ─▶ triage/enrich ─▶ 13 agents
```

**Field mapping (sketch only — exact schema is DOC 05):** each transform populates —
`finding_id` (stable/idempotent per §5 dedup), `data_source ∈ {wazuh, suricata, falco}`,
`timestamp`, `severity` (from rule level/priority, §5), `anomaly_score`, `mitre_predictions`
(from Wazuh `rule.mitre.id` / Falco `tags` / Suricata metadata → `{Txxxx: score}` **or** `[Txxxx]`;
both accepted by `ingest_finding`), `entity_context` (attacker IP = Kali sandbox, target IP/host,
user, container/pod, rule id, raw-log ref), `evidence_links` (pointer to raw Wazuh/EVE/Falco line).
**Entity-key convention (resolved by 05 §1.3 — singular is canonical):** the correlator reads the
**scalar** keys `src_ip`/`dst_ip`, so every sensor transform MUST populate those. Vigil's native
SIEM/Kafka paths also carry *plural-list* forms (`src_ips`,`dest_ips`,`hostnames`,`usernames`) —
transforms MAY additionally include them, and 05's correlator normalizes plural→scalar
(`src_ip or src_ips[0]`). Do **not** rely on the plural list alone.

### 4.4 New code (all additive per `00 §3`, captured as engine patches in `06`)

- Vigil (Apache-2.0 repo): `services/wazuh_ingestion.py` (`WazuhIngestionService`,
  `WazuhIndexerIngestion`), `backend/api/wazuh_webhook.py` (gated router, mount in `main.py` like
  Darktrace), `daemon/federation/adapters/wazuh.py` (`register_adapter`). Falco needs **no** Vigil
  code — it rides the existing Kafka consumer; only a Falcosidekick config + a tiny shaping template.
- `telemetry/`: Wazuh custom rules/decoders + `integrations/custom-vigil` integrator script,
  Suricata `suricata.yaml` + ruleset, Falco `falco.yaml` + `falcosidekick.yaml`.

---

## 5. Tuning (noise, rule packs, severity, dedup)

**Rule packs**
- *Wazuh:* enable Suricata/IDS decoders, Sysmon + Sigma (Windows/Kerberos), Docker/rootcheck,
  auditd. Ship a small **RedBlue rule pack** in `telemetry/wazuh/` mapping range-specific paths
  (webroot FIM, app logs). Set the manager's **MITRE** enrichment on so `rule.mitre.id` is
  populated (feeds `mitre_predictions`).
- *Suricata:* ET Open ruleset; scope `HOME_NET` to `range-net`; disable chatty policy/info
  categories; keep SCAN/WEB_SERVER/MALWARE/EXPLOIT/CURRENT_EVENTS; use `flowbits`/`threshold` to
  fold scan floods into one alert.
- *Falco:* start from the default ruleset; add macros to allowlist the *target's own* benign
  exec/writes (baseline first, then attack) to kill false positives; keep the escape/IMDS/priv/
  shell-in-container rules hot.

**Forward-threshold (the main noise lever)** — don't forward everything to Vigil:
- Wazuh Integrator `<integration>` block filters by **`<level>`** (forward only level ≥ 5),
  **`<rule_id>`**, **`<group>`**. Info/level-0–4 stay in the indexer for enrichment but don't create
  findings.
- Falcosidekick `minimumpriority: notice` (drop Debug/Informational before Kafka).
- Suricata: only alerts (not flow/stats) reach Wazuh; `eve.json` `flow`/`stats` types excluded from
  the shipper.

**Severity mapping (→ `severity` + `anomaly_score`; 05 finalizes)**

| Source scale | → Vigil `severity` |
|---|---|
| Wazuh level 12–15 / Suricata sev 1 / Falco Emergency-Critical | `critical` |
| Wazuh 8–11 / Suricata sev 2 / Falco Error | `high` |
| Wazuh 4–7 / Suricata sev 3 / Falco Warning | `medium` |
| Wazuh 0–3 / Suricata sev 4 / Falco Notice-Info | `low`/`info` |

`SIEMIngestionService.normalize_severity()` already coerces most string/number forms; transforms
should set an explicit `anomaly_score` (e.g. `level/15`, Suricata `1→0.9…4→0.4`) so the daemon's
high-signal fork (`00`/vigil-architecture) triggers appropriately.

**Dedup / aggregation (3 layers)**
1. *Sensor-side:* Wazuh aggregates repeats; Suricata `threshold`; Falco rate-limits.
2. *Idempotent id:* stable `finding_id` in the canonical `f-<YYYYMMDD>-<sha256_16>` form (05/00 §7;
   `ID_HASH_WIDTH=16`, sha256 — the sha1_8 form was abandoned). Wazuh: `sha256(rule_id|agent_id|full_log)[:16]`
   and set `external_id = Wazuh alert id` so the `(data_source, external_id)` UNIQUE index dedups the
   poll adapter; Suricata: seed from EVE `flow_id`; Falco: `sha256(rule|output_fields|ts)[:16]`.
3. *Ingest-side:* `ingest_finding` skips existing ids; Kafka lane adds a Redis sorted-set dedup
   (`vigil:dedup:kafka`, 24 h). The coordinator further scopes/aggregates by **engagement window**
   (`05`/`06`) so cross-engagement crosstalk doesn't inflate detection counts.

---

## 6. Acceptance test (P2 exit)

**Exit criterion (00 §8, P2):** *"Target range instrumented; Wazuh/Suricata/Falco alert → Vigil
finding."* Concretely: run **one** Decepticon action → a sensor fires → a canonical Vigil finding
appears, correctly attributed, within N seconds.

### 6.1 Setup
1. `docker compose -f telemetry/docker-compose.telemetry.yml up -d` (Wazuh manager/indexer/
   dashboard, Suricata on `range-net`, Falco+sidekick).
2. Bring up the v1 target (DVWA + one vuln container) on `range-net`; Wazuh agent enrolled; Suricata
   `HOME_NET` = range CIDR; Falcosidekick → Kafka `security.findings`.
3. Vigil up with the `kafka` profile; new `wazuh_webhook` router enabled + `WAZUH_WEBHOOK_SECRET`
   set; daemon running.

### 6.2 Three deterministic triggers (one per sensor class)

| # | Red action (from Kali sandbox `bash`) | Sensor | Expected |
|---|---|---|---|
| A (simplest, most deterministic) | `docker exec <target-container> /bin/bash` | **Falco** | *Terminal shell in a container* → sidekick → Kafka → finding `data_source=falco` |
| B | `nmap -sV -p- <target>` | **Suricata** | ET SCAN → Wazuh → push → finding `data_source=suricata` |
| C | SQLi on DVWA (`' OR 1=1-- -`) | **Suricata**/**Wazuh** | WEB_SERVER SQLi + apache-log rule → finding |

### 6.3 Verification procedure (per trigger)
```bash
# 1. Sensor fired?
#   Falco:    docker logs falco | grep "Terminal shell"
#             docker logs falcosidekick | grep -i kafka   # output OK
#   Wazuh:    docker exec wazuh.manager tail -f /var/ossec/logs/alerts/alerts.json
#             docker exec wazuh.manager tail -f /var/ossec/logs/integrations.log  # integrator POST
#   Suricata: docker exec suricata tail -f /var/log/suricata/eve.json | grep '"event_type":"alert"'

# 2. Reached Vigil? (finding exists)
curl -s 'http://localhost:6987/api/findings?data_source=falco&limit=5'   | jq '.[].finding_id'
curl -s 'http://localhost:6987/api/findings?data_source=suricata&limit=5' | jq '.'

# 3. Kafka lane counters (Falco)
curl -s http://localhost:9091/status | jq .kafka   # messages_consumed / enqueued

# 4. Ground-truth in DB
docker exec deeptempo-postgres psql -U deeptempo -d deeptempo_soc \
  -c "SELECT finding_id,data_source,severity,mitre_predictions,entity_context->>'src_ips'
      FROM findings WHERE data_source IN ('wazuh','suricata','falco')
      ORDER BY created_at DESC LIMIT 5;"

# 5. Daemon triaged it? (status advanced off 'new', ai_enrichment present)
```

**PASS =** for each trigger, a canonical finding exists with (a) correct `data_source`, (b)
`entity_context` carrying attacker IP (= Kali sandbox) and target IP/host/container, (c) a MITRE
mapping, (d) `severity` per §5, (e) daemon picked it up — all within the target latency (push:
< ~10 s; Kafka: < ~5 s; poll backfill: ≤ interval). Trigger **A** is the recommended one-command
smoke test for CI/demo because it is fully deterministic and touches the whole Falco→Kafka→finding
lane without network timing variance.

**Not in P2 scope (defer to P4):** the coordinator's *attacked-vs-detected* scorecard — P2 only
proves telemetry produces findings.

---

## 7. License note

| Component | License | Handling (per `00 §6` "license hygiene") |
|---|---|---|
| **Wazuh** (mgr/indexer/dashboard/agent) | **GPLv2** | **Arm's-length:** deploy **official images unmodified**; never fork-and-redistribute. Integration is process-boundary only (HTTP webhook / Kafka / `_search` over a socket) = *mere aggregation*, not a derivative work. |
| **Suricata** | **GPLv2** | Same. We only consume its `eve.json` output file; no linking. |
| Wazuh custom rules/decoders + integrator script | (config/data) | Configuration & data files, not GPL-linked code. Keep in `telemetry/` as deploy artifacts; the integrator script is a thin data-shipper (safe to license Apache-2.0 to match the repo). |
| **Falco** + **Falcosidekick** | **Apache-2.0** (CNCF) | No friction — compatible with our Apache-2.0 coordinator/new code. |
| New Vigil-side connectors (`wazuh_ingestion.py`, `wazuh_webhook.py`, adapter) | Apache-2.0 (vigil repo) | They call GPL software **over a socket/HTTP**, so they are **not** derivatives of Wazuh/Suricata. Ship as additive patches (`06`), never by vendoring GPL source into the Apache tree. |

**Hard rule:** Wazuh/Suricata enter the monorepo **only as pinned image references** in the compose
file. No GPL source is copied into `telemetry/`, `vigil/`, or `redblue-coordinator/`. (Reinforces
`00 §6` and `redblue-integration-gotchas`.)

---

## 8. Risks

| # | Risk | Impact | Mitigation |
|---|---|---|---|
| 1 | **Vigil's Elastic connector ≠ Wazuh** (Kibana Detection-Engine dependency; OpenSearch schema differs) | The "reuse Elastic ingestion" assumption is false — must build a new connector | Build `WazuhIngestionService` + webhook; reuse only `ElasticService.search()`. Primary integration cost of P2. |
| 2 | **Poll latency vs MTTD** (SIEM adapter default 300 s) | Blind window skews the scorecard | Push via Integrator (primary); poll interval 30–60 s as backfill only. |
| 3 | **Sensor noise** (00 §11 #5) | Findings flood the daemon; cost guardrails abort | Forward-thresholds (Wazuh `<level>≥5`, Falco `minimumpriority`, Suricata categories); 3-layer dedup; baseline Falco allowlists before attacking. |
| 4 | **Attack-path vs sandbox isolation** [Δ00] | Kali can't reach target *or* isolation rule is violated | Introduce `range-net`; Kali joins it as its only extra attachment, still off `redblue-shared`. Needs sign-off into 00 §5. |
| 5 | **Kafka `:9092` not in 00 port map** [Δ00] | Undocumented host port; possible future collision | Add Kafka host `9092` / internal `kafka:29092` to 00 §4 (blue stack). |
| 6 | **`entity_context` schema drift** (plural-list vs singular) | Blue agents/correlator mis-read attacker/target IPs | Standardize on 05's **singular** canonical (`src_ip`/`dst_ip`); optionally also emit `src_ips`/`dest_ips` lists; the correlator normalizes plural→scalar (05 §1.3/§8). |
| 7 | **Falco privileged/kernel access** | Blocked on hardened/managed sovereign nodes (no eBPF/kmod) | Prefer modern-eBPF; validate on ESDS node images early; DaemonSet + PSP/PSA exceptions documented. |
| 8 | **Wazuh indexer is JVM-heavy (OpenSearch)** | RAM/CPU footprint on the lab host | Single-node profile; size in `02`; consider `wazuh-alerts` retention/ILM caps. |
| 9 | **Encrypted C2 evades Suricata** | C2 step under-detected | JA3/JA4 + beacon-periodicity sigs + host-side Wazuh/Falco process detection; document residual gap. |
| 10 | **GOAD Windows footprint vs sovereign/container posture** | AD realism costs VM/licensing | Samba/Linux-AD emulation first; full GOAD only on demand. |
| 11 | **Blind-spot specialists** (phisher/wireless/mobile/iot/ics, LLM-layer) | Coverage gaps look like "red won" | Explicitly scope out of P2; LLM-layer covered by `vigil-llm` (`08`); document residual in the scorecard so gaps are visible, not silent. |
| 12 | **Self-signed TLS on Wazuh indexer** | Poll adapter TLS failures | `verify_ssl=False` for the lab indexer (ElasticService supports it); real certs for prod. |

---

## 9. Deliverables & next docs

- `telemetry/docker-compose.telemetry.yml` + `telemetry/{wazuh,suricata,falco,target-range}/` configs.
- Vigil additive patches: `WazuhIngestionService`/`WazuhIndexerIngestion`, `/api/webhooks/wazuh`
  gated router, `register_adapter("wazuh")` — enumerated as a patch in **`06`**.
- Falcosidekick→Kafka shaping template (no Vigil code).
- **05** finalizes the sensor→finding field schema (severity/MITRE/entity_context/idempotent id).
- **06** captures the engine patch set + the shared-KG ground-truth read for scoring.
- **07** consumes these findings for MTTD/MTTR/detection-rate scoring.

---

## Conflicts with 00 (flagged back per the conformance rule)

1. **No `range-net` / target-range network in 00 §5** — 00 isolates `sandbox-net` from
   `redblue-shared` but never defines how Kali reaches the target or where the range lives. This doc
   proposes `range-net` (Kali joins it as its only extra attachment, still off `redblue-shared`).
   **Needs a note/row in 00 §5.**
2. **Kafka host port `9092` absent from 00 §4** — the Falco lane (and any future stream lane) rides
   Vigil's Kafka broker. Add host `9092` / internal `kafka:29092` (blue stack) to the port map.
3. **No target-range spec in 00 §6** — 00 names the sensors but not the range. §2.2 proposes v1 =
   DVWA + vuln container, sovereign = kubernetes-goat + Linux-AD. Suggest recording the choice in 00.
4. **Implicit "reuse Vigil Elastic ingestion for Wazuh" is invalid** — not stated in 00 but implied
   by `redblue-integration-seams`; corrected here (Kibana Detection-Engine dependency). No 00 text
   change needed, but 05/06 must not assume the Elastic connector covers Wazuh.

All other decisions conform to 00: sensor choice (§6), ports 9200/8443/1514-1515/55000/5060 (§4),
networks `telemetry-net`/`redblue-shared`/`range-net` (§5), phase P2 (§8), naming
(`f-<YYYYMMDD>-<sha256_16>`, `data_source`), Apache-2.0 new code + GPL arm's-length (§6).
