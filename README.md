# RedBlue AI — Autonomous Purple-Team Platform for Sovereign Cloud

> An AI red team that never sleeps, an AI blue SOC that catches it *for real*, and a
> governed brain that scores your defenses and closes the loop — **entirely on local LLM
> inference, with zero foreign-API egress** (built for DPDP / CERT-In on ESDS Sovereign Cloud).

**Status:** coordinator brain feature-complete — **90/90 tests green, ruff-clean**; 6 engine patches
verified; `make smoke` green. Live two-engine bring-up is wired behind tested seams (see
[Project status](#project-status)). Nothing is committed yet — the tree is staged for your review.

---

## Table of contents

- [What is RedBlue AI?](#what-is-redblue-ai)
- [The closed loop](#the-closed-loop)
- [The four moat pillars](#the-four-moat-pillars)
- [What gets attacked?](#what-gets-attacked) — the attacker, the victim, and how to point it at your own app
- [Repository layout](#repository-layout)
- [Prerequisites](#prerequisites)
- [Quickstart](#quickstart) — from clone to a scored engagement in ~5 minutes
- [User guide: the API & what each call returns](#user-guide-the-api--what-each-call-returns)
- [Governance & autonomy tiers](#governance--autonomy-tiers)
- [Sovereignty: proving zero egress](#sovereignty-proving-zero-egress)
- [Continuous mode (CART drift replay)](#continuous-mode-cart-drift-replay)
- [Configuration](#configuration)
- [`make` target reference](#make-target-reference)
- [Testing & quality gates](#testing--quality-gates)
- [Port map](#port-map)
- [How the engines are integrated](#how-the-engines-are-integrated)
- [Project status](#project-status)
- [Security guardrails — read before exposing](#security-guardrails--read-before-exposing)
- [Documentation index](#documentation-index)
- [License](#license)

---

## What is RedBlue AI?

Most "purple team" tooling is a red tool and a blue tool that never actually talk. RedBlue AI
wires three AI security engines into **one continuously-running, self-scoring, governed loop**:

| Engine | Role | Origin (reused, pinned) |
|---|---|---|
| 🔴 **Decepticon** | Autonomous **red** team — ~25 LangGraph agents that recon, exploit & pivot | PurpleAILAB `v1.1.40` |
| 🔵 **Vigil** | Autonomous **blue** AI-SOC — ingests telemetry, triages, investigates, responds | Vigil-SOC / DeepTempo `v0.4.0` |
| 🟡 **vigil-llm** | **Prompt-injection scanner** — hardens both engines against poisoned log data | deadbits `v0.10.3-alpha` |
| 🧠 **redblue-coordinator** | **The brain (new)** — triggers red, waits for blue, scores posture, governs response | this repo |

**We integrate, we don't rebuild.** The three engines are *reproduced* (cloned at pinned SHAs from
`manifest.toml`), never vendored. Every line we author lives in the new directories
(`redblue-coordinator/`, `telemetry/`, `deploy/`) or as **additive** `overlay/` files and `patches/`.
This keeps the engines upgradable and the moat — the coordination, governance, and sovereignty
layer — cleanly ours.

## The closed loop

```
                    ┌──────────────────── redblue-coordinator (LangGraph brain) ────────────────────┐
                    │  plan → trigger_red → await_telemetry → collect_detections → score → decide → report │
                    └──────┬──────────────────────────────────────────────┬───────────────────▲───────────┘
                           │ 1. launch engagement                          │ 4. pull findings   │ 6. governed
                           ▼                                               ▼                    │    response
                   ┌───────────────┐        2. attacks          ┌──────────────────┐            │  (AUTO / HITL / never)
                   │ 🔴 Decepticon │ ─────────────────────────▶ │  Target range /  │            │
                   │   red agents  │                            │   sandbox :9999  │            │
                   └───────────────┘                            └────────┬─────────┘            │
                                                                         │ 3. sensors observe    │
                                                          ┌──────────────▼───────────────┐      │
                                                          │ 🎯 Wazuh · Suricata · Falco   │      │
                                                          └──────────────┬───────────────┘      │
                                                                         ▼                       │
                                                                ┌───────────────┐  5. detections  │
                                                                │  🔵 Vigil SOC │ ────────────────┘
                                                                │  blue agents  │
                                                                └───────────────┘
       🟡 vigil-llm injection shield sits in front of BOTH engines' LLM inputs.
       🧠 All LLM calls → local Ollama :11434 only.  Egress SLI must stay 0.
```

The coordinator emits a **scorecard** for every engagement: which techniques were attacked, which
blue *actually* caught, the **detection rate**, and **MTTD** (mean-time-to-detect) per technique —
plus a tamper-evident, hash-chained **evidence ledger** proving what happened.

## The four moat pillars

The AI engines are commodity. The defensible product is the layer around them:

1. **Sovereignty** — one local Ollama serves both engines (Decepticon → LiteLLM :4000, Vigil →
   Bifrost :8080). A Prometheus SLI (`redblue_external_egress_bytes_total`) and an egress-lockdown
   script prove **zero foreign-API traffic** — the compliance story for DPDP / CERT-In.
2. **The closed loop** — red and blue are joined by a real sensor plane and scored automatically.
   You get a continuously-updated *defensive posture*, not a one-off pentest PDF.
3. **Tiered-autonomy governance** — every response action is classified **AUTO / HUMAN / NEVER-AUTO**.
   Anything crossing a tenant boundary or touching the control plane is fail-closed to `DENY`. Every
   decision is written to a per-tenant **WORM (hash-chained) evidence ledger**.
4. **AI-native defense** — an injection shield (heuristic + vigil-llm) and a verification gate
   ("no verdict without a supporting artifact") defend the *agents themselves* from poisoned logs.
   A built-in **eval harness** red-teams our own AI (agent-hijack rate **must be 0**).

## What gets attacked?

A common first question: *"when I run an engagement, which server / which application does it hit?"*
The coordinator **never attacks anything itself** — it tells the red engine "go" and scores the
result. What actually happens depends on the mode:

- **Test / simulator mode** (`uv run pytest`, the offline eval, every JSON in this README): the red
  engine is a **fake** that returns fixed data. **Nothing is attacked.** This is the laptop-friendly
  path that validates all the logic.
- **Live mode** (`make up` + a target): a real attack runs. Here's exactly what hits what:

```
  Decepticon "sandbox" (Kali)  ──── range-net ────▶   range-dvwa   (the victim)
  container :9999                                     vulnerables/web-dvwa
  ~25 LLM red agents run                              = Damn Vulnerable Web App
  nmap / exploits / pivots                              (a deliberately-broken PHP/MySQL app)
        │                                                      │
        │  the agents CHOOSE which techniques to run           │  Wazuh · Suricata · Falco
        │  at runtime, steered by `instruction` + `in_scope`   ▼  watch it independently → Vigil findings
        └──────────────────── coordinator scores attacked-vs-detected ───────────────────┘
```

| Piece | What it is | Where it's defined |
|---|---|---|
| **The attacker** | Decepticon's **Kali `sandbox` container** (`:9999`) — the only thing that runs offensive tools | Decepticon compose |
| **The victim** | **DVWA** (Damn Vulnerable Web App), container `range-dvwa` — the *only* pre-wired target | `telemetry/docker-compose.telemetry.yml` (profile `target`) |
| **The wire between them** | `range-net` — the sandbox joins it as its *only* extra network, so it can reach the victim but stays **off** the shared bus (the isolation invariant `make health` checks) | telemetry + decepticon overrides |
| **Who picks the attacks** | the ~25 red LLM agents, **at runtime** — not a fixed script | Decepticon engine |

**Bring the live target up** (DVWA sits behind a compose profile, so it's opt-in):

```bash
cd deploy
make up                              # coordinator + Decepticon (the Kali sandbox) + Vigil
make telemetry PROFILES=target       # the sensor plane + the DVWA victim on range-net
# now a live engagement attacks DVWA:
curl -s http://localhost:8900/api/engagements -H 'content-type: application/json' -d '{
  "tenant_id": "acme", "engagement_id": "eng-acme-20260806-dvwa",
  "scope": { "in_scope": ["range-dvwa"], "sandbox_url": "http://sandbox:9999" },
  "instruction": "Recon and exploit the web application on the range."
}' | jq
```

**What the scope fields mean** (they *are* the target selection):

| Field | Meaning |
|---|---|
| `scope.in_scope` | the hosts/addresses red is **allowed** to touch — a hard boundary, not a hint. Point it at the victim (`range-dvwa` or its IP/CIDR). |
| `scope.sandbox_url` | which sandbox red executes *from* (`http://sandbox:9999`) |
| `instruction` | the mission / OPPLAN in plain English — steers *what kind* of attack the agents attempt |

**To attack your *own* application** instead of DVWA, add it as another service on `range-net` and
name it in `in_scope`:

```yaml
# telemetry/docker-compose.telemetry.yml  (under services:)
  my-app:
    image: your/app:tag
    networks: [range-net]
    profiles: [target]
```
```jsonc
"scope": { "in_scope": ["my-app"], "sandbox_url": "http://sandbox:9999" }
```

> ⚠️ **Only ever put systems you own in `in_scope`.** This is live offensive tooling; the `in_scope`
> list is the boundary that keeps it pointed at your range and nothing else.

## Repository layout

```
Purple_Team/
├── manifest.toml            # engine pins (SHA + tag) — engines are reproduced, not vendored
├── setup.sh                 # idempotent bootstrap: clone/pin engines, build the 4 envs, apply overlay+patches
├── redblue-coordinator/     # 🧠 THE BRAIN (new) — Python 3.13 / uv. The LangGraph loop, governance, evidence, API
│   └── redblue/{contracts,loop,governance,continuous,eval,store,evidence,obs,api,config}/
├── telemetry/               # 🎯 sensor plane (new) — Wazuh / Suricata / Falco + a target range
├── deploy/                  # 🐳 unified compose + Makefile (new) — one command brings up the stack
│   ├── docker-compose.redblue.yml, overrides/, env/, Makefile, smoke.sh
│   ├── observability/redblue_posture.json   # Grafana dashboard
│   └── sovereignty/         # egress-lockdown.sh + verify-egress.sh
├── overlay/                 # additive NEW files layered onto engines (Bifrost sovereign cfg, MCP driver, UI console)
├── patches/                 # additive git patches to engine files (tool-tier gate, real isolate_host, …)
├── plans/                   # the 10 authoritative planning docs (00–09)
├── docs/                    # ARCHITECTURE.md, architecture.html (diagram), DEMO.md, ADRs
├── Decepticon/  vigil/  vigil-llm/   # the reused engines (populated by setup.sh; git-ignored)
└── README.md                # you are here
```

---

## Prerequisites

| Need | Why | Minimum |
|---|---|---|
| **[uv](https://docs.astral.sh/uv/)** | builds the Python envs (coordinator, engines) | latest |
| **Docker + Compose v2** | runs the engines, sensors, and Ollama | 24+ |
| **[Ollama](https://ollama.com)** (or the bundled container) | local LLM inference — the sovereignty core | — |
| **git** | clones the pinned engines | 2.30+ |
| **RAM** | | **~14 GB** to run the coordinator + one engine; **≥32 GB** (GPU recommended) for the full red+blue+sensors lab |
| `jq` (optional) | pretty-prints API JSON in examples | — |

> You do **not** need a GPU, 32 GB, or Docker to run the coordinator brain and its full test suite —
> that path is pure Python and validates all the logic. The heavy resources are only for the live
> two-engine + sensor bring-up.

---

## Quickstart

### Step 1 — Bootstrap the superproject

```bash
git clone <this-repo> Purple_Team && cd Purple_Team
./setup.sh                 # clone/pin engines @ manifest SHAs, init Vigil submodules, build the 4 envs, apply overlay+patches
# faster, scaffold + submodules only (skip building the 4 Python envs):
SKIP_ENVS=1 ./setup.sh
```

`setup.sh` is idempotent — safe to re-run. It verifies each engine sits at its pinned SHA, then
provisions four isolated environments (coordinator + Decepticon via `uv sync`, Vigil on Python 3.10,
vigil-llm on an isolated Python 3.9 because it pins `pydantic 1.x`).

### Step 2 — Verify the brain (no Docker, no GPU needed)

```bash
cd redblue-coordinator
uv run pytest -q
```

Expected — the whole coordinator (loop, governance, scoring, evidence, eval, API) validated:

```
90 passed, 1 warning in 1.60s
```

### Step 3 — Run the coordinator API

```bash
cd redblue-coordinator
uv run uvicorn redblue.api:create_app --factory --host 0.0.0.0 --port 8900
# health check:
curl -s http://localhost:8900/api/health
# → {"status":"ok", ...}
```

### Step 4 — Drive an engagement and get a scorecard

`POST /api/engagements` runs the full loop and returns a scorecard summary synchronously:

```bash
curl -s http://localhost:8900/api/engagements -H 'content-type: application/json' -d '{
  "tenant_id": "acme",
  "engagement_id": "eng-acme-20260805-7f3a",
  "scope": { "in_scope": ["range-dvwa"], "sandbox_url": "http://sandbox:9999" }
}' | jq
```

Response — **RedBlue attacked 2 techniques, blue caught 1, so posture = 50% detection, 12s MTTD:**

```json
{
  "engagement_id": "eng-acme-20260805-7f3a",
  "status": "completed",
  "scorecard_id": "sc-eng-acme-20260805-7f3a-v1",
  "detection_rate": 0.5
}
```

That's the loop closing. The next section shows every artifact it produces.

> **⚠️ Which engine ran? Two modes — read this.** The exact scorecard JSON shown throughout
> this README comes from the **test path** (`uv run pytest` and the offline harness), where the
> red engine is a **simulator** — *nothing is actually attacked*; it returns fixed data so the loop,
> scoring, and governance can be validated on a laptop. `10.20.0.9` etc. are placeholder values.
>
> A **live** `POST /api/engagements` (against a bare coordinator with no engines up) instead returns
> `502` — it tries to reach Decepticon at `langgraph:2024` and can't. To make a *real* attack happen
> you need the engines + a target up (`make up` and a target profile). See
> [What gets attacked?](#what-gets-attacked) for exactly what runs against what.

### Step 5 — Bring up the live stack (optional, heavy)

From `deploy/` — pick the slice you have resources for:

```bash
cd deploy
make ollama       # P1: shared local Ollama (:11434) — the sovereignty core
make red-only     # Decepticon standalone (LangGraph :2024, sandbox :9999)
make blue-only    # Vigil SOC standalone (:6987, UI :6988)
make lab PROFILES=target   # red + blue + sensor plane + the DVWA victim (attack the range, watch Vigil findings)
make up           # the full loop incl. the coordinator, then `make health`
make health       # probe every cross-stack endpoint + the sandbox-isolation invariant
make smoke        # "does the loop close?" gate — live if coordinator is up, else logic-smoke
make eval         # the red-team-of-the-AI eval (the demo proof asset)
make down         # stop everything, keep volumes
```

---

## User guide: the API & what each call returns

Base URL `http://localhost:8900`. All outputs below are **captured verbatim** from the running
coordinator so you know exactly what to expect.

### Engagements

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/engagements` | Run the full red→blue→score loop; returns the scorecard summary |
| `GET` | `/api/engagements` | List engagements |
| `GET` | `/api/engagements/{id}` | One engagement's status |
| `GET` | `/api/engagements/{id}/scorecard` | The full posture scorecard |
| `GET` | `/api/engagements/{id}/evidence?verify=true` | The hash-chained WORM evidence ledger (+ integrity check) |
| `GET` | `/api/engagements/{id}/events` | **Server-Sent Events** — live stream of loop node transitions |

#### The scorecard — `GET /api/engagements/{id}/scorecard`

This is the core deliverable: attacked-vs-detected, broken down per technique and per individual
attack instance, with MTTD and the **gaps** (attacks that slipped past blue).

```json
{
  "scorecard_id": "sc-eng-acme-20260805-7f3a-v1",
  "engagement_id": "eng-acme-20260805-7f3a",
  "tenant_id": "acme",
  "version": 1,
  "window": { "t_start": 1000.0, "t_end": 1005.0, "settle_deadline": 1125.0 },
  "attacked_techniques": ["T1046", "T1190"],
  "detected_techniques": ["T1046"],
  "gaps": [
    { "technique_id": "T1190", "entity": "10.20.0.9", "first_attack_ts": 1001.0, "suggested_control": null }
  ],
  "detection_rate": 0.5,
  "mttd": { "mean": 12.0, "median": 12.0, "p90": 12.0 },
  "per_technique": [
    { "technique_id": "T1046", "attacked": 1, "detected": 1, "missed": 0, "detection_rate": 1.0, "mttd_seconds": 12.0 },
    { "technique_id": "T1190", "attacked": 1, "detected": 0, "missed": 1, "detection_rate": 0.0, "mttd_seconds": null }
  ],
  "per_finding": [
    { "technique": "T1046", "entity": "10.20.0.9", "red_action_id": "FIND-001", "red_action_ts": 1000.0,
      "blue_finding_id": "f-20260805-abcdef0123456789", "blue_detect_ts": 1012.0, "detected": true, "mttd_seconds": 12.0 },
    { "technique": "T1190", "entity": "10.20.0.9", "red_action_id": "FIND-002", "red_action_ts": 1001.0,
      "blue_finding_id": null, "blue_detect_ts": null, "detected": false, "mttd_seconds": null }
  ],
  "evidence_refs": ["47d5c4f119bea102df46e2194afdef9e3aaf04d566937cf2d09aef5463865297"]
}
```

**How to read it:** `T1046` (network scan) was caught in 12s → good. `T1190` (exploit public-facing
app) was **missed** → it appears in `gaps`, dragging `detection_rate` to 0.5. `evidence_refs` links
the scorecard to its entry in the tamper-evident ledger below.

#### The evidence ledger — `GET /api/engagements/{id}/evidence?verify=true`

Every step is appended to a **per-tenant, HMAC hash-chained** ledger. `verify=true` re-walks the
chain and returns `"verified": true` only if no record was altered (a broken link reports the first
bad sequence number).

```json
{
  "engagement_id": "eng-acme-20260805-7f3a",
  "records": [
    { "seq": 0, "ts": 1000.0, "actor": "coordinator", "record_type": "engagement.planned",
      "prev_hash": "0000…0000", "this_hash": "97bb474e…0db4c" },
    { "seq": 1, "ts": 1000.0, "actor": "red", "record_type": "red.launched",
      "ref": { "thread_id": "eng-acme-20260805-7f3a", "run_id": "run-42" },
      "prev_hash": "97bb474e…0db4c", "this_hash": "e9061baa…630fa1" },
    { "seq": 2, "ts": 1000.0, "actor": "coordinator", "record_type": "telemetry.collected", "…": "…" },
    { "seq": 3, "ts": 1000.0, "actor": "coordinator", "record_type": "scorecard.produced",
      "ref": { "scorecard_id": "sc-eng-acme-20260805-7f3a-v1" }, "…": "…" },
    { "seq": 4, "ts": 1000.0, "actor": "coordinator", "record_type": "engagement.completed", "…": "…" }
  ],
  "count": 5,
  "verified": true
}
```

*(Each record also carries a `payload_hash`; hashes are abbreviated here — the API returns them in
full.)* This is your audit trail: who did what, in order, provably un-tampered.

#### Live event stream — `GET /api/engagements/{id}/events` (SSE)

```bash
curl -N http://localhost:8900/api/engagements/eng-acme-20260805-7f3a/events
```

Streams each loop node as it fires (`plan_engagement`, `trigger_red`, `await_telemetry`,
`collect_detections`, `score`, `decide_response`, `report_evidence`) — wire it to a dashboard for a
live "watch the loop run" view.

### Posture — `GET /api/posture`

The org-wide roll-up across all engagements — the number a CISO watches:

```json
{
  "engagements": 1,
  "totals": { "attacked": 2, "detected": 1 },
  "detection_rate": 0.5,
  "attacked_techniques": ["T1046", "T1190"],
  "detected_techniques": ["T1046"],
  "attack_coverage": { "attacked": 2, "detected": 1 },
  "mttd": { "mean": 12.0, "median": 12.0, "p90": 12.0 },
  "gap_count": 1,
  "top_gaps": [
    { "technique_id": "T1190", "entity": "10.20.0.9", "first_attack_ts": 1001.0, "suggested_control": null }
  ]
}
```

### The AI self-eval — `GET /api/eval/injection`

Runs the **red-team-of-the-AI** harness against a held-out corpus: can a poisoned log line hijack our
own agents? The hard gate is `agent_hijack_rate == 0` and `passed == true`.

```json
{
  "total": 11, "injections": 7, "benign": 4,
  "caught": 7, "missed": 0, "false_positives": 0,
  "injection_catch_rate": 1.0,
  "false_positive_rate": 0.0,
  "precision": 1.0,
  "recall": 1.0,
  "canary_leak_rate": 0.0,
  "agent_hijack_rate": 0.0,
  "verification_reject_rate": null,
  "grounding_compliance": null,
  "passed": true,
  "detail": { "tp": 7, "fp": 0, "fn": 0, "tn": 4, "hijack_cases": 3, "hijacks": 0, "canaries": 2, "leaks": 0 }
}
```

**What "good" looks like:** catch every injection (`injection_catch_rate 1.0`) with **no** false
positives, **zero** agent hijacks, **zero** canary leaks. This is the demo proof asset — also runnable
offline via `make eval`.

### Prometheus metrics — `GET /metrics`

Plain-text exposition (also scraped on `:8902`). The SLIs the posture dashboard renders:

```
redblue_engagements_total{mode="on_demand",status="completed"} 1.0
redblue_attacks_total 2.0
redblue_detected_total 1.0
redblue_mttd_seconds_bucket{le="15.0"} 1.0
redblue_mttd_seconds_sum 12.0
redblue_mttd_seconds_count 1.0
redblue_external_egress_bytes_total 0.0      # ← the sovereignty guardrail: MUST stay 0
```

Also exported: `redblue_actions_total{tier=…}` (autonomy actions by tier) and
`redblue_quarantined_total{reason=…}` (detections the shield/verification gate held back).

### Kill switch — `POST /api/kill` · `POST /api/tenants/{id}/kill`

Global or per-tenant emergency stop — halts autonomous action immediately. Use it as the
break-glass control before granting any AUTO autonomy.

### Drift / continuous replay

Covered in [Continuous mode](#continuous-mode-cart-drift-replay) below.

---

## Governance & autonomy tiers

Every response action the coordinator considers is classified before it can run:

| Tier | Meaning | Example |
|---|---|---|
| **AUTO** | Runs autonomously (in-tenant, reversible, high-confidence) | tag a host, open a ticket, enrich an alert |
| **HUMAN** | Pauses for an approver (`interrupt()` / HITL) | isolate a host, block an IP |
| **NEVER-AUTO** | Fail-closed `DENY` — never automatable | anything crossing a **tenant boundary** or touching the **control plane** |

The policy engine evaluates the **boundary predicate first** (fail-closed → `DENY` on any doubt),
then a **confidence gate** (Vigil-origin actions missing a confidence score fail closed). Approvals
require the tenant's configured `required_approvers`. Every decision — allow, hold, or deny — is
written to the WORM evidence ledger. Default posture is conservative: `force_manual = true` per tenant
until you deliberately grant autonomy.

---

## Sovereignty: proving zero egress

The whole point is that **no prompt, log line, or finding ever leaves the sovereign boundary.**

- **One local Ollama (`:11434`)** serves both engines — Decepticon via LiteLLM (`:4000`), Vigil via
  Bifrost (`:8080`, using `overlay/vigil/docker/bifrost/config.sovereign.json`). No OpenAI/Anthropic/
  Google keys are wired in the sovereign path.
- **The egress SLI** `redblue_external_egress_bytes_total` must read `0`. Alert on any non-zero value.
- **Lock it down and prove it:**

```bash
cd deploy/sovereignty
./egress-lockdown.sh     # drop egress to non-allowlisted hosts at the Docker-network level
./verify-egress.sh       # attempt calls to public LLM APIs; expect them all to FAIL (that's a pass)
```

See `docs/adr/0002-sovereignty-local-llm.md` for the decision record.

---

## Continuous mode (CART drift replay)

Beyond on-demand engagements, RedBlue runs **continuously**: when your infrastructure changes, it
re-attacks the changed surface automatically — with a safety budget and a human gate on first run.

```bash
# 1. Feed an infra change event (a new service, a config drift, …):
curl -s -X POST http://localhost:8900/api/engagements/eng-acme-20260805-7f3a/drift \
  -H 'content-type: application/json' \
  -d '{ "kind": "service_added", "entity": "10.20.0.42", "detail": "new public nginx" }'
# → a debounced, budget-checked ReplayPlan. The FIRST replay of an engagement is dry-run (needs approval).

# 2. Approve it to run live and re-score:
curl -s -X POST http://localhost:8900/api/engagements/eng-acme-20260805-7f3a/drift/<plan_id>/approve
```

Guardrails baked in: **debounce** (`REDBLUE_DRIFT_DEBOUNCE_S`, default 300s — collapses chatty infra
events) and a **replay budget** (`REDBLUE_MAX_REPLAYS_PER_HOUR`, default 6). Budget is consumed by
live replays, not dry-runs.

---

## Configuration

All coordinator settings use the `REDBLUE_` env prefix (via `.env` or environment). The most useful:

| Env var | Default | Purpose |
|---|---|---|
| `REDBLUE_LANGGRAPH_URL` | `http://langgraph:2024` | Decepticon red-engine endpoint |
| `REDBLUE_VIGIL_URL` | `http://backend:6987` | Vigil blue-SOC endpoint |
| `REDBLUE_VIGIL_TOKEN` | `""` | Vigil service JWT (empty = DEV_MODE enclave; set for prod) |
| `REDBLUE_OLLAMA_URL` | `http://ollama:11434` | local inference (sovereignty core) |
| `REDBLUE_DECEPTICON_NEO4J_URI` | `bolt://neo4j:7687` | red engine knowledge graph |
| `REDBLUE_DB_URL` | `sqlite:///./redblue.db` | coordinator store |
| `REDBLUE_CHECKPOINTER` | `sqlite` | LangGraph checkpointer: `memory` or `sqlite` |
| `REDBLUE_TELEMETRY_SETTLE_S` | `120.0` | how long to wait for sensors to report before scoring |
| `REDBLUE_SANDBOX_URL` | `http://sandbox:9999` | the isolated target range |
| `REDBLUE_DRIFT_DEBOUNCE_S` | `300.0` | CART: collapse chatty infra events |
| `REDBLUE_MAX_REPLAYS_PER_HOUR` | `6` | CART: replay budget cap |
| `REDBLUE_SERVICE_TOKEN` | `""` | coordinator API auth token |
| `REDBLUE_API_PORT` / `REDBLUE_METRICS_PORT` | `8900` / `8902` | API + metrics ports |

Per-tenant governance policy (approvers, `force_manual`, boundaries) lives in
`redblue/config/tenants.py`. Engine pins live in `manifest.toml`.

---

## `make` target reference

Run from `deploy/`.

| Target | What it does |
|---|---|
| `make net` | create the shared `redblue-shared` Docker network (idempotent) |
| `make ollama` | bring up the shared local Ollama (`:11434`) |
| `make red-only` | Decepticon standalone (core profile) |
| `make blue-only` | Vigil SOC standalone (core profile) |
| `make telemetry` | the sensor plane — Wazuh / Suricata / Falco (**heavy**; needs `vm.max_map_count=262144`). Add `PROFILES=target` to also start the DVWA victim |
| `make lab` | red + blue + telemetry (the purple loop minus the coordinator) |
| `make up` | the full loop incl. coordinator, then `make health` |
| `make health` | probe LangGraph / Vigil / Ollama / coordinator + assert the sandbox is **not** on the shared net |
| `make config` | acceptance gate — every compose project renders |
| `make smoke` | "does the loop close?" (live if coordinator up, else logic-smoke) |
| `make eval` | the red-team-of-the-AI eval (falls back to running the harness offline) |
| `make posture-dashboard` | instructions to import the Grafana dashboard |
| `make down` / `make clean` | stop (keep volumes) / stop + prune **safe** volumes only |

---

## Testing & quality gates

```bash
cd redblue-coordinator
uv run pytest -q          # → 90 passed         (the whole brain: loop, governance, scoring, evidence, eval, API)
uv run ruff check .       # → lint clean
cd ../deploy
make config               # → every compose project renders (decepticon ✓ vigil ✓ telemetry ✓ coordinator ✓)
make smoke                # → the loop-closes gate
make eval                 # → injection_catch_rate 1.0, agent_hijack_rate 0.0, passed true
```

The 90 tests include a regression suite from an adversarial self-review (correlation windows, MTTD
sign, fail-closed confidence gates, evidence-chain integrity, the ReAct injection heuristic, CART
budget accounting, and more). The 6 engine patches are verified to reverse-apply cleanly *and*
behavior-checked.

---

## Port map

| Service | Port | | Service | Port |
|---|---|---|---|---|
| 🧠 Coordinator API | `8900` | | 🔵 Vigil backend | `6987` |
| 🧠 Coordinator metrics | `8902` | | 🔵 Vigil frontend | `6988` |
| 🔴 Decepticon LangGraph | `2024` | | 🔵 Vigil Bifrost (LLM gw) | `8080` |
| 🔴 Decepticon LiteLLM | `4000` | | 🔵 Vigil Postgres | `5432` |
| 🔴 Decepticon Neo4j | `7687` | | 🔴 Decepticon Postgres | `5433` |
| 🔴 Decepticon sandbox | `9999` | | 🔵 Redis | `6379` |
| 🧠 Ollama (shared) | `11434` | | 🟡 vigil-llm scanner | `5000` |
| 🎯 Wazuh indexer / API | `9200` / `8443` | | 📊 Grafana / Prometheus | `3001` / `9095` |

The **sandbox (`:9999`) is deliberately kept off the shared network** — `make health` asserts this
isolation invariant and reports an "ISOLATION BREACH" if it's violated.

---

## How the engines are integrated

We never fork the engines. Changes are strictly additive so the pins in `manifest.toml` can be bumped
after re-testing:

- **`overlay/`** — *new* files layered onto an engine: the Bifrost sovereign config, the
  Decepticon MCP driver, the single-origin coordinator console (Posture + Engagements screens) in the
  Vigil UI.
- **`patches/`** — small git patches to *existing* engine files, e.g.
  `0002-tool-tier-verb-gate` (routes dangerous red verbs + 4 blue action types through the approval
  gate) and the real `isolate_host` action (mock → fail-closed).
- **`setup.sh`** reproduces each engine at its pinned SHA, then applies overlay + patches. Bump a
  SHA only after re-testing the additive set against the new engine revision.

---

## Project status

The full P0–P9 build is **complete at the logic level**. Everything that can be validated without a
32 GB GPU box + running engines is done and tested; the live slices are wired behind those same
tested seams and documented as deferred.

| Phase | Scope | State |
|---|---|---|
| P0–P3 | repo scaffold, compose/ports, sovereignty + local LLM, sensor plane | ✅ built |
| P4 | data contracts & schemas (canonical finding, events, scorecard, evidence) | ✅ built, tested |
| P5 | red/blue seams & connectors | ✅ built, tested |
| P6 | coordinator LangGraph loop + injection shield | ✅ built, tested |
| P7 | API surface + store + observability | ✅ built, tested |
| P8 | governance, tiered autonomy, AI-native defense, eval harness | ✅ built, tested |
| P9 | UI console, dashboards, testing roadmap | ✅ built |

**Deferred to a resourced host (all behind tested seams):** real two-engine bring-up; packet-level
proof of egress = 0; the Vigil frontend production build + Playwright run; wiring `VigilLlmHttpScanner`
to a live vigil-llm service; live AUTO execution with `interrupt()`-based HITL resume; Decepticon's
in-engine `/cart/replay`.

---

## Security guardrails — read before exposing

- **This is offensive tooling. Only ever point it at systems you own** (the sandbox range / your own
  tenants). The `in_scope` list in an engagement is a boundary, not a suggestion.
- **`DEV_MODE=true` bypasses all Vigil auth** — it is for the local enclave only and **must be off**
  before Vigil is exposed. Set `REDBLUE_VIGIL_TOKEN` / a service JWT for anything real.
- **Keep the HITL and egress guardrails on.** Don't grant AUTO autonomy until you've tested the kill
  switch and confirmed `redblue_external_egress_bytes_total` stays 0.
- **Secrets live only in `.env`** (git-ignored) — never commit them.
- **vigil-llm caveat:** its `GET /settings` endpoint leaks the configured OpenAI key (a redaction
  key-name mismatch) and it ships no auth — keep it on an internal network only, and in the sovereign
  config use `input_scanners = transformer,yara` (both fully local/offline).
- GPL/AGPL sensor components (Wazuh, Suricata) stay arm's-length — **deployed, never forked**.

---

## Documentation index

| Doc | What's in it |
|---|---|
| `plans/00_MASTER_PLAN.md` | authoritative decisions: layout, port map, networks, tech stack, naming, roadmap |
| `plans/01`–`09` | the detailed per-phase plans |
| `docs/ARCHITECTURE.md` | the architecture in Mermaid |
| `docs/architecture.html` | the rendered architecture diagram (shareable) |
| `docs/DEMO.md` | a 10-minute pitch / demo walkthrough |
| `docs/adr/0001…0003` | architecture decision records (repo structure, sovereignty, telemetry) |
| `redblue-coordinator/README.md` | the coordinator package internals |
| `overlay/vigil/REDBLUE_CONSOLE.md` | the single-origin UI console |

---

## License

Apache-2.0. The reused engines retain their own licenses. GPL/AGPL sensor components
(Wazuh, Suricata, Shuffle) are deployed arm's-length and never forked; the coordinator is **never**
built on AGPL code.
