# 03 — Sovereignty & Local LLM (Zero Foreign-API Egress)

> **Status:** Planning (pre-code). **Owner:** ESDS RedBlue AI team.
> **Conforms to:** `00_MASTER_PLAN.md` (AUTHORITATIVE). Tech stack §6 (Ollama), port map §4
> (Ollama `:11434`, LiteLLM `:4000`, Bifrost `:8080`), phases §8 (P0 standalone, **P1 = Sovereignty exit gate**).
> **Deviations from 00 are collected in the final "Conflicts with 00" section** — this doc does not silently diverge.

**Mandate.** Both engines — 🔴 Decepticon (red) and 🔵 Vigil (blue) — run **exclusively on local Ollama**
inference with **verifiable zero egress to any foreign LLM API** (Anthropic / OpenAI / Google / xAI / …),
for ESDS Sovereign Cloud under **DPDP + CERT-In**. This is P1's binary exit gate: *"both engines answer with
zero external egress (verified)."*

This document is grounded in the actual engine code, not the docs. The load-bearing facts and where they live:

| Fact (verified in code) | Location |
|---|---|
| Red auth method `OLLAMA_LOCAL="ollama_local"`; detected via `OLLAMA_API_BASE`/`OLLAMA_MODEL` | `decepticon-core/.../types/llm.py:129`, `factory.py:389-398` |
| Red Ollama **collapses all tiers to one model** (`ollama_chat/__OLLAMA_MODEL__` placeholder; resolved from `OLLAMA_MODEL`) | `types/llm.py:238-251, 636-657`; `resolve_chain` `:769-773` |
| Red per-role override `DECEPTICON_MODEL_<ROLE>` wins over bundle/tier; each value is registered as a LiteLLM route | `agents/build.py:140` `resolve_role_model`; `litellm_dynamic_config.py:437-464` `collect_requested_models` |
| Red proxy `http://localhost:4000`, env `DECEPTICON_LLM__PROXY_URL`/`__PROXY_API_KEY`; profile `DECEPTICON_MODEL_PROFILE` | `decepticon-core/.../utils/config.py:37-73` |
| Red `ollama_chat/` (NOT `ollama/`) is mandatory — it hits `/api/chat` which supports tool calls | `litellm.yaml:741-753`; `litellm_dynamic_config.py:290-294, 376-401` |
| Blue: **all** LLM traffic routes through Bifrost; Ollama → OpenAI-format `/v1` as `ollama/<model>` | `services/llm_router.py:281-342, 346-428` |
| Blue Ollama Bifrost allow-list is pinned to wildcard `["*"]` | `services/bifrost_admin.py:170-173` |
| Blue Bifrost seed already ships an `ollama` provider (`url: env.OLLAMA_URL`, models `["*"]`) | `vigil/docker/bifrost/config.json:50-67` |
| Blue per-component model chain: `ai_model_configs[component] → chat_default → default **Anthropic** provider` | `services/model_registry.py:793-829`; components `:81-89` |
| Blue `DEFAULT_MODEL` failsafe defaults to `claude-sonnet-4-6` (cloud!) | `services/defaults.py:15` |
| Blue **extended-thinking only round-trips on the Anthropic passthrough** — the Ollama `/v1` path drops it | `llm_router.py:317-342, 562-565` vs `_dispatch_bifrost_openai:346-428` |
| Blue Ollama runs **host-native** (not a container); containers reach it via `host.docker.internal` | `services/ollama_process.py:1-18, 46-72` |

---

## 1. Ollama setup — one Ollama, both gateways

### 1.1 Topology decision (single shared Ollama)

> **⚠ CANONICAL DECISION (reconciled with 00 §5 / 02 §1.4):** the **default deployment is a
> containerized `ollama` service on `redblue-shared`**, reached by both gateways at `http://ollama:11434`
> (no `extra_hosts` needed; k8s-portable; what `02`'s compose + Makefile assume). Vigil's host-native
> `ollama_process.py` supervisor is **bypassed** — point `OLLAMA_URL`/`OLLAMA_API_BASE` at the container
> and do not let Vigil spawn a competing host daemon. The **host-native** topology shown below (Ollama on
> the host + `host.docker.internal:11434` + `extra_hosts: host-gateway`) is a **documented ALTERNATIVE**
> for nodes where in-container GPU passthrough is undesirable — substitute `ollama:11434` for
> `host.docker.internal:11434` throughout this doc when using the container default.

Per 00 §5 ("One Ollama serves both LiteLLM `:4000` and Bifrost `:8080`") we run **one Ollama** bound to
`:11434` and point both gateways at it. (Default: containerized `ollama:11434`, per the banner above;
the host-native variant below is the alternative.)

```
                         ┌──────────── HOST ────────────┐
  Decepticon agents ──▶ LiteLLM proxy (:4000, container) ─┐
  (LangGraph :2024)      OLLAMA_API_BASE=                  │
                         http://host.docker.internal:11434 ├─▶  Ollama daemon
                                                           │    :11434 (host-native, GPU)
  Vigil agents/daemon ─▶ Bifrost gateway (:8080, container)┘    OLLAMA_HOST=0.0.0.0:11434
  (backend :6987)        provider "ollama" url=
                         http://host.docker.internal:11434
```

**Why host-native and not a compose service.** Vigil's supervisor (`ollama_process.py`) is explicit: Ollama is
run as a **host process**, never a container, because containerized Ollama loses GPU acceleration on macOS
(no Metal passthrough) and, on Linux, containerizing it just adds the `nvidia-container-toolkit` dependency for
no benefit. Both gateways run *in* containers and reach the host daemon over `host.docker.internal`.

> **Linux note (this deployment is Linux).** `host.docker.internal` is not automatic on Linux. Every container
> that must reach Ollama (LiteLLM, Bifrost) needs, in its compose service:
> ```yaml
> extra_hosts:
>   - "host.docker.internal:host-gateway"
> ```
> Decepticon's LiteLLM service already ships this (`.env.example:154`). Vigil's Bifrost service must be verified
> to carry it too (record the requirement in `02_INFRA_COMPOSE_AND_PORTS.md`). Alternative: bind Ollama to the
> host LAN IP and use that IP directly in both `OLLAMA_API_BASE` and `OLLAMA_URL`.

### 1.2 Install

```bash
# Linux host (ESDS node)
curl -fsSL https://ollama.com/install.sh | sh        # or the offline .tgz for air-gapped nodes
# Serve on all interfaces so containers can reach it; keep models resident longer.
sudo tee /etc/systemd/system/ollama.service.d/override.conf <<'EOF'
[Service]
Environment="OLLAMA_HOST=0.0.0.0:11434"
Environment="OLLAMA_KEEP_ALIVE=30m"          # keep a hot model resident between calls
Environment="OLLAMA_MAX_LOADED_MODELS=3"     # how many distinct models stay resident (VRAM-bound)
Environment="OLLAMA_NUM_PARALLEL=2"          # concurrent requests per model
Environment="OLLAMA_FLASH_ATTENTION=1"
EOF
sudo systemctl daemon-reload && sudo systemctl enable --now ollama
```

**Air-gapped install:** pull the install tarball + model blobs on a connected staging box, transfer, and
`ollama create`/import; the daemon itself makes no outbound calls once models are local (it will try
`registry.ollama.ai` **only** on `ollama pull` — which we do during provisioning, before the egress lockdown of §5).

### 1.3 GPU vs CPU

| Mode | When | Config | Expectation |
|---|---|---|---|
| **GPU (NVIDIA)** | Default for demo/prod | `nvidia-smi` present; Ollama auto-detects CUDA. Set `CUDA_VISIBLE_DEVICES` to pin cards. | 20–80 tok/s on a 14–32B Q4 model; usable for interactive agents. |
| **CPU-only** | Fallback / laptop dev | No GPU; Ollama falls back automatically. Cap model size ≤8B (Q4). | 3–10 tok/s; acceptable for smoke tests, **not** for a live multi-agent engagement. |

Quantization: pull **Q4_K_M** builds (Ollama default tags) — best VRAM/quality trade. Reserve Q5/Q8 for the
strongest reasoning model if VRAM allows. Sizing detail in §7.

### 1.4 Model pull manifest (provisioning step, before egress lockdown)

Two named variants, referenced throughout. Pull the whole set for the variant you deploy:

```bash
# ── Variant A: "demo GPU-light" (single 24 GB GPU, or CPU smoke test) ──
ollama pull qwen2.5-coder:7b        # red exploit/patch/code roles + blue investigation
ollama pull llama3.1:8b             # general HIGH/MID agents (tool-calling)
ollama pull llama3.2:3b             # recon/triage/scanner — fast, cheap
ollama pull nomic-embed-text        # local embeddings (see §6.4) — replaces cloud embeddings

# ── Variant B: "quality" (48–80 GB VRAM / multi-GPU) ──
ollama pull qwen2.5-coder:32b       # red HIGH code roles (exploiter/patcher/contract_auditor)
ollama pull qwen3:32b               # HIGH reasoning (or: qwq:32b / deepseek-r1:32b for native thinking)
ollama pull llama3.3:70b            # strongest general agent (blue investigation/threat_hunt)
ollama pull qwen2.5:14b             # MID tier general
ollama pull llama3.1:8b             # LOW/MID tool-calling
ollama pull llama3.2:3b             # recon/triage
ollama pull nomic-embed-text        # local embeddings
```

**Tool-calling is non-negotiable for both engines** (every Decepticon agent and every Vigil MCP agent emits tool
calls). Pick models Ollama reports as tool-capable. Vigil's discovery treats a model as tool-capable if its name
prefix matches `_OLLAMA_TOOL_CAPABLE_FAMILIES` (`provider_model_discovery.py:339`): `llama3.1/3.2/3.3`, `llama4`,
`qwen2.5`, `qwen3`, `qwq`, `mistral*`, `command-r*`, `deepseek-r1/v2/v3/coder-v2`, `nemotron`, `granite3`, `phi4`,
`glm4`, `hermes3`, `athene`, `firefunction`. Note `qwen2.5-coder` matches via the `qwen2.5` prefix and
`qwen3-coder` via `qwen3` — both are tool-capable. For a model the heuristic doesn't know, set
`OLLAMA_EXTRA_TOOL_MODELS=<name>` (`provider_model_discovery.py:383`). **Avoid** `gemma*`, plain `phi3`, and
`codellama` for agent roles — weak or no tool-call support.

---

## 2. Model selection per role / tier

Both engines expose fine-grained role/tier structure. The tables map that structure onto local models for the two
variants. **Same physical models are shared across engines** to minimize VRAM residency thrash (§7).

### 2.1 Decepticon (red) — agent tiers → local model

Ground truth from `types/llm.py:512-543` (`AGENT_TIERS`):

| Tier | Roles (verbatim from `AGENT_TIERS`) | Demo (A) | Quality (B) | Rationale |
|---|---|---|---|---|
| **HIGH** | `decepticon` (orchestrator), `exploit`, `exploiter`, `patcher`, `contract_auditor`, `analyst`, `vulnresearch` | `qwen2.5-coder:7b` | `qwen2.5-coder:32b` (code/exploit) · `qwen3:32b` (orchestrator/analyst reasoning) | Deep reasoning + source-level analysis + exploit code. Failure cost is mission-critical. |
| **MID** | `detector`, `verifier`, `blue_cell`, `postexploit`, `ad_operator`, `cloud_hunter`, `reverser`, `phisher`, `mobile_operator`, `iot_operator`, `ics_operator`, `forensicator`, `supply_chain_operator` | `llama3.1:8b` | `qwen2.5:14b` | Precision execution, structured judgment, tool-heavy with moderate iteration. |
| **LOW** | `soundwave` (pre-engagement planner), `recon`, `scanner`, `wireless_operator`, `osint_operator` | `llama3.2:3b` | `llama3.1:8b` | High-throughput recon/triage/docs; low reasoning depth. |

> **Critical implementation note (verified).** Decepticon's Ollama path does **not** honor HIGH/MID/LOW per-tier
> model IDs. When `OLLAMA_LOCAL` is the auth method, `resolve_chain` (`types/llm.py:769-773`) resolves **every**
> tier to the single `ollama_chat/<OLLAMA_MODEL>`. To realize the table above you set **one base model**
> (`OLLAMA_MODEL`) for the whole fleet and **override the roles that need a different model** with
> `DECEPTICON_MODEL_<ROLE>=ollama_chat/<model>`. Each override value is auto-registered as a LiteLLM route by
> `collect_requested_models` (`litellm_dynamic_config.py:447-464`), so pointing three roles at three different
> Ollama tags "just works." Concrete wiring in §3.

### 2.2 Vigil (blue) — 13 agents → component category → local model

Ground truth: `soc_agents.py` `AGENT_CONFIGS` + `_BUILTIN_COMPONENT_CATEGORY:159-173`. Vigil resolves an
agent's model by its **component category** (`triage` / `investigation` / `reporting`), falling through to
`chat_default` (`model_registry.py:793-829`). So you assign models **per component**, not per agent.

| Agent (`id`) | `enable_thinking` | budget | `component_category` | Demo (A) | Quality (B) |
|---|---|---|---|---|---|
| `triage` | ✗ | — | **triage** | `llama3.2:3b` | `llama3.1:8b` |
| `investigator` (default) | ✓ | 10000 | investigation | `qwen2.5-coder:7b` | `llama3.3:70b` |
| `threat_hunter` | ✓ | 10000 | investigation | `qwen2.5-coder:7b` | `llama3.3:70b` |
| `correlator` | ✓ | 8000 | investigation | `qwen2.5-coder:7b` | `qwen3:32b` |
| `responder` | ✗ | — | investigation | `llama3.1:8b` | `qwen2.5:14b` |
| `reporter` | ✗ | — | **reporting** | `llama3.1:8b` | `qwen2.5:14b` |
| `mitre_analyst` | ✓ | 6000 | investigation | `qwen2.5-coder:7b` | `qwen3:32b` |
| `forensics` | ✓ | 8000 | investigation | `qwen2.5-coder:7b` | `llama3.3:70b` |
| `threat_intel` | ✓ | 6000 | investigation | `qwen2.5-coder:7b` | `qwen3:32b` |
| `compliance` | ✗ | — | investigation | `llama3.1:8b` | `qwen2.5:14b` |
| `malware_analyst` | ✓ | 10000 | investigation | `qwen2.5-coder:7b` | `llama3.3:70b` |
| `network_analyst` | ✓ | 8000 | investigation | `qwen2.5-coder:7b` | `qwen3:32b` |
| `auto_responder` (daemon) | ✓ | 3000 | investigation | `llama3.1:8b` | `qwen2.5:14b` |

Plus the non-agent components the daemon/orchestrator use (`model_registry.py:81-89`): `orchestrator_plan`,
`orchestrator_review`, `summarization`, and the ultimate `chat_default` failsafe. Assign them:

| Component | Demo (A) | Quality (B) | Note |
|---|---|---|---|
| `chat_default` | `llama3.1:8b` | `qwen2.5:14b` | **Must be set** — else falls through to a cloud Anthropic default (§4.4). |
| `orchestrator_plan` | `qwen2.5-coder:7b` | `qwen3:32b` | Autonomous loop planning. |
| `orchestrator_review` | `llama3.1:8b` | `qwen2.5:14b` | Verdict review. |
| `summarization` | `llama3.2:3b` | `llama3.1:8b` | Context compaction. |
| `triage` / `investigation` / `reporting` | as agent table | as agent table | The three the 13 agents map onto. |

Because **investigation** is shared by 9 of the 13 agents, its model choice dominates blue's VRAM footprint and
quality — invest the strongest local model there (Variant B: `llama3.3:70b`).

---

## 3. Wiring red — Decepticon LiteLLM → Ollama

Decepticon already has a first-class Ollama path (`AuthMethod.OLLAMA_LOCAL`). Three env vars turn it on; per-role
overrides realize the tier table.

### 3.1 Core env (`Decepticon/.env`)

```bash
# ── Point the LiteLLM proxy at the host Ollama ──
OLLAMA_API_BASE=http://host.docker.internal:11434    # Linux: needs extra_hosts host-gateway (§1.1)
OLLAMA_MODEL=llama3.1:8b                              # fleet-wide base model (registered as ollama_chat/llama3.1:8b)

# ── Force local-only routing ──
DECEPTICON_AUTH_PRIORITY=ollama_local                 # ONLY method → no cloud fallback ever built
DECEPTICON_MODEL_PROFILE=eco                          # per-agent tiers (moot for Ollama collapse, kept for override composition)

# ── Proxy connection (defaults are fine; shown for completeness) ──
# DECEPTICON_LLM__PROXY_URL=http://localhost:4000
# DECEPTICON_LLM__PROXY_API_KEY=sk-decepticon-master
LITELLM_MASTER_KEY=sk-decepticon-master

# ── Leave EVERY cloud key unset/placeholder ──
# ANTHROPIC_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY, … : DO NOT SET.
# DECEPTICON_AUTH_CLAUDE_CODE=false and all other DECEPTICON_AUTH_* stay false.
```

Setting `DECEPTICON_AUTH_PRIORITY=ollama_local` makes `_detect_available_methods` (`factory.py:580-588`) build a
**single-method** chain — even if a stray cloud key were present, it is never added to any fallback chain because
it is not in the priority list. This is the primary red-side egress guarantee.

### 3.2 Per-role model overrides (realize the tier table)

Add one line per role that should differ from the base `OLLAMA_MODEL`. Values **must** carry the `ollama_chat/`
prefix (the tool-call `/api/chat` route). Each is registered automatically at proxy startup.

```bash
# HIGH code/exploit roles → the coder model
DECEPTICON_MODEL_EXPLOITER=ollama_chat/qwen2.5-coder:32b
DECEPTICON_MODEL_EXPLOIT=ollama_chat/qwen2.5-coder:32b
DECEPTICON_MODEL_PATCHER=ollama_chat/qwen2.5-coder:32b
DECEPTICON_MODEL_CONTRACT_AUDITOR=ollama_chat/qwen2.5-coder:32b
DECEPTICON_MODEL_VULNRESEARCH=ollama_chat/qwen2.5-coder:32b
# HIGH reasoning roles → the reasoning model
DECEPTICON_MODEL_DECEPTICON=ollama_chat/qwen3:32b
DECEPTICON_MODEL_ANALYST=ollama_chat/qwen3:32b
# MID roles → 14B general
DECEPTICON_MODEL_DETECTOR=ollama_chat/qwen2.5:14b
DECEPTICON_MODEL_VERIFIER=ollama_chat/qwen2.5:14b
DECEPTICON_MODEL_CLOUD_HUNTER=ollama_chat/qwen2.5:14b
# … (blue_cell, ad_operator, reverser, phisher, *_operator, forensicator, supply_chain_operator)
# LOW roles inherit the base OLLAMA_MODEL (llama3.1:8b for Variant B) — no override needed,
#   or pin them cheaper: DECEPTICON_MODEL_RECON=ollama_chat/llama3.2:3b
```

> The displaced tier primary is kept as the head of the role's **fallback** chain (`factory._compose_assignment`
> `:1531-1552`), so a bad override still degrades to the base local model rather than erroring.

**Alternative (fewer env lines):** pre-register every model once via
`DECEPTICON_LITELLM_MODELS=ollama_chat/qwen2.5-coder:32b,ollama_chat/qwen3:32b,ollama_chat/qwen2.5:14b,ollama_chat/llama3.2:3b`
(`litellm_dynamic_config.py:454`) and still set the `DECEPTICON_MODEL_<ROLE>` picks. Either way the models must
be **pulled** in Ollama (§1.4) or calls 404.

### 3.3 What NOT to touch

- Do **not** edit `config/litellm.yaml`. The Ollama route is generated dynamically at proxy startup
  (`litellm_startup.py` → `litellm_dynamic_config.py`); the static YAML is cloud-provider definitions only and is
  inert without their API keys.
- Keep `ollama_chat/` (never legacy `ollama/`) — `validate_model_name` rejects `ollama/` with a remediation hint;
  `ollama/` routes to `/api/generate` which cannot do tool calls.

### 3.4 Red sanity check

```bash
# Proxy resolves and serves a local model with tool support:
curl -s http://localhost:4000/v1/models -H "Authorization: Bearer sk-decepticon-master" | grep ollama_chat
decepticon-cli auth        # AuthInventory: resolved_chain == [ollama_local]; no cloud method "active"
```

---

## 4. Wiring blue — Vigil Bifrost → Ollama

Blue is more involved: Vigil resolves models through a DB-backed chain whose **final fallback is a cloud Anthropic
provider** (`model_registry.py:823-828`) and whose failsafe constant is `claude-sonnet-4-6` (`defaults.py:15`).
Sovereignty means (a) create a default **Ollama** provider + per-component rows, and (b) make sure the cloud
fallback can never resolve (no Anthropic row, local `DEFAULT_MODEL`).

### 4.1 Bifrost gateway config — enable Ollama, strip cloud

The seed `vigil/docker/bifrost/config.json` **already ships an `ollama` provider** with `url: env.OLLAMA_URL` and
`models: ["*"]`. For sovereignty, edit the seed to **delete the `anthropic` and `openai` provider blocks** entirely,
leaving only `ollama`:

```jsonc
{
  "$schema": "https://www.getbifrost.ai/schema",
  "client": { "enable_logging": true, "disable_content_logging": false },
  "logs_store": { "enabled": true, "type": "sqlite", "config": { "path": "./logs.db" } },
  "providers": {
    "ollama": {
      "network_config": { "default_request_timeout_in_seconds": 1800, "allow_private_network": true },
      "keys": [{ "name": "default-ollama-url", "weight": 1,
                 "ollama_key_config": { "url": "env.OLLAMA_URL" },
                 "models": ["*"] }]
    }
  }
}
```

Then set, for the **Bifrost container** env (Linux host-native Ollama):
```bash
OLLAMA_URL=http://host.docker.internal:11434     # container-reachable form; needs extra_hosts host-gateway
BIFROST_URL=http://bifrost:8080                  # what the Vigil backend calls (default)
```

> Removing the cloud blocks is defense-in-depth: even if an `ANTHROPIC_API_KEY` leaked into the environment,
> Bifrost has **no anthropic route** to spend it on. Bifrost's live config lives in its own SQLite after first boot
> (`ollama_process.py:205-216`), so re-seed on a clean volume or edit via the admin API.

### 4.2 The wildcard allow-list (already handled)

Vigil's model-catalog sync special-cases Ollama: `sync_provider_models` pins the Bifrost allow-list to `["*"]`
for `provider_type == "ollama"` (`bifrost_admin.py:170-173`) because a self-hosted Ollama serves whatever you
pulled. So you do **not** enumerate Ollama models into Bifrost — the wildcard covers every tag. The sync runs on
backend startup, on a schedule, and after `ollama start` (`ollama_process.py:205-236`). Nothing to do beyond
having the `ollama` provider present in Bifrost (§4.1).

### 4.3 Create the default Ollama provider + per-component rows

These are DB rows in `llm_provider_configs` and `ai_model_configs` (schema: `database/init/10_ai_model_configs.sql`).
Create them via the Settings → AI / LLM Providers UI, or seed SQL. Conceptually:

```sql
-- 1) One Ollama provider, marked default. base_url is the HOST-side URL Vigil uses.
INSERT INTO llm_provider_configs (provider_id, provider_type, base_url, api_key_ref,
                                  default_model, is_active, is_default, config)
VALUES ('ollama-local', 'ollama', 'http://localhost:11434', NULL,
        'llama3.1:8b', TRUE, TRUE, '{}'::jsonb);

-- 2) Per-component model assignments (all point at the ollama provider). Variant B shown.
INSERT INTO ai_model_configs (component, provider_id, model_id) VALUES
  ('chat_default',        'ollama-local', 'qwen2.5:14b'),
  ('triage',              'ollama-local', 'llama3.1:8b'),
  ('investigation',       'ollama-local', 'llama3.3:70b'),
  ('reporting',           'ollama-local', 'qwen2.5:14b'),
  ('orchestrator_plan',   'ollama-local', 'qwen3:32b'),
  ('orchestrator_review', 'ollama-local', 'qwen2.5:14b'),
  ('summarization',       'ollama-local', 'llama3.1:8b')
ON CONFLICT (component) DO UPDATE
  SET provider_id = EXCLUDED.provider_id, model_id = EXCLUDED.model_id;
```

At dispatch, `provider.provider_type == "ollama"` sends the model to Bifrost's OpenAI `/v1` endpoint as
`ollama/<model_id>` (`llm_router.py:380, 465`) — the wildcard allow-list lets it through, Bifrost forwards to the
host Ollama.

> The stock `10_ai_model_configs.sql` seeds `chat_default` **from the default Anthropic provider**
> (`:44-49`). On a sovereign install there is no Anthropic provider, so that seed is a harmless no-op — but you
> **must** insert the Ollama `chat_default` row above, or blue has no resolvable model.

### 4.4 Disable cloud — the four egress cutoffs on the blue side

1. **No Anthropic/OpenAI provider rows** in `llm_provider_configs` → `_default_anthropic_provider()` returns None,
   so the component chain's terminal fallback is dead (`model_registry.py:823-828`).
2. **`DEFAULT_MODEL` → a local model.** Set `DEFAULT_MODEL=llama3.1:8b` (per `defaults.py:14` guidance). Its
   default `claude-sonnet-4-6` is a cloud model and is the failsafe used when no row resolves.
3. **Strip cloud providers from the Bifrost seed** (§4.1) — no route to spend a stray key on.
4. **Leave `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `CLAUDE_API_KEY` unset.** `_dispatch_anthropic` and the
   discovery key-resolver fall back to these env names (`llm_router.py:543`, `bifrost_admin.py:423-426`); unset +
   no rows = nothing to fall back to.

> **Consequence to accept:** with no Anthropic provider, Vigil's Anthropic **passthrough** path
> (`/anthropic`, the only one that carries extended thinking + native prompt caching) is never taken. All blue
> traffic goes down the Ollama `/v1` path. This is the extended-thinking gap addressed in §6.

### 4.5 Blue sanity check

```bash
# Bifrost knows only ollama; wildcard allow-list live:
curl -s http://localhost:8080/api/providers/ollama | jq '.keys[0].models'   # → ["*"]
# Vigil resolves a component to the ollama provider (not anthropic):
#   Settings → AI Model Assignments shows every component → ollama-local
```

---

## 5. Sovereignty verification — proving zero egress (P1 exit gate)

Two layers: **prevention** (make egress impossible) and **proof** (demonstrate none occurred). P1 passes only when
both engines answer a scripted prompt **and** a packet capture shows zero foreign-LLM traffic.

### 5.1 Prevention — default-deny egress firewall

Provision models first (§1.4 needs `registry.ollama.ai`), **then** lock the host down. Prefer default-deny over a
domain blocklist (blocklists rot; new provider endpoints appear).

```bash
# nftables: default-drop OUTBOUND to public internet; allow loopback, LAN/RFC1918, DNS to local resolver.
# Ollama (11434), LiteLLM (4000), Bifrost (8080) are all loopback/inter-container → unaffected.
nft add table inet sov
nft add chain inet sov out '{ type filter hook output priority 0 ; policy drop ; }'
nft add rule  inet sov out oifname "lo" accept
nft add rule  inet sov out ip daddr { 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16 } accept   # LAN + docker nets
nft add rule  inet sov out ct state established,related accept
nft add rule  inet sov out udp dport 53 ip daddr <internal-dns> accept
# Everything else (incl. 443 to api.anthropic.com / api.openai.com / generativelanguage.googleapis.com) is DROPPED.
```

Belt-and-suspenders explicit denies (audit-friendly, catch a misconfig before default-drop does):
```bash
for d in api.anthropic.com api.openai.com generativelanguage.googleapis.com api.x.ai \
         api.deepseek.com api.mistral.ai openrouter.ai router.huggingface.co ollama.com registry.ollama.ai; do
  for ip in $(dig +short $d); do nft add rule inet sov out ip daddr $ip drop; done
done
```
Docker note: container egress traverses the host's `FORWARD`/NAT chains — apply equivalent drops there, or attach
the LLM-path containers to an `internal: true` Docker network (00 §5's `redblue-shared` should be `internal`
for the LLM leg), so containers have no default route off-host at all.

### 5.2 Proof — packet capture during a live engagement

```bash
# Capture all outbound 443 + DNS for provider domains, host-wide, during a full run.
sudo tcpdump -i any -n -w /evidence/sov-$(date +%s).pcap \
  '(tcp port 443 or udp port 53) and not net 10.0.0.0/8 and not net 172.16.0.0/12 and not net 192.168.0.0/16'
```
Run **both** engines through a representative task (red: a scoped recon+exploit engagement; blue: ingest a finding
→ investigator agent → verdict). Then assert the pcap contains **zero** packets to any foreign LLM endpoint. A
green run = the capture is empty (or only local/LAN traffic).

### 5.3 Negative control (prove the guard actually bites)

A verification that never fails proves nothing. Add a deliberate cloud attempt and confirm it is blocked:
```bash
# From the host and from inside the Bifrost container:
curl -sS --max-time 5 https://api.anthropic.com/v1/models ; echo "exit=$?"   # expect timeout / no route (non-zero)
```
Record the failure as evidence alongside the empty pcap.

### 5.4 P1 exit-gate checklist (evidence artifacts → coordinator evidence store, 00 §5/08)

- [ ] Red answers a scripted prompt end-to-end on `ollama_local` only (`decepticon-cli auth` shows single-method chain).
- [ ] Blue answers a scripted finding investigation with every component resolving to `ollama-local`.
- [ ] `tcpdump` pcap over the full run: **zero** foreign-LLM packets. (artifact: `sov-*.pcap`)
- [ ] Negative control: direct `api.anthropic.com` call from host **and** Bifrost container is refused. (artifact: log)
- [ ] nftables OUTPUT counters show non-zero drops on the provider-IP rules. (artifact: `nft list ruleset`)
- [ ] No cloud provider rows in `llm_provider_configs`; `DEFAULT_MODEL` is local; Bifrost config has only `ollama`.

---

## 6. Quality mitigations — closing the local-LLM gap

00 §11 risk #1 is "local-LLM quality drop vs cloud." The concrete mechanisms and mitigations:

### 6.1 The extended-thinking gap (the big one)

**Finding (verified).** Nine of the 13 blue agents set `enable_thinking=True` (investigator, threat_hunter,
correlator, mitre_analyst, forensics, threat_intel, malware_analyst, network_analyst, auto_responder). Extended
thinking is applied **only** on the Anthropic passthrough path (`llm_router._dispatch_anthropic:562-565` →
`build_thinking_kwargs`). The Ollama path is `_dispatch_bifrost_openai` (`:346-428`) which **never sends thinking
kwargs**. On a sovereign deploy, every blue agent goes down the Ollama path → **`enable_thinking` becomes a
silent no-op; `thinking_budget` is ignored.** Same for red: no Ollama extended-thinking concept exists.

Mitigations, in preference order:

1. **Route thinking-heavy agents to a natively-reasoning local model.** Point the `investigation` component (which
   backs 9 agents) and red HIGH-reasoning roles at a model that reasons via `<think>` blocks internally:
   `qwq:32b`, `deepseek-r1:*`, or `qwen3:32b` (thinking-capable and tool-capable per the family list). This
   recovers chain-of-thought depth without needing the API-level thinking parameter. **Trade-off:** reasoning
   models emit long internal traces → higher latency and token use; keep them off LOW/triage roles.
2. **Raise `max_tokens` for reasoning headroom.** The thinking-heavy agents already carry `max_tokens: 16384`
   (`soc_agents.py`), which gives a reasoning model room to think-then-answer in one call. Leave those high.
3. **Accept graceful degradation elsewhere.** For agents where deep thinking is a nice-to-have (triage, reporter,
   compliance — already `enable_thinking=False`), a fast 3B–8B model is fine.
4. **(Optional, later) patch the Ollama path** to translate `enable_thinking` into the model's native reasoning
   switch (e.g. prompt-level "think step by step" or Ollama `think` option). Track as an engine patch in
   `06_RED_BLUE_SEAMS_AND_CONNECTORS.md` — additive, per 00 §3 patch-set rule.

### 6.2 Which agents can run small models

- **Small (3B):** red `recon`/`scanner`/`osint_operator`/`wireless_operator`; blue `triage`, `summarization`.
  High-throughput, shallow reasoning, mostly structured extraction.
- **Mid (8–14B):** red MID tier; blue `responder`/`reporter`/`compliance`/`auto_responder`/`chat_default`.
- **Large (32–70B):** red HIGH tier; blue `investigation` (9 agents) + `orchestrator_plan`. Spend the VRAM here.

### 6.3 Cache & context strategy

- **Prompt caching:** Anthropic native prompt caching (`cache_control`) only exists on the Anthropic passthrough,
  which sovereignty removes. Ollama's own **KV-cache reuse** is the substitute — keep models resident
  (`OLLAMA_KEEP_ALIVE=30m`, §1.2) so the large shared system prompts (BASE_PROMPT + memory-palace block) don't
  re-prefill every call. Cost accounting is moot (`model_registry.py:266,292` price Ollama at $0), so the
  daemon's `max_cost`/`max_hourly_cost` guardrails effectively become **wall-clock/iteration** guardrails — retune
  `ORCHESTRATOR_MAX_COST` to a high sentinel and rely on `max_iterations`/`max_runtime` instead.
- **Context window:** local models have smaller effective context than the cloud models these prompts were tuned
  for. Prefer 32K-context builds (qwen2.5/qwen3 support 32K+; set Ollama `num_ctx` accordingly). Vigil's
  one-shot workflows (memory: `vigil-architecture`) pack a lot into one call — watch for context overflow and lean
  on the `summarization` component to compact.
- **Concurrency vs residency:** one Ollama serving both engines means distinct models contend for VRAM. If red's
  `qwen2.5-coder:32b` and blue's `llama3.3:70b` can't both stay resident, Ollama unloads/reloads between calls
  (seconds of latency). Mitigate by (a) sharing models across engines where the table allows, and (b) sizing VRAM
  to hold the working set (`OLLAMA_MAX_LOADED_MODELS`, §7).

### 6.4 Embeddings must be local too (a quiet egress vector)

- **Red:** Decepticon's skillogy + KG embedding default is `openai/text-embedding-3-small`
  (`litellm.yaml:130`, `.env.example:188`) — a cloud call needing `OPENAI_API_KEY`. With no key it **degrades to
  substring search** (`.env.example:186-187`), which is acceptable but dumber. To keep semantics, register a local
  embedding route and set `DECEPTICON_SKILLOGY_EMBED_MODEL` to it (Ollama `nomic-embed-text`), or leave unset and
  accept substring fallback. **Never set a cloud embedding key.**
- **Blue:** Vigil findings carry `embedding vector(768)` (memory: `vigil-architecture`). Confirm the ingestion
  embedding pipeline is pointed at a local model (Ollama `nomic-embed-text` = 768-dim) or disabled — track in
  `05_DATA_CONTRACTS_AND_SCHEMAS.md`. Any cloud embedding endpoint is an egress leak §5's firewall would catch.

---

## 7. Hardware sizing

Approximate resident VRAM per model (Q4_K_M): 3B ≈ 2–3 GB, 7–8B ≈ 5–6 GB, 14B ≈ 9–10 GB, 32B ≈ 20–22 GB,
70B ≈ 42–48 GB. Add ~1–4 GB per resident model for KV cache at 8–32K context.

| Profile | GPU | Resident working set (both engines) | `OLLAMA_MAX_LOADED_MODELS` | Notes |
|---|---|---|---|---|
| **Demo GPU-light (A)** | 1× 24 GB (RTX 4090 / A10) | `qwen2.5-coder:7b` + `llama3.1:8b` + `llama3.2:3b` ≈ 13 GB | 3 | All three resident; snappy interactive demo. Embeddings on CPU or same GPU. |
| **CPU smoke** | none | one ≤8B model at a time | 1 | Functional tests only; not a live engagement. |
| **Quality single-node (B)** | 1× 80 GB (A100/H100) | `llama3.3:70b` (blue investigation) ~46 GB + `qwen2.5-coder:32b` (red code) swaps with `qwen3:32b` | 1–2 | 70B pins most of the card; the two 32B models contend — expect reload latency, or drop to `qwen2.5:32b` shared. |
| **Quality multi-GPU (B+)** | 2× 48 GB or 4× 24 GB | 70B on GPU-0; 32B + 14B + 8B + 3B across GPU-1(+) | 4–5 | Best throughput; pin with `CUDA_VISIBLE_DEVICES` / Ollama scheduling. Recommended for a real closed-loop run. |

RAM: ≥64 GB host (model load + Postgres/Neo4j/Redis + telemetry stack). Disk: ~150 GB for the Variant B model set
+ blobs. CPU-offload (partial layers) works when VRAM is short but tanks throughput — avoid for live agents.

**Rule of thumb:** the shared-Ollama design is VRAM-bound, not compute-bound. Size to hold the **union** of red's
and blue's active models resident; every model that doesn't fit becomes a reload-latency tax on every turn.

---

## 8. Checklist, acceptance, risks

### 8.1 Build checklist (P0 → P1)

- [ ] Ollama installed host-native, `OLLAMA_HOST=0.0.0.0:11434`, keep-alive + max-loaded tuned (§1.2).
- [ ] Model set pulled for the chosen variant (§1.4), all tool-capable, embeddings model included.
- [ ] LiteLLM (`:4000`) and Bifrost (`:8080`) containers carry `extra_hosts: host.docker.internal:host-gateway` (Linux).
- [ ] **Red:** `OLLAMA_API_BASE`, `OLLAMA_MODEL`, `DECEPTICON_AUTH_PRIORITY=ollama_local`; per-role
      `DECEPTICON_MODEL_<ROLE>=ollama_chat/…` overrides; no cloud keys. `decepticon-cli auth` → single-method chain.
- [ ] **Blue:** Bifrost seed stripped to `ollama` only; `OLLAMA_URL` set; default `ollama-local`
      `LLMProviderConfig`; `ai_model_configs` rows for all 7 components; `DEFAULT_MODEL=<local>`; no cloud rows.
- [ ] Both engines answer a scripted prompt (P0 standalone-on-Ollama).
- [ ] Egress default-deny firewall applied **after** model provisioning; negative control refused (§5.3).
- [ ] Full-run pcap is empty of foreign-LLM traffic; artifacts filed to the evidence store (§5.4).

### 8.2 Acceptance criteria (P1 gate — 00 §8/§10)

1. **Functional:** red completes a scoped engagement and blue completes a finding investigation, both entirely on
   local Ollama, tool calls working.
2. **Sovereign (binary):** packet-capture proof of **zero** foreign-API egress across a full run of both engines,
   plus a passing negative control. This is the non-negotiable P1 exit gate.
3. **Configurable:** switching Variant A ↔ B is env/DB-only (no code changes).

### 8.3 Risks & mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| **Extended-thinking silently disabled** on Ollama path for 9 blue agents (+ red) | Degraded reasoning on the deepest agents | Route `investigation` + red HIGH-reasoning to a native reasoning model (`qwq`/`deepseek-r1`/`qwen3`); optionally patch the Ollama path (§6.1). |
| **Silent cloud fallback** via `DEFAULT_MODEL=claude-sonnet-4-6` / terminal Anthropic provider | Egress + sovereignty breach | Local `DEFAULT_MODEL`, no Anthropic rows, Bifrost stripped to ollama, firewall default-deny (§4.4, §5). |
| **VRAM residency thrash** — 2 large models on one Ollama | Multi-second reload latency per turn | Share models across engines; size VRAM to the union; tune `OLLAMA_MAX_LOADED_MODELS`/`KEEP_ALIVE` (§6.3, §7). |
| **Non-tool-capable model** picked | Agents "call nothing," runs fail silently | Restrict to `_OLLAMA_TOOL_CAPABLE_FAMILIES`; `OLLAMA_EXTRA_TOOL_MODELS` for customs (§1.4). |
| **Embedding egress** (skillogy/KG/finding vectors default to cloud) | Quiet DPDP breach | Local `nomic-embed-text` or accept substring fallback; never set a cloud embed key (§6.4). |
| **Red tier collapse misunderstood** — expecting per-tier models "for free" | Wrong model on wrong role | Realize tiers via `DECEPTICON_MODEL_<ROLE>` overrides; document that Ollama collapses tiers (§2.1, §3.2). |
| **Linux `host.docker.internal` not wired** | Gateways can't reach Ollama; blank failures | `extra_hosts: host-gateway` on LiteLLM + Bifrost, or bind Ollama to host LAN IP (§1.1). |
| **`ollama pull` blocked by the egress lockdown** | Can't add/update models later | Provision behind a maintenance window: lift firewall → pull → re-lock; or run a local model mirror on the LAN. |
| **CPU-only fallback** on a GPU-less node | 3–10 tok/s, unusable for live loop | Enforce GPU presence for engagements; CPU is smoke-test only (§1.3, §7). |

---

## Conflicts with / clarifications to 00_MASTER_PLAN

1. **Ollama is host-native, not a compose service.** 00 §4 lists Ollama under "shared" stack and §5 says "One
   Ollama serves both." Verified engine behavior (`vigil/services/ollama_process.py`) runs Ollama as a **host
   process** (containerizing loses GPU accel), with containers reaching it via `host.docker.internal`. Not a
   contradiction of "one Ollama," but 00 §4/§5 and `02_INFRA_COMPOSE_AND_PORTS.md` should pin: **Ollama on the
   host at `:11434`; LiteLLM/Bifrost containers use `extra_hosts: host-gateway` (Linux).**
2. **"Models per role-tier" is asymmetric between engines.** 00 §6 (`03`) implies a clean per-role-tier model
   table. **Red** does not honor per-tier model IDs on Ollama — `resolve_chain` collapses HIGH/MID/LOW to a single
   `OLLAMA_MODEL`; per-role differentiation is achieved only via `DECEPTICON_MODEL_<ROLE>` overrides. **Blue**
   assigns per *component* (`triage`/`investigation`/`reporting`/…), not per agent. §2–§4 encode this precisely.
3. **Extended thinking does not survive sovereignty (blue).** 00 §11 risk #1 names "local-LLM quality drop"
   generically; the concrete, code-verified mechanism is that Vigil's `enable_thinking`/`thinking_budget` only
   apply on the Anthropic passthrough, which a sovereign deploy removes. Recorded here as the primary quality gap
   (§6.1); the optional Ollama-path thinking patch belongs to the `06` engine patch-set.
4. **Two silent cloud-fallback paths on the blue side** must be explicitly closed (`DEFAULT_MODEL=claude-sonnet-4-6`;
   terminal Anthropic-provider fallback in `resolve_model_for_component`). 00's sovereignty statement assumes local;
   §4.4 makes the cutoffs concrete. Flagging so `08_GOVERNANCE` treats "no cloud provider row + local DEFAULT_MODEL"
   as a governed, audited invariant, not a config nicety.
5. **Embedding egress vector** (skillogy/KG/finding vectors default to cloud embeddings) is not mentioned in 00 but
   is a real DPDP surface; §6.4 routes it local. `05_DATA_CONTRACTS` should confirm the blue finding-embedding
   pipeline is local (768-dim `nomic-embed-text`).
6. **Provisioning vs lockdown ordering.** `ollama pull` needs `registry.ollama.ai`; the §5 default-deny firewall
   blocks it. 00's "zero egress" is a *runtime* invariant — model provisioning happens in a pre-lockdown
   maintenance window (or via a LAN mirror). Worth a one-line note in 00 §8 P0.
