# 02 — Infra: Docker Compose Topology, Ports, Networks, Bring-up

> **Status:** Planning (pre-code). **Conforms to:** `00_MASTER_PLAN.md` (AUTHORITATIVE) — port map §4,
> networks §5, phases §8. **Scope:** how the three reused stacks + the two new stacks
> (`telemetry/`, `redblue-coordinator/`) come up together, share exactly one bus, keep their
> private nets, and never collide on a host port.
> **This is a PLAN with representative skeletons — not final production compose.** Every YAML block
> below is illustrative and labelled as such; the real files land in P0/P2/P4 per §8 of `00`.
>
> **Conflicts flagged back to `00` (details in §10):**
> 1. `00 §3` describes `deploy/docker-compose.redblue.yml` as a *single* "top-level override wiring
>    all stacks." A single merged project is **infeasible**: both Decepticon and Vigil define a
>    service literally named `postgres`, and Compose merges same-key services across every `-f`/`include`
>    into one broken service. **Resolution:** multi-project topology (one `docker compose` *project* per
>    stack) joined by a shared *external* network. The `deploy/` file becomes the coordinator+shared-plane
>    project plus per-stack override fragments — not one god-file.
> 2. `00 §4` lists Decepticon web `3000→3100` and terminal `3003→3103` as remaps. Verified: these are
>    **not** true host collisions with Vigil (Vigil exposes nothing on host 3000/3003). They are 00-mandated
>    band moves (and both sit behind Decepticon's default-off `web` profile). Kept for conformance; noted as
>    precautionary, not collision-forced. The **only** always-on collision is Postgres `5432`; the only
>    conditional collision is `8081` (Decepticon BHCE vs Vigil daemon webhook).

---

## 1. Unified topology

### 1.1 The model: 4 projects, 1 shared bus, N private nets

We do **not** merge the stacks into one Compose project. Instead:

- Each stack runs as its **own Compose project** (`-p <name>`): `decepticon`, `vigil`, `telemetry`,
  `coordinator`. This keeps each stack's `postgres`/`redis`/`neo4j` service names, volumes, and
  container names isolated (they are project-scoped) and lets each keep its own `.env`, its own
  relative build contexts, and its own `depends_on` graph **unmodified**.
- One **external** Docker network, `redblue-shared`, is the *only* cross-stack bus. It is created once
  (`docker network create redblue-shared`) and referenced by every project as `external: true`, so it is
  **not** project-prefixed and every stack sees the same bridge.
- Each stack keeps its **private** net(s) exactly as authored: `decepticon-net`, `sandbox-net` (Kali),
  `deeptempo-network` (Vigil), `telemetry-net`. Only a hand-picked set of services is *additionally*
  attached to `redblue-shared` via a thin override — nothing is moved off its private net.
- **`sandbox-net` is never attached to `redblue-shared`.** `c2-sliver` stays on `sandbox-net` only; the
  Kali `sandbox` additionally joins **`range-net`** — its *only* extra attachment — to reach the target
  range (per doc 04 / 00 §5), and is **still never** on `redblue-shared`. (Neo4j is dual-homed
  sandbox-net+decepticon-net in the base file; §3.4 covers the one extra hop and its hardening.)

```
 ┌───────────────────────────────────────── redblue-shared (external bridge) ─────────────────────────────────────────┐
 │                                                                                                                     │
 │   redblue-coordinator:8900   ──►  langgraph:2024        vigil backend:6987        ollama:11434       wazuh mgr:1514 │
 │   (coordinator project)           neo4j bolt:7687       vigil soc-daemon:8081(int) (shared plane)     suricata/falco│
 │                                   (decepticon project)  (vigil project)                               (telemetry)   │
 └───────┬───────────────────────────────┬─────────────────────────┬───────────────────────────┬────────────────────┘
         │ redblue-shared only            │ +decepticon-net          │ +deeptempo-network         │ +telemetry-net
   ┌─────▼─────┐                    ┌─────▼───────────────────┐ ┌────▼─────────────────────┐ ┌────▼─────────────────────┐
   │coordinator│                    │  DECEPTICON project      │ │  VIGIL project           │ │  TELEMETRY project        │
   │ + evidence│                    │  litellm postgres neo4j  │ │  postgres redis backend  │ │  wazuh-indexer/mgr/dash   │
   │  (sqlite) │                    │  langgraph skillogy      │ │  soc-daemon llm-worker   │ │  suricata falco           │
   └───────────┘                    │  web(cli/web) bhce(ad)   │ │  bifrost (obs/splunk/..) │ │  target-range             │
                                    │                          │ └──────────────────────────┘ └──────────────────────────┘
                                    │   ┌──── sandbox-net (ISOLATED, never on redblue-shared) ────┐
                                    │   │  sandbox:9999   c2-sliver   (neo4j dual-homed in)        │
                                    │   └──────────────────────────────────────────────────────────┘
                                    └────────────────────────────────────────────────────────────────┘
```

### 1.2 `deploy/` layout (conforms to `00 §3`, refined per Conflict 1)

```
deploy/
├── docker-compose.redblue.yml        # NEW services only: redblue-coordinator + shared ollama + telemetry include; declares redblue-shared (external)
├── overrides/
│   ├── decepticon.redblue.yml         # attach litellm/langgraph/neo4j to redblue-shared; point LLM base at ollama
│   └── vigil.redblue.yml              # attach backend/soc-daemon to redblue-shared; !override soc-daemon ports (8081→8082); point OLLAMA_URL at ollama
├── env/
│   ├── decepticon.env                 # POSTGRES_PORT=5433, WEB_PORT=3100, TERMINAL_PORT=3103, DECEPTICON_STACK_NAME=…, OLLAMA base
│   ├── vigil.env                      # POSTGRES_PASSWORD, OLLAMA_URL=http://ollama:11434, DEV_MODE=false(before exposure)
│   └── shared.env                     # REDBLUE_*, OLLAMA_MODEL tiers (owned by doc 03)
├── .env.example
└── Makefile                           # the real orchestrator (§5) — sequences the 4 projects
```

`telemetry/docker-compose.telemetry.yml` lives under `telemetry/` (per `00 §3`) and is `include:`d by the
coordinator project (they share a lifecycle) or run as its own `-p telemetry` project (default — see §4).

### 1.3 Service inventory (host port per `00 §4`)

Legend — **Profile** blank = starts by default in its stack; **↔shared** = additionally attached to
`redblue-shared` via override. Host ports are what `00 §4` mandates (Decepticon binds them on `127.0.0.1`).

| # | Service (project) | Image | Host port (00 §4) | Internal | Network(s) | Profile | Named volumes | depends_on (healthy unless noted) |
|---|---|---|---|---|---|---|---|---|
| **RED — Decepticon (`-p decepticon`)** |
| 1 | litellm | `…/decepticon-litellm` | 4000 (127.0.0.1) | 4000 | decepticon-net, **↔shared** | — | (uses postgres) | postgres |
| 2 | postgres | `postgres:17-alpine` | **5433** (was 5432) | 5432 | decepticon-net | — | `postgres_data` | — |
| 3 | neo4j | `neo4j:5.26-community` | 7687 / 7474 | 7687/7474 | sandbox-net, decepticon-net, **↔shared** | — | `neo4j_data`, `neo4j_logs` | — |
| 4 | sandbox (Kali) | `…/decepticon-sandbox` | **none** | 9999 | **sandbox-net only** | — | (bind: workspace) | neo4j |
| 5 | langgraph | `…/decepticon-langgraph` | 2024 (127.0.0.1) | 2024 | decepticon-net, sandbox-net, **↔shared** | — | (bind: telemetry id) | litellm, sandbox(started), neo4j |
| 6 | skillogy | `…/decepticon-skillogy` | 9100 (127.0.0.1) | 9100 | decepticon-net | — | — | neo4j, litellm |
| 7 | web | `…/decepticon-web` | **3100** + **3103** | 3000/3003 | decepticon-net | `web` | (bind: workspace) | langgraph, postgres |
| 8 | cli | `…/decepticon-cli` | none (tty) | — | decepticon-net | `cli` | docker.sock, home bind | langgraph |
| 9 | ghidra-mcp | `decepticon-sandbox-reversing` | none | 8089 | sandbox-net | `reversing` | — | — |
| 10 | c2-sliver | `…/decepticon-c2-sliver` | none | — | **sandbox-net only** | `c2-sliver` | `sliver_data` | — |
| 11 | bhce-postgres-init | `postgres:17-alpine` | none | — | decepticon-net | `ad` | — | postgres |
| 12 | bhce-neo4j | `neo4j:4.4.48-community` | none | 7687/7474 | decepticon-net | `ad` | `bhce_neo4j_data`, `bhce_neo4j_logs` | — |
| 13 | bhce | `specterops/bloodhound` | **8081** | 8080 | decepticon-net | `ad` | — | postgres, bhce-postgres-init, bhce-neo4j |
| **BLUE — Vigil (`-p vigil`)** |
| 14 | postgres | `pgvector/pgvector:pg16` | **5432** (keeps) | 5432 | deeptempo-network | — | `postgres_data` | — |
| 15 | redis | `redis:7-alpine` | 6379 | 6379 | deeptempo-network | — | `redis_data` | — |
| 16 | backend | `Dockerfile.backend` | 6987 | 6987 | deeptempo-network, **↔shared** | — | — | postgres, redis, bifrost |
| 17 | soc-daemon | `Dockerfile.daemon` | **8082** + 9090 + 9091 | 8081/9090/9091 | deeptempo-network, **↔shared** | — | — | postgres, redis, bifrost |
| 18 | llm-worker | `Dockerfile.backend` | none | — | deeptempo-network | — | — | postgres, redis, bifrost |
| 19 | bifrost | `maximhq/bifrost:latest` | 8080 | 8080 | deeptempo-network | — | (bind: config.json) | redis |
| 20 | pgadmin | `dpage/pgadmin4` | 5050 | 80 | deeptempo-network | `dev` | `pgadmin_data` | postgres (started) |
| 21 | otel-collector | `otel/otel-collector-contrib` | 4317 / 4318 | 4317/4318 | deeptempo-network | `observability` | — | — |
| 22 | jaeger | `jaegertracing/all-in-one` | **16686** | 16686 | deeptempo-network | `observability` | — | — |
| 23 | prometheus | `prom/prometheus` | **9095** | 9090 | deeptempo-network | `observability` | `prometheus_data` | — |
| 24 | grafana | `grafana/grafana` | **3001** | 3000 | deeptempo-network | `observability` | `grafana_data` | prometheus (started) |
| 25 | splunk | `splunk/splunk` | 6990/8088/8089/9997 | — | deeptempo-network | `splunk` | `splunk_data`, `splunk_etc` | — |
| 26 | kafka | `apache/kafka:3.7.0` | 9092 | 9092/29092 | deeptempo-network | `kafka` | `kafka_data` | — |
| **SHARED plane (`-p coordinator` / deploy file)** |
| 27 | ollama | `ollama/ollama` | **11434** | 11434 | **redblue-shared** | — (or `gpu`) | `ollama_models` | — |
| 28 | redblue-coordinator | NEW (uv/FastAPI/LangGraph) | **8900** (+8901/8902) | 8900 | **redblue-shared** | — | `coordinator_data` | (retry, not depends_on — cross-project) |
| **TELEMETRY (`-p telemetry`) — skeletons in doc 04** |
| 29 | wazuh-indexer | `wazuh/wazuh-indexer` | **9200** | 9200 | telemetry-net, **↔shared** | — | `wazuh_indexer_data` | — |
| 30 | wazuh-manager | `wazuh/wazuh-manager` | 1514/1515/55000 | same | telemetry-net, **↔shared** | — | `wazuh_manager_data` | wazuh-indexer |
| 31 | wazuh-dashboard | `wazuh/wazuh-dashboard` | **8443** (was 443) | 5601 | telemetry-net | — | `wazuh_dashboard_data` | wazuh-indexer |
| 32 | suricata | `jasonish/suricata` | — (host netns) | — | telemetry-net, **↔shared** | — | `suricata_logs` | — |
| 33 | falco | `falcosecurity/falco` | 5060 (opt gRPC) | 5060 | telemetry-net, **↔shared** | — | (host /proc, kernel) | — |
| 34 | target-range | (DVWA / juice-shop / custom) | (scoped) | — | telemetry-net | `target` | — | — |

Ports **bolded** in the Host-port column are the ones that differ from each service's authored default —
i.e. the resolution set (§2).

### 1.4 Skeleton — `deploy/docker-compose.redblue.yml` (coordinator + shared plane) — *representative*

```yaml
# deploy/docker-compose.redblue.yml — run as: docker compose -p coordinator -f deploy/docker-compose.redblue.yml up
# REPRESENTATIVE SKELETON. Coordinator + the one shared Ollama. Engines/telemetry come up as their own
# projects and attach to redblue-shared via their override fragments.
name: coordinator

include:
  # Telemetry shares this project's lifecycle in the "lab"/full profile; run standalone with -p telemetry otherwise.
  - path: ../telemetry/docker-compose.telemetry.yml

services:
  ollama:
    image: ollama/ollama:latest
    container_name: redblue-ollama
    ports:
      - "11434:11434"          # 00 §4: single shared LLM host
    volumes:
      - ollama_models:/root/.ollama
    networks: [redblue-shared]
    # GPU reservation is doc-03 territory; representative form:
    # deploy: { resources: { reservations: { devices: [{ driver: nvidia, count: 1, capabilities: [gpu] }] } } }
    healthcheck:
      test: ["CMD", "ollama", "list"]
      interval: 10s
      timeout: 5s
      retries: 12
      start_period: 30s
    restart: unless-stopped

  redblue-coordinator:
    build: { context: ../redblue-coordinator, dockerfile: Dockerfile }
    container_name: redblue-coordinator
    env_file: [ ./env/shared.env ]
    environment:
      - REDBLUE_DECEPTICON_URL=http://langgraph:2024        # reached over redblue-shared
      - REDBLUE_DECEPTICON_NEO4J_URI=bolt://neo4j:7687
      - REDBLUE_VIGIL_URL=http://backend:6987
      - REDBLUE_VIGIL_WEBHOOK_URL=http://soc-daemon:8081     # internal port on the bus (host is 8082)
      - REDBLUE_OLLAMA_URL=http://ollama:11434
      - REDBLUE_DB_URL=sqlite:////data/redblue.db            # MVP store; Postgres later (00 §6)
    ports:
      - "8900:8900"            # API
      - "8901:8901"            # UI (if standalone; else folds into Vigil console)
      - "8902:8902"            # /metrics
    volumes:
      - coordinator_data:/data # evidence store + sqlite (WORM, hash-chained — doc 08)
    networks: [redblue-shared]
    # NOTE: no depends_on on langgraph/backend — they live in other PROJECTS. Ordering is Makefile-driven
    # (§4.3) and the coordinator retries with backoff against the URLs above until healthy.
    restart: unless-stopped

volumes:
  ollama_models:
  coordinator_data:

networks:
  redblue-shared:
    external: true            # created once by `make net`; shared by all 4 projects, not project-prefixed
```

### 1.5 Skeleton — `deploy/overrides/decepticon.redblue.yml` — *representative*

```yaml
# Merged as: docker compose -p decepticon --env-file deploy/env/decepticon.env \
#   -f ../Decepticon/docker-compose.yml -f deploy/overrides/decepticon.redblue.yml up
# REPRESENTATIVE. Adds the shared bus to the 3 cross-stack endpoints; points LLM at the shared ollama.
# Compose merges service `networks:` lists ADDITIVELY, so we only append redblue-shared.
services:
  litellm:
    environment:
      - OLLAMA_API_BASE=http://ollama:11434     # was host.docker.internal; now the shared container
    networks: [redblue-shared]                  # appended to decepticon-net
  neo4j:
    networks: [redblue-shared]                  # appended to sandbox-net + decepticon-net (see §3.4 risk)
  langgraph:
    networks: [redblue-shared]                  # appended to decepticon-net + sandbox-net

networks:
  redblue-shared:
    external: true
```

Host-port remaps for Decepticon are **not** here — they are env-only (`deploy/env/decepticon.env`, §2.2),
because every Decepticon host port is `${VAR:-default}`.

### 1.6 Skeleton — `deploy/overrides/vigil.redblue.yml` — *representative*

```yaml
# Merged as: docker compose -p vigil --env-file deploy/env/vigil.env \
#   -f ../vigil/docker/docker-compose.yml -f deploy/overrides/vigil.redblue.yml up
# REPRESENTATIVE. Vigil host ports are HARDCODED string literals ("8081:8081"), and Compose MERGES
# `ports:` lists additively — so we MUST use the !override tag to replace, not append.
services:
  backend:
    environment:
      - OLLAMA_URL=http://ollama:11434
    networks: [redblue-shared]                  # appended to deeptempo-network
  soc-daemon:
    environment:
      - OLLAMA_URL=http://ollama:11434
      - DAEMON_WEBHOOK_PORT=8081                 # internal listen stays 8081
    ports: !override                             # replace the base list; internal stays 8081, host → 8082
      - "8082:8081"                              # 00 §4: webhook remapped (Decepticon BHCE owns host 8081)
      - "9090:9090"
      - "9091:9091"
    networks: [redblue-shared]

networks:
  redblue-shared:
    external: true
```

---

## 2. Port collision resolution (reproduces + expands `00 §4`)

### 2.1 The full default host-port map, with collision verdicts

Verified against the real files (`Decepticon/docker-compose.yml`, `vigil/docker/docker-compose.yml`).
Decepticon publishes on `127.0.0.1`; Vigil publishes on `0.0.0.0`. A host port is a collision regardless of
bind address if both stacks claim the same number and both services are up.

| Host port | Decepticon claims | Vigil claims | Collision? | Resolution (00 §4) |
|---|---|---|---|---|
| **5432** | postgres (default, always on) | postgres (always on) | **YES — always** | Decepticon → **5433** |
| **8081** | bhce (profile `ad`, on-demand) | soc-daemon webhook (always on) | **YES — when `ad` up** | Vigil webhook → **8082** |
| 3000 | web (profile `web`, off by default) | — | No | Decepticon web → **3100** (00 band move, not forced) |
| 3003 | web terminal (profile `web`) | — | No | Decepticon terminal → **3103** (00 band move) |
| 4000 | litellm | — | No | keep |
| 7474 / 7687 | neo4j | — | No | keep |
| 2024 | langgraph | — | No | keep |
| 9100 | skillogy | — | No | keep |
| 6379 | — | redis | No | keep |
| 6987 | — | backend | No | keep |
| 8080 | (bhce *internal* only) | bifrost | No (bhce host=8081) | keep |
| 9090 / 9091 | — | soc-daemon prom/health | No | keep |
| 3001 | — | grafana (obs) | No | keep |
| 16686 | — | jaeger (obs) | No | keep |
| 9095 | — | prometheus (obs) | No | keep |
| 4317 / 4318 | (jaeger stanza commented out) | otel (obs) | No | keep |
| 5050 | — | pgadmin (dev) | No | keep |
| 6990/8088/8089/9997 | (ghidra-mcp int 8089, not host) | splunk | No | keep |
| 9092 | — | kafka | No | keep |
| 11434 | (LLM base, not published) | (OLLAMA_URL host, not published) | No | shared `ollama` publishes it |

**Net:** only **two** true remaps are collision-forced (`5432`, `8081`); the two `3000/3003` moves are
00-mandated band organization. Telemetry (`9200/8443/1514-1515/55000/5060`) and coordinator (`8900-8902`)
claim fresh, un-collided ranges per `00 §4`.

### 2.2 Exactly WHERE each remap is applied

| Remap | Mechanism | File / var | Why it works |
|---|---|---|---|
| Decepticon Postgres `5432→5433` | **env only** | `deploy/env/decepticon.env`: `POSTGRES_PORT=5433` | Base compose: `"127.0.0.1:${POSTGRES_PORT:-5432}:5432"`. Internal stays 5432; DSNs (`postgres:5432`) unaffected. |
| Decepticon web `3000→3100` | **env only** | `deploy/env/decepticon.env`: `WEB_PORT=3100` | Base: `"127.0.0.1:${WEB_PORT:-3000}:3000"`. Also read by `cli` env + `NEXT_PUBLIC_*`. Behind `web` profile. |
| Decepticon terminal `3003→3103` | **env only** | `deploy/env/decepticon.env`: `TERMINAL_PORT=3103` | Base: `"127.0.0.1:${TERMINAL_PORT:-3003}:3003"` + `NEXT_PUBLIC_TERMINAL_WS_URL`. |
| Vigil daemon webhook `8081→8082` | **compose override `!override`** | `deploy/overrides/vigil.redblue.yml` → `soc-daemon.ports` | Vigil ports are literal `"8081:8081"`; `!override` replaces the list. Internal listen kept 8081 (`DAEMON_WEBHOOK_PORT=8081`), host → 8082. |
| (Decepticon BHCE stays `8081`) | env-available | `${BHCE_PORT:-8081}` | Only up under `ad` profile; keeps 8081 free-and-clear once Vigil vacated it. |

**Rule confirmed:** Decepticon remaps require **zero file edits** (env-file only). Vigil requires a **tracked
override fragment** (its ports are not parameterized) — consistent with `00 §3` "no in-place edits to reused
repos; changes are additive/tracked." No line of either repo's `docker-compose.yml` is modified.

---

## 3. Networks & volumes

### 3.1 Network graph

| Network | Owner/scope | Driver | Members | Joined to redblue-shared? |
|---|---|---|---|---|
| `redblue-shared` | **external** (created by `make net`) | bridge | coordinator, ollama, langgraph, neo4j, litellm, vigil-backend, vigil-soc-daemon, wazuh-manager, suricata, falco | — (is the bus) |
| `decepticon-net` | decepticon project | bridge | litellm, postgres, neo4j, langgraph, skillogy, web, cli, bhce* | No (private) |
| `sandbox-net` | decepticon project | bridge | **sandbox, c2-sliver, ghidra-mcp**, neo4j (dual), langgraph (dual) | **NEVER** (isolation invariant) |
| `deeptempo-network` | vigil project | bridge | postgres, redis, backend, soc-daemon, llm-worker, bifrost, pgadmin, obs/splunk/kafka | No (private) |
| `telemetry-net` | telemetry project | bridge | wazuh-*, suricata, falco, target-range | No (private) |
| `range-net` | telemetry/range | bridge | target-range, suricata (sniff), **Kali `sandbox` (its only extra attach)** | No (private; the sole Kali→target path — per 04 / 00 §5) |

**Isolation invariant (test in §7):** `docker network inspect redblue-shared` must **never** list
`decepticon-sandbox` or `decepticon-c2-sliver`. The Kali attack surface reaches only its target
(telemetry-net targets via routed engagement scope) and Neo4j — never the coordinator/blue plane directly.

### 3.2 Named volumes — what must persist

| Volume | Project | Holds | Persist? | `make clean` policy |
|---|---|---|---|---|
| `postgres_data` (decepticon) | decepticon | LiteLLM spend logs + `decepticon_web` state | Yes | prune only on `clean-all` |
| `postgres_data` (vigil) | vigil | findings, cases, investigations, RBAC, pgvector embeddings | **Critical** | never auto-prune |
| `neo4j_data` / `neo4j_logs` | decepticon | **shared attack graph** (engagement-scoped, blue reads it) | **Critical** | never auto-prune |
| `bhce_neo4j_data` / `_logs` | decepticon | BloodHound AD graph (profile `ad`) | Optional | prune on `clean` |
| `sliver_data` | decepticon | C2 profiles/certs (profile `c2-sliver`) | Optional | prune on `clean` |
| `redis_data` | vigil | ARQ `arq:llm` queue + session store | Recoverable | prune on `clean` |
| `ollama_models` | shared | pulled GGUF weights (multi-GB) | **Yes — expensive to refill** | **never auto-prune** (guard in Makefile) |
| `coordinator_data` | coordinator | engagements, scorecards, **hash-chained evidence** (doc 08) | **Critical** | never auto-prune |
| `wazuh_indexer_data` | telemetry | OpenSearch indices (alerts, ground truth) | Yes | prune on `clean-all` |
| `wazuh_manager_data` | telemetry | agent keys, rules state | Yes | prune on `clean-all` |
| `prometheus_data` / `grafana_data` | vigil | metrics TSDB + dashboards (obs) | Optional | prune on `clean` |
| `splunk_data`/`_etc`, `kafka_data`, `pgadmin_data` | vigil | profile stores | Optional | prune on `clean` |

Two Postgres instances **stay separate** (`00 §5`): red `decepticon_web`/`litellm` DBs vs blue
`deeptempo_soc`. Do not merge. Coordinator uses its own SQLite (`coordinator_data`) in MVP.

### 3.3 The `postgres` service-name collision (root cause of the multi-project model)

Both `Decepticon/docker-compose.yml` and `vigil/docker/docker-compose.yml` define a top-level service keyed
`postgres` (different images — `postgres:17-alpine` vs `pgvector/pgvector:pg16`, different DBs, different init
dirs, different passwords). Under **any** single-project merge (`include:` or an `-f` chain), Compose merges
same-key services into one — last-writer-wins on `image`, unioned `environment`, conflicting volume mounts —
producing a **broken** Postgres. Multi-project isolation (`-p decepticon` vs `-p vigil`) is the fix and the
reason `00 §3`'s "single top-level file" is refined (Conflict 1). Same latent risk existed for `redis`/`neo4j`
had both stacks defined them; only `postgres` actually overlaps today.

### 3.4 Neo4j dual/tri-homing — the one bridge to watch

Base compose already dual-homes `neo4j` on `sandbox-net` + `decepticon-net` (so the orchestrator on the infra
plane can read findings written from inside the sandbox). Our override adds `redblue-shared` (so the
coordinator/Vigil can read the engagement-scoped attack graph over the bus, per `00 §5`). Net effect: Neo4j is
tri-homed. **Mitigations already in place / required:**
- The base file's APOC **allowlist-only** posture (no file-I/O, cross-DB, or trigger procedures) stays — it is
  what stops a prompt-injection Cypher payload from turning Neo4j into a sandbox→management pivot.
- The **sandbox itself is not on redblue-shared**, so a compromised Kali box cannot reach the coordinator/blue
  plane; only Neo4j (hardened, read-mostly for blue) is the shared surface.
- **High-isolation alternative (documented, not default):** drop `redblue-shared` from `neo4j`; instead attach
  the **coordinator** to `decepticon_decepticon-net` (external) and have it read bolt there. Keeps Neo4j off the
  bus at the cost of the coordinator knowing a project-prefixed net name. Choose per deployment risk tier.

---

## 4. Bring-up order & health

### 4.1 Intra-project health chains (verified from the real `depends_on` + `healthcheck`)

**Decepticon** (all gates are `service_healthy` unless noted):
```
postgres (pg_isready, ~10s)
   └─► litellm (GET /health/readiness; start_period 300s — prisma migrate + routing load)
neo4j (wget :7474, start_period 90s) ─┐
sandbox (service_STARTED, not healthy)─┤
litellm ──────────────────────────────┼─► langgraph (GET /2024/ok, start 90s)
                                       │        └─► web (profile web; node http get, start 90s)
neo4j + litellm ──────────────────────┴─► skillogy (GET /v1/health)
[profile ad] postgres ─► bhce-postgres-init ─► (bhce-neo4j) ─► bhce
```
Launcher uses `compose up --wait`; `litellm` healthy is the long pole (measured 136s cold, 300s cushion).

**Vigil**:
```
postgres (pg_isready) ─┐
redis (redis-cli ping)─┼─► backend / soc-daemon / llm-worker
bifrost (GET /health)──┘
```
`bifrost` healthcheck: `wget -qO- :8080/health | grep '"status":"ok"'` (GET, not HEAD).

**Telemetry** (doc 04 owns detail):
```
wazuh-indexer (needs host sysctl vm.max_map_count=262144) ─► wazuh-manager ─► wazuh-dashboard
suricata / falco: independent (falco needs privileged + kernel headers/eBPF)
```

### 4.2 The cross-project ordering gap (important)

`depends_on` **only works within a single Compose project**. In the multi-project topology the coordinator
(project `coordinator`) **cannot** `depends_on` langgraph (project `decepticon`) or backend (project `vigil`).
Cross-stack readiness is therefore enforced two ways:
1. **Makefile sequencing** — `make up` brings up projects in order and blocks on each with `--wait`.
2. **Coordinator startup retry/backoff** — it polls `REDBLUE_DECEPTICON_URL/ok`, `REDBLUE_VIGIL_URL/health`,
   and `ollama:11434` with exponential backoff before entering its loop; `make health` is the human gate.

### 4.3 Per-phase bring-up (conforms to `00 §8`)

| Phase | Command | Projects up | Profiles | Shared bus? |
|---|---|---|---|---|
| **P0** engines standalone | `make red-only` / `make blue-only` | decepticon, vigil (separately) | none (core only) | not required |
| **P1** sovereignty | as P0 + `ollama` up, LLM bases → `ollama:11434` | + ollama | none | ollama on bus |
| **P2** + telemetry | `make lab` | decepticon, vigil, telemetry, ollama | telemetry core | yes (sensors→Vigil webhook) |
| **P4** + coordinator | `make up` | all 4 | as configured | yes (full loop) |
| on-demand | `make ad` / `make reversing` / `make obs` / `make demo` | adds profiles | `ad`/`reversing`/`observability`/`splunk`… | — |

**Order for `make up`:** `net → ollama → decepticon (--wait) → vigil (--wait) → telemetry (--wait) → coordinator`.

### 4.4 Running subsets via profiles

- Decepticon profiles (default OFF): `web`, `cli`, `reversing`, `c2-sliver`, `ad`. Core = litellm+postgres+
  neo4j+sandbox+langgraph+skillogy.
- Vigil profiles (default OFF): `dev` (pgadmin), `observability` (otel/jaeger/prometheus/grafana),
  `splunk`, `kafka`. Core = postgres+redis+backend+soc-daemon+llm-worker+bifrost.
- Exposed as Make vars: `make up PROFILES="observability ad"` → passes `--profile` flags to the right projects.
- Vigil **frontend (`:6988`) is NOT in the compose file** — it is run via `start.sh`/`npm run dev` in dev. Host
  6988 is reserved (`00 §4`); the unified console (doc 09) extends this FE. Note it separately when demoing.

---

## 5. Makefile targets (`deploy/Makefile`) — *representative skeleton*

```makefile
# deploy/Makefile — the real orchestrator of the 4 projects. REPRESENTATIVE.
SHELL := /bin/bash
DEC   := docker compose -p decepticon --env-file env/decepticon.env \
           -f ../Decepticon/docker-compose.yml -f overrides/decepticon.redblue.yml
VIG   := docker compose -p vigil --env-file env/vigil.env \
           -f ../vigil/docker/docker-compose.yml -f overrides/vigil.redblue.yml
TEL   := docker compose -p telemetry -f ../telemetry/docker-compose.telemetry.yml
CO    := docker compose -p coordinator -f docker-compose.redblue.yml
PROFILES ?=
DEC_PROF := $(foreach p,$(PROFILES),--profile $(p))
VIG_PROF := $(foreach p,$(PROFILES),--profile $(p))

net:            ## create the shared bus once (idempotent)
	docker network inspect redblue-shared >/dev/null 2>&1 || docker network create redblue-shared

ollama: net
	$(CO) up -d ollama

red-only: net ollama            ## P0/P1 red engine standalone
	$(DEC) $(DEC_PROF) up -d --wait

blue-only: net ollama           ## P0/P1 blue engine standalone
	$(VIG) $(VIG_PROF) up -d --wait

lab: red-only blue-only         ## P2: engines + telemetry sensors
	$(TEL) up -d --wait

up: lab                         ## P4: full closed loop
	$(CO) up -d --wait
	@$(MAKE) health

down:                           ## stop everything, keep volumes
	-$(CO) down ; -$(TEL) down ; -$(VIG) down ; -$(DEC) down

logs:                           ## tail all (usage: make logs SVC=langgraph)
	@if [ -n "$(SVC)" ]; then $(DEC) logs -f $(SVC) 2>/dev/null || $(VIG) logs -f $(SVC); \
	 else $(DEC) logs -f & $(VIG) logs -f & $(TEL) logs -f & $(CO) logs -f ; fi

ps:            ; $(DEC) ps ; $(VIG) ps ; $(TEL) ps ; $(CO) ps

config:                         ## validate every project renders (acceptance gate)
	$(DEC) config -q && $(VIG) config -q && $(TEL) config -q && $(CO) config -q && echo OK

health:                         ## show healthchecks + probe cross-stack endpoints
	@docker ps --format '{{.Names}}\t{{.Status}}' | grep -E 'decepticon|deeptempo|redblue|wazuh|suricata|falco'
	@curl -sf http://localhost:2024/ok       && echo " langgraph OK"
	@curl -sf http://localhost:6987/health   && echo " vigil OK"      || true
	@curl -sf http://localhost:11434/api/tags>/dev/null && echo " ollama OK"
	@curl -sf http://localhost:8900/health   && echo " coordinator OK"|| true
	@docker network inspect redblue-shared -f '{{range .Containers}}{{.Name}} {{end}}' \
	  | grep -Eq 'sandbox|c2-sliver' && echo "!! ISOLATION BREACH: sandbox on shared net" || echo " isolation OK"

ad reversing:  ; $(MAKE) red-only PROFILES="$@"     ## on-demand red profiles
obs:           ; $(MAKE) blue-only PROFILES="observability"
demo:          ; $(MAKE) up PROFILES="observability"  ## demo lab (§6)

clean:                          ## down + prune SAFE volumes (keeps postgres/neo4j/ollama/coordinator)
	$(MAKE) down
	-docker volume rm coordinator_sliver_data decepticon_bhce_neo4j_data vigil_grafana_data vigil_prometheus_data 2>/dev/null

clean-all:                      ## DANGER: also removes model + DB + evidence volumes
	$(MAKE) down
	@read -p "Delete ollama_models + all DBs + evidence? [y/N] " a; [ "$$a" = y ] && \
	  docker volume prune -f && docker network rm redblue-shared || echo aborted
```

`clean` never touches `ollama_models`, the two Postgres volumes, `neo4j_data`, or `coordinator_data`
(model re-pull and evidence loss are expensive/irreversible). Only `clean-all` does, behind a prompt.

---

## 6. Resource & GPU sizing

### 6.1 Per-stack footprint (steady state, core profiles)

| Stack | Services (core) | RAM (approx) | vCPU | Notes |
|---|---|---|---|---|
| Decepticon | litellm, postgres(2g cap), neo4j(2g cap), sandbox(4g cap), langgraph, skillogy | **~8–10 GB** | 4–6 | sandbox is idle-light but capped 4g for scans/fuzzers; neo4j+pg capped 2g each |
| Vigil | postgres, redis(512m cap), backend, soc-daemon, llm-worker, bifrost | **~6–8 GB** | 4 | 3 Python services (backend/daemon/worker) ~1–1.5g each |
| Telemetry | wazuh-indexer, wazuh-manager, wazuh-dashboard, suricata, falco | **~6–9 GB** | 4–6 | **indexer is the pig** (OpenSearch/JVM ~2–4g, needs `vm.max_map_count=262144`); falco needs kernel access |
| Coordinator | redblue-coordinator | **~0.5–1 GB** | 1 | FastAPI + LangGraph, SQLite |
| **Ollama** | model host | **model-dependent** (see 6.2) | 2 (+GPU) | the real driver of the box size |

Profile add-ons (all default OFF): Vigil `observability` +~1.5 GB; `splunk` **+2–4 GB** (heavy);
`kafka` +1 GB; Decepticon `ad` (bhce trio) **+2–3 GB**; `reversing` (ghidra, 4g cap) **+2–4 GB**.

### 6.2 Ollama model footprint (doc 03 owns final tiers; sizing only here)

| Model class | Example | RAM/VRAM (Q4) | Fits GPU |
|---|---|---|---|
| Small (7–8B) | `qwen2.5:7b`, `llama3.1:8b` | ~5–6 GB | 8 GB GPU |
| Mid (14B) | `qwen2.5:14b` | ~9–10 GB | 12–16 GB GPU |
| Large (32–34B) | `qwen2.5:32b` Q4 | ~20–22 GB | 24 GB GPU |
| XL (70B) | `llama3.1:70b` Q4 | ~40–45 GB | 48 GB GPU (or dual 24 GB) |
| Embeddings | `nomic-embed-text` | ~0.5 GB | any / CPU-ok |

**One Ollama serves both LiteLLM (red) and Bifrost (blue)** (`00 §5`) → red and blue **contend for the same
VRAM**. Concurrent red+blue inference on a single mid model will serialize; size the GPU for the *largest single
model in play plus embeddings*, and rely on Vigil's ARQ `arq:llm` queue + LiteLLM routing to smooth bursts.
Keep `keep_alive` modest so an idle engine's model can be evicted for the other.

### 6.3 Minimum dev box vs demo lab

| | **Minimum dev box** (P0–P1) | **Demo lab** (P4 full loop) |
|---|---|---|
| Goal | engines standalone on a small model | closed loop + telemetry + coordinator + obs |
| Profiles | core only (no telemetry/obs/ad/reversing/splunk) | telemetry + `observability` (+ `ad` on demand) |
| Model | one 7–8B Q4 | one 14B Q4 (+embeddings), room for 32B |
| **RAM** | **16–24 GB** (tight at 16) | **64 GB** |
| **vCPU** | 8 | 16 |
| **GPU** | optional (CPU inference works but slow) | **24 GB** (RTX 4090 / A5000 / L4-class) |
| **Disk** | ~60 GB (images + one model) | **~200 GB** (Wazuh indices grow, multiple models, all images) |
| Host prep | Docker + Compose v2.24+ (for `!override`) | + `sysctl vm.max_map_count=262144`, GPU driver + nvidia-container-toolkit, kernel headers (falco) |

Compose **v2.24+** is a hard floor (the `!override`/`!reset` merge tags used for the Vigil port remap).
`develop.watch` (Decepticon dev/watch overlays) needs **v2.22+**; both satisfied by v2.24+.

---

## 7. Checklist & acceptance

**Pre-flight (host):**
- [ ] Docker Engine + Compose **v2.24+** (`docker compose version`).
- [ ] `sysctl -w vm.max_map_count=262144` (Wazuh indexer) — persist in `/etc/sysctl.d/`.
- [ ] GPU: nvidia driver + `nvidia-container-toolkit` (demo lab); else CPU-only Ollama.
- [ ] `make net` created `redblue-shared`.
- [ ] `deploy/env/*.env` populated (Decepticon `POSTGRES_PORT=5433/WEB_PORT=3100/TERMINAL_PORT=3103`;
      Vigil `POSTGRES_PASSWORD` set, `DEV_MODE=false` **before any exposure**).

**Compose validates (acceptance):**
- [ ] `make config` → all 4 projects render (`docker compose config -q` exits 0 for each).
- [ ] No host-port collision: `ss -ltnp` shows one owner per 5432/5433/8081/8082/… .
- [ ] Vigil `soc-daemon` publishes **8082→8081** (confirm `docker port deeptempo-daemon`).
- [ ] Decepticon `postgres` publishes **5433→5432** (confirm `docker port decepticon-postgres`).

**Health green:**
- [ ] `make health` → langgraph `/ok`, vigil `/health`, ollama `/api/tags`, coordinator `/health` all 200.
- [ ] `docker ps` shows every core container `healthy` (litellm may take up to 300s cold).
- [ ] Coordinator reaches `langgraph:2024`, `neo4j:7687`, `backend:6987`, `ollama:11434` over `redblue-shared`.

**Isolation invariant:**
- [ ] `docker network inspect redblue-shared` lists **no** `sandbox`/`c2-sliver` container.
- [ ] `sandbox` can reach `neo4j` + its scoped target, and **cannot** reach `redblue-coordinator`/`backend`.

**Persistence:**
- [ ] `make down && make up` preserves Vigil findings, Neo4j attack graph, coordinator evidence, ollama models.
- [ ] `make clean` leaves `ollama_models`, both `postgres_data`, `neo4j_data`, `coordinator_data` intact.

## 8. Risks

| # | Risk | Impact | Mitigation |
|---|---|---|---|
| R1 | `postgres` service-name collision if anyone merges stacks into one project | Corrupt/merged DB service | **Multi-project topology is mandatory** (§3.3); Makefile enforces `-p`; document loudly. |
| R2 | Vigil ports hardcoded; naive override **appends** → 8081 still bound | Port collision persists | Use `!override` (Compose ≥2.24) in `vigil.redblue.yml` (§1.6); acceptance test §7 verifies. |
| R3 | `depends_on` doesn't cross projects → coordinator races engines | Loop starts before engines ready | Makefile `--wait` sequencing + coordinator retry/backoff (§4.2). |
| R4 | Neo4j tri-homed onto `redblue-shared` widens sandbox→bus bridge | Pivot surface | APOC allowlist stays; sandbox itself off the bus; high-isolation alt keeps Neo4j private (§3.4). |
| R5 | Wazuh indexer needs `vm.max_map_count`; falco needs privileged/kernel | Telemetry won't boot | Host-prep checklist (§7); gate telemetry behind `make lab`. |
| R6 | `host.docker.internal:11434` doesn't resolve on Linux (Vigil has no `extra_hosts`) | Blue can't reach host Ollama | Ship **containerized `ollama`** on `redblue-shared`; point both engines at `http://ollama:11434` (§1.4/§6.2). |
| R7 | Single Ollama shared by red+blue → VRAM contention | Latency / OOM on GPU | Size for largest single model + embeddings; ARQ queue + LiteLLM routing + modest `keep_alive` (§6.2). |
| R8 | `make clean` nukes model/DB/evidence volumes | Expensive re-pull / evidence loss | `clean` excludes them; only `clean-all` prunes, behind a prompt (§5). |
| R9 | Vigil `DEV_MODE=true` + Decepticon RoE/HITL off, once joined to shared bus | Auth bypass / unbounded red on a reachable plane | Set `DEV_MODE=false` and enforce RoE/HITL per tenant **before** exposure (docs 06/08); not a compose fix but a bring-up gate. |
| R10 | Vigil frontend (`:6988`) absent from compose (dev-run only) | "console" missing in a pure-compose demo | Note explicitly; add a FE service or run `start.sh`; host 6988 reserved (§4.4, doc 09). |
| R11 | Compose < v2.24 in CI/older hosts | `!override` unknown tag, render fails | Pin v2.24+ as a hard floor (§6.3); `make config` catches it early. |

---

## 9. Handoffs

- **doc 03** — finalizes Ollama model tiers, GPU reservation syntax, air-gap egress verification. §6.2 sizing is
  provisional; §1.4 `ollama` service is the anchor point.
- **doc 04** — fills the telemetry skeletons (§1.3 rows 29–34): Wazuh/Suricata/Falco configs, target range,
  alert→Vigil-webhook (`soc-daemon:8081` on the bus) mapping.
- **doc 06/08** — the DEV_MODE/RoE/HITL bring-up gate (R9) and the tool-tier fix are their acceptance items;
  compose only provides the reachable surface.

## 10. Conflicts with `00` (summary)

1. **`00 §3` single `deploy/docker-compose.redblue.yml` "wiring all stacks":** refined to a **multi-project**
   model (one project per stack + shared external net + per-stack override fragments), because the shared
   `postgres` service key makes a single merged project non-viable. `deploy/docker-compose.redblue.yml` remains
   (it's the coordinator + shared-Ollama project) but is no longer the *only* file. **Requests a wording update
   to `00 §3`.**
2. **`00 §4` Decepticon `3000→3100` / `3003→3103`:** verified **not** host collisions with Vigil (they sit
   behind Decepticon's default-off `web` profile and Vigil exposes nothing on 3000/3003). Kept for conformance
   as band organization; flagged so `00 §4`'s "collisions resolved" framing reads accurately (the true forced
   remaps are `5432→5433` and `8081→8082` only).

No other divergence: port map, network names, `sandbox-net` isolation, two-Postgres separation, one-Ollama,
phase numbering, and naming all conform to `00`.
