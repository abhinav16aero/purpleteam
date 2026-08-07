# 01 — Repo Structure, Submodules, Environments & Bootstrap

> **Status:** Planning (pre-code). **Owner:** ESDS RedBlue AI team.
> **Conformance:** This doc conforms to `00_MASTER_PLAN.md` — directory layout (§3),
> port map (§4), naming (§7), phases (§8). Where I resolve a decision that `00` explicitly
> delegated here ("git subtree/submodule — see 01"), I record it in **§9 Conflicts &
> reconciliation** rather than diverging silently.
> **Phase:** primarily **P0** (Prereqs & standalone) per `00` §8, with hooks into P3 (red→blue seam patches).

---

## 0. Ground truth — what is actually on disk (verified 2026-08-05)

All three engines are **independent git repositories** (each has its own `.git`; the umbrella
`/home/abhinav/Desktop/Purple_Team/` is **not** a git repo). All three are **Apache-2.0**. All
three working trees are **clean** (no uncommitted local edits — important: our patch strategy in §3
starts from a pristine base).

| Repo | Remote (`origin`) | HEAD | Last tag | Runtime Python | Env / build |
|---|---|---|---|---|---|
| `Decepticon/` | `github.com/PurpleAILAB/Decepticon.git` | `e34afba0` | `v1.1.40` | **3.13** (`.python-version`) | **uv workspace** (`package=false`; members `packages/*`) + Go launcher + Next.js web |
| `vigil/` | `github.com/Vigil-SOC/vigil.git` | `311790e` | `v0.4.0` | **3.10+** (claude-agent-sdk needs ≥3.10) | **venv + pip** (`venv/`), Docker for PG/Redis/Bifrost |
| `vigil-llm/` | `github.com/deadbits/vigil-llm.git` | `f2b4c13` | `v0.10.3-alpha` | **3.9+** | **pip** (`setup.py`), Flask :5000 + Streamlit, own `Dockerfile` |

**Decepticon uv workspace** — root `pyproject.toml`: `name="decepticon-workspace"`, `package=false`,
`requires-python=">=3.13"`, `[tool.uv.workspace] members=["packages/*"]`. The three real packages:
`packages/decepticon`, `packages/decepticon-core`, `packages/decepticon-sdk` (all workspace sources).

### 0.1 Vigil submodules — the three "empty" ones (the user's explicit question)

`vigil/.gitmodules` declares three submodules; `git -C vigil submodule status` shows all three
with a **leading `-`** (uninitialized / empty working dirs). **All three upstreams are public and
reachable right now** (tested with `git ls-remote` + fetch-by-SHA, all exit 0):

| Submodule (path) | URL | Pinned gitlink SHA | Upstream `HEAD` today | What it provides | Fetch verified |
|---|---|---|---|---|---|
| `deeptempo-core` | `github.com/DeepTempo/deeptempo-core.git` | `5c96abac` | `5c96abac` (== pin) | Core AI/detection lib incl **LogLM** (log-anomaly model), embeddings/detection primitives | ✅ |
| `mcp-servers` | `github.com/DeepTempo/deeptempo-mcp-servers.git` | `834f1cd7` | `834f1cd7` (== pin) | **MCP tool server implementations** Vigil's agents call | ✅ |
| `mempalace` | `github.com/MemPalace/mempalace.git` | `9b35d9f7` | `1d113e46` (pin is **older**) | **Agent long-term memory** (MemPalace); pulls `chromadb` transitively | ✅ (fetch-by-SHA of the older pin succeeds) |

**Two facts that change how we handle these** (both verified in `vigil/scripts/lib.sh`):

1. **`vigil/requirements.txt` installs them as editable, at the very top:**
   ```
   -e ./deeptempo-core
   -e ./mcp-servers
   -e ./mempalace
   ```
   A naive `pip install -r vigil/requirements.txt` **hard-fails** on these lines while the dirs are
   empty (no `setup.py`/`pyproject.toml` to install).

2. **But Vigil's own bootstrap does NOT fail — it silently degrades.** `install_python_deps()` runs
   through `filtered_reqs()`, which **drops any `-e ./dir` whose dir lacks `setup.py`/`pyproject.toml`**:
   ```bash
   if [[ "$line" =~ ^-e[[:space:]]+\. ]]; then
       dir=...; [ -f "$dir/setup.py" ] || [ -f "$dir/pyproject.toml" ] || continue   # skip empty submodule
   fi
   ```
   And `vigil/start.sh` auto-inits: `if [ ! -f deeptempo-core/pyproject.toml ]; then git submodule update --init --recursive; fi`.

   **Net:** `./setup_dev.sh` / `./start.sh` on an internet-connected host will **init the submodules
   and install them**; if init fails (offline/private), the run **continues without them** and the
   deeptempo/MCP/memory features are **silently absent**. The failure mode is *missing capability*,
   not *crash* — but any code path that `import`s these packages will raise at runtime unless guarded.

### 0.2 Decepticon also has (its own, separate) submodules

`Decepticon/.gitmodules`: `benchmark/xbow-validation-benchmarks` and `benchmark/MHBench` (branch
`decepticon`). These are **benchmark-only** — *not* on the runtime path for a standalone engagement.
Leave them **uninitialized** for P0; init only when running `make benchmark`.

---

## 1. Repo organization strategy — decision & justification

### 1.1 Options considered

| Option | Mechanism | Upstream `git pull` stays easy? | New code isolation | Blast radius of an engine bump | Verdict |
|---|---|---|---|---|---|
| **A. Keep-as-is siblings + thin superproject + manifest pin** | 3 engines stay independent checkouts; a new git repo versions only `redblue-coordinator/`, `telemetry/`, `deploy/`, `docs/`, `plans/`, `overlay/`, `patches/`, `setup.sh`; engines pinned by a `manifest` file | **Yes** — each engine keeps its own `origin`; `git -C vigil pull` just works | **Total** — new code never touches engine trees | Small, controlled | **✅ RECOMMENDED** |
| B. Nest engines as **git submodules** of the superproject | superproject records engine gitlinks | Yes but noisy (detached HEADs, `--recursive` init pain — and Vigil already nests 3 of its *own* submodules → **submodules-in-submodules**) | Total | Medium; recursive-init fragility | ❌ (adds a 2nd submodule layer over Vigil's existing 3) |
| C. **git subtree** the engines into the superproject | engine history squashed/merged into one tree | Painful — subtree pull/push per engine, history bloat (~262k LOC combined) | Poor — engine code now lives in *our* history | Large | ❌ |
| D. **Monorepo** (merge all four into one tree) | one `.git`, one history | Upstream merges become manual conflict resolution forever | Poor | Very large | ❌ (kills the "engines are commodity, keep them mergeable" moat) |

### 1.2 Decision: **Option A** — siblings + thin superproject + manifest pin

**Rationale.** The moat (per `redblue-strategic-moat` memory) is *the glue + governance +
sovereignty*, not the engines. The engines are upstream-tracked commodities we must keep **cheaply
re-pullable**. Nesting them (B/C/D) couples our history to theirs and — for Vigil specifically —
stacks a second submodule layer on top of its existing three. Option A keeps each engine a pristine,
independently-updatable checkout, confines 100% of our authored code to three new dirs, and makes
engine upgrades a two-step ritual (bump manifest → re-apply overlay/patches → re-test) instead of a
merge war.

### 1.3 Concrete git layout

Create **one** new git repo — the *superproject* — rooted at `Purple_Team/`, that **tracks only the
new dirs** and **ignores the three engine trees** (they keep their own `.git`):

```
/home/abhinav/Desktop/Purple_Team/            # NEW superproject git repo (git init here)
├── .git/                                      #   ← the ONLY new .git; engines keep theirs
├── .gitignore                                 #   ignores Decepticon/ vigil/ vigil-llm/ + envs/secrets
├── manifest.toml                              #   PINS each engine: url + tag + tested-good SHA  (§1.4)
├── setup.sh                                   #   idempotent bootstrap (§5)
├── LICENSE                                    #   Apache-2.0 (matches engines)
├── plans/                                     #   00–09 planning docs  (tracked)
├── docs/                                      #   ADRs, runbooks           (tracked — create)
├── redblue-coordinator/                       #   NEW (tracked)  — Python 3.13 / uv / LangGraph
│   ├── redblue/  { loop, connectors, scoring, governance, evidence, api, config }
│   ├── tests/
│   └── pyproject.toml
├── telemetry/                                 #   NEW (tracked)  — wazuh/ suricata/ falco/ target-range/ + compose
├── deploy/                                    #   NEW (tracked)  — docker-compose.redblue.yml, .env.example, Makefile, k8s/
├── overlay/                                   #   NEW (tracked)  — additive NEW files dropped into engines  (§3 Tier A)
│   ├── vigil/…                                #     e.g. services/decepticon_ingestion.py
│   ├── Decepticon/…
│   └── vigil-llm/…
├── patches/                                   #   NEW (tracked)  — in-place edits to EXISTING engine files  (§3 Tier B)
│   ├── vigil/0001-isolate_host-real-action.patch
│   ├── vigil/0002-tool-tier-verb-gate.patch
│   └── vigil/0003-daemon-workflow-step-map.patch
│
├── Decepticon/    ← gitignored by superproject; keeps origin PurpleAILAB/Decepticon
├── vigil/         ← gitignored; keeps origin Vigil-SOC/vigil  (+ its own 3 submodules)
└── vigil-llm/     ← gitignored; keeps origin deadbits/vigil-llm
```

- **How the new dirs are versioned:** normal files in the superproject repo. `redblue-coordinator/`,
  `telemetry/`, `deploy/`, `overlay/`, `patches/`, `docs/`, `plans/`, `manifest.toml`, `setup.sh` are
  all committed here. This is the repo we push to ESDS's internal GitLab/GitHub.
- **How the engines are versioned:** *not* by the superproject. They are reproduced deterministically
  by `setup.sh` from `manifest.toml` (clone at pinned SHA). The superproject's `.gitignore` excludes
  their trees so we never accidentally commit 262k LOC of vendored engine code.

### 1.4 `manifest.toml` — the pin that makes bootstrap reproducible

```toml
# manifest.toml — engines are reproduced, not vendored. Bump a SHA only after re-test.
[engines.decepticon]
url    = "https://github.com/PurpleAILAB/Decepticon.git"
tag    = "v1.1.40"
sha    = "e34afba0…"          # tested-good; setup.sh checks out this exact SHA
submodules = []               # benchmark submodules stay OFF for P0

[engines.vigil]
url    = "https://github.com/Vigil-SOC/vigil.git"
tag    = "v0.4.0"
sha    = "311790e…"
submodules = ["deeptempo-core", "mcp-servers", "mempalace"]   # INIT these (§2)

[engines.vigil-llm]
url    = "https://github.com/deadbits/vigil-llm.git"
tag    = "v0.10.3-alpha"
sha    = "f2b4c13…"
submodules = []
```

### 1.5 Keeping upstream mergeable

Upgrading an engine is a **ritual, not a merge**:

```bash
# 1. update the checkout in place (works because each engine kept its own origin)
git -C vigil fetch origin --tags
git -C vigil checkout <new-tag>            # detached at the new release
# 2. re-apply our additive layer (idempotent; §3)
./setup.sh --apply-overlay --apply-patches # copies overlay/, git-apply patches/
# 3. if a patch no longer applies cleanly → the upstream file moved: regenerate that ONE patch
# 4. re-run smoke; if green, bump manifest.toml [engines.vigil].{tag,sha} and commit
```
Because our code is 100% in `overlay/` (new files → never conflict) and `patches/` (small, targeted
diffs against existing files), an upstream bump touches at most the handful of patches whose target
files moved. Everything else is invariant by construction.

---

## 2. Submodule handling — init vs vendor vs stub (the explicit ask)

The user asked specifically about **moving/copying** the empty Vigil submodules. Given the verified
facts in §0.1 (**all three upstreams are public and reachable**), the answer is clear and cheap.

### 2.1 Primary path — **initialize from upstream** (recommended; network confirmed)

```bash
cd /home/abhinav/Desktop/Purple_Team/vigil

# Init + fetch + checkout the pinned SHAs for all three:
git submodule update --init --recursive
#   (bandwidth-lean variant — full history is unnecessary for a pinned SHA:)
# git submodule update --init --recursive --depth 1

# Verify — success = NO leading '-' on any line (a '+' means checked-out-but-not-at-pin):
git submodule status
#   expect:
#    5c96abac… deeptempo-core (heads/main)
#    834f1cd7… mcp-servers    (heads/main)
#    9b35d9f7… mempalace      (…)      ← note: OLDER than upstream HEAD 1d113e46 by design

# Then the editable installs in requirements.txt resolve normally (done inside vigil's venv in §5):
#   -e ./deeptempo-core  -e ./mcp-servers  -e ./mempalace
```
`mempalace` pins an **older** commit than its upstream `HEAD`; `git submodule update` checks out the
**recorded** SHA (`9b35d9f7`), which we verified is fetchable. Do **not** run `git submodule update
--remote` (that would fast-forward to upstream HEAD and silently un-pin us).

**What each unlocks / impact if left empty:**

| Submodule | If initialized | If left EMPTY (impact) |
|---|---|---|
| `deeptempo-core` | LogLM + core detection/embedding lib available → Vigil's ML anomaly path works | `import deeptempo_core` paths raise at runtime; ML/LogLM detection unavailable. **Not on our critical loop path** (we detect via Wazuh/Suricata/Falco → findings, per `00` §2), so P0-tolerable but a real capability gap — recommend init. |
| `mcp-servers` | Vigil agents' MCP tool servers load | MCP-tool-backed agent actions silently missing; some `mcp-config.json` entries dead. Recommend init (we also *add* an MCP entry in §3). |
| `mempalace` | Agent long-term memory (cross-run recall) + brings `chromadb` transitively | Agents run stateless-per-session; `chromadb` may be absent. Non-blocking for P0; recommend init. |

**Recommendation: initialize all three.** They're free (public + reachable), and leaving them empty
seeds silent, hard-to-diagnose capability gaps in the blue engine.

### 2.2 Contingency A — **vendor / copy** (only if an upstream goes private or air-gapped)

If ESDS later air-gaps the build, or an upstream is pulled, convert submodule → vendored tree:

```bash
cd /home/abhinav/Desktop/Purple_Team/vigil
# one-time, on a connected mirror host: fetch the exact pinned tree
git clone https://github.com/DeepTempo/deeptempo-core.git /tmp/dtc && \
  git -C /tmp/dtc checkout 5c96abac
# de-submodule and vendor the content into vigil (documented, tracked change):
git submodule deinit -f deeptempo-core
git rm -f deeptempo-core                       # removes gitlink + .gitmodules entry
rm -rf .git/modules/deeptempo-core
rsync -a --exclude='.git' /tmp/dtc/ deeptempo-core/
git add deeptempo-core .gitmodules && git commit -m "vendor deeptempo-core @5c96abac (air-gap)"
```
This is an **engine edit**, so it must be captured as a Tier-B change (§3) and mirrored in
`manifest.toml` (drop the submodule, record the vendored SHA). Prefer an **internal ESDS mirror** of
the three upstreams over vendoring — it keeps `git submodule update` working unchanged and preserves
provenance. **Do not choose this contingency now** — upstreams are reachable.

### 2.3 Contingency B — **stub** (offline dev, capability deliberately deferred)

For a developer who can't reach GitHub and doesn't need the ML/memory features, drop a minimal
`pyproject.toml` shim into each empty dir so `filtered_reqs()` installs an importable no-op package.
This satisfies imports without the real logic. **Explicitly a dev-only crutch** — never ship a build
that stubs `deeptempo-core`, because detection results would be silently fake. Track stubs under
`overlay/vigil/_stubs/` and gate them behind `REDBLUE_STUB_SUBMODULES=1` in `setup.sh`.

### 2.4 Decepticon benchmark submodules

Leave `benchmark/xbow-validation-benchmarks` and `benchmark/MHBench` **uninitialized** for P0. Init
on demand only for benchmarking:
```bash
git -C Decepticon submodule update --init benchmark/MHBench benchmark/xbow-validation-benchmarks
```

---

## 3. Additive-patch strategy — modify engines WITHOUT forking

**Principle (from `00` §3):** *we do not edit the three reused repos in place except through a small,
tracked patch set.* We implement that with a **two-tier overlay**, both tiers living in the
superproject (`overlay/` + `patches/`) and applied idempotently by `setup.sh`.

### 3.1 Tier A — **overlay of NEW files** (preferred; zero merge risk)

Any capability we add as a **brand-new file** (a file that does not exist upstream) is stored under
`overlay/<engine>/<same-relative-path>` and **copied into** the engine tree at bootstrap. Because
the file is new, upstream `git pull` can never conflict with it.

```
overlay/vigil/services/decepticon_ingestion.py   →  vigil/services/decepticon_ingestion.py
overlay/vigil/mcp/redblue-decepticon-driver.json →  merged into vigil/mcp-config.json  (see 3.3)
```
Apply step (idempotent — copy is deterministic):
```bash
rsync -a overlay/vigil/  vigil/          # deploy tier-A files
# (symlink variant for hot-dev: ln -sfn ../overlay/vigil/services/decepticon_ingestion.py …)
```
**Use Tier A for:** the new `DecepticonIngestionService` connector (per `06`), any new coordinator-
facing helper modules, new MCP server entry files, new config *files*.

### 3.2 Tier B — **tracked patch files** for edits to EXISTING upstream files

When we must edit a file that upstream owns, we keep the edit as a `git`-format patch under
`patches/<engine>/NNNN-<slug>.patch`, generated from the pristine base and re-applied after checkout.

**Generate** (from a clean engine tree at the pinned SHA, make the edit, then):
```bash
cd vigil
git diff services/response_actions.py > ../patches/vigil/0001-isolate_host-real-action.patch
git checkout -- services/response_actions.py         # restore pristine; patch is the source of truth
```
**Apply** (idempotent — `git apply --3way` no-ops if already applied, 3-way-merges if the base moved):
```bash
for p in patches/vigil/*.patch; do
  git -C vigil apply --3way --whitespace=nowarn "$p" \
    || echo "DRIFT: $p failed — upstream file moved, regenerate this patch";
done
```
Each patch file carries a header comment: **rationale**, **target upstream file**, **linked plan doc**,
**related memory gotcha**. CI re-applies all patches against the manifest-pinned base to detect drift
early.

**Concrete Tier-B patch set for P0→P3** (all target *existing* Vigil files; rationale from
`redblue-integration-gotchas` + `vigil-governance-gates` memory):

| Patch | Target (existing file) | Why | Ref |
|---|---|---|---|
| `0001-isolate_host-real-action.patch` | Vigil response-action module | `isolate_host` is a **mock**; only Cloudflare truly executes — make it real (or fail-closed) | gotcha; `08` |
| `0002-tool-tier-verb-gate.patch` | Vigil tool-tier gate | Gate is **verb-blind to `launch`/`exploit`/`attack`** → red-driver tools default auto-exec | gotcha; `06` |
| `0003-daemon-workflow-step-map.patch` | `daemon/plan_generator.py` (`WORKFLOW_STEP_MAP` + `select_workflow`) | Register gated purple-team workflow step titles so the autonomous orchestrator can run DB workflows with `approval_required` phases | gotcha; `06` |

> Decepticon's safety gates (RoE enforce + HITL **off by default**) are toggled by **config/env**,
> not code — handled in `03`/`08` via env, **not** a patch here (keeps the patch set minimal).

### 3.3 Config additions (JSON/YAML) — merge, don't patch

`vigil/mcp-config.json` is a live config file; a line-diff patch is brittle. Instead store the new
entry as a fragment in `overlay/vigil/mcp/redblue-decepticon-driver.json` and **merge with `jq`** at
bootstrap (idempotent — keyed insert):
```bash
jq -s '.[0] * {mcpServers: (.[0].mcpServers + .[1].mcpServers)}' \
   vigil/mcp-config.json overlay/vigil/mcp/redblue-decepticon-driver.json \
   > vigil/mcp-config.json.tmp && mv vigil/mcp-config.json.tmp vigil/mcp-config.json
```

### 3.4 Why this beats a fork

A fork drifts the moment upstream tags a release; every bump becomes a merge. Overlay+patches invert
it: our surface is *explicit and auditable* (one dir of new files + a numbered patch series), engine
upgrades are mechanical, and a failed `git apply` is a **precise signal** ("upstream moved this exact
file") rather than a silent divergence.

---

## 4. Environments — four toolchains that must coexist

Each engine keeps its **native** env manager (do not homogenize — that would be an engine edit and
would fight each project's CI):

| Component | Interpreter | Env manager | Location | Runs in |
|---|---|---|---|---|
| **Decepticon** | Python **3.13** | **uv** workspace (`uv sync`) | `Decepticon/.venv` | host for dev (`make dev` = compose watch); Docker for the stack (PG/Neo4j/LiteLLM/LangGraph/sandbox) |
| **Vigil** | Python **3.10+** | **venv + pip** (`venv/`) | `vigil/venv` | host backend/daemon; Docker for PG/Redis/Bifrost/Ollama |
| **vigil-llm** | Python **3.9+** | **pip**, **isolated** | `vigil-llm/.venv` | **Docker** (own `Dockerfile`) — see §4.1 |
| **redblue-coordinator** | Python **3.13** | **uv** (conda env `redblue` also OK per `00` §6) | `redblue-coordinator/.venv` | host for dev; Docker for deploy (port **8900**, env prefix `REDBLUE_`) |

### 4.1 The hard constraint — vigil-llm MUST be isolated

`vigil-llm/requirements.txt` pins **`pydantic==1.10.7`, `openai==1.0.0`, `transformers==4.36.0`,
`numpy==1.25.2`, `chromadb==0.4.17`** — these **directly conflict** with Vigil (`pydantic>=2.0`,
`openai>=1.40`) and Decepticon (3.13-era stack). **Never install vigil-llm into Vigil's or the
coordinator's venv.** Consume it **only** as a **separate container / MCP tool** (per `00` §6 "vigil-llm
wrapped as MCP tool"). Its own `Dockerfile` makes this clean: build it, run it, call it over MCP/HTTP —
never share an interpreter.

### 4.2 What goes in Docker vs host

- **Docker (always):** all stateful/service infra — Postgres (×2, red `:5433`, blue `:5432`), Neo4j,
  Redis, LiteLLM `:4000`, Bifrost `:8080`, **Ollama `:11434` (single, shared)**, the sensor plane
  (Wazuh/Suricata/Falco), and **vigil-llm** (isolation). Wiring per `02`.
- **Host (dev) / Docker (deploy):** the Python app processes — Decepticon LangGraph, Vigil
  backend+daemon, coordinator. Dev uses each engine's hot-reload (`make dev`, `./start.sh`); deploy
  containerizes them behind `deploy/docker-compose.redblue.yml`.
- **Coexistence rule:** four separate virtualenvs, never cross-activated. `setup.sh` builds each in
  its own dir. The only shared runtime dependency is **one Ollama** (both LLM gateways point at it).

---

## 5. Build / bootstrap order + `setup.sh` outline

**Ordering constraints:** (a) submodules must init **before** Vigil's pip step (else editable installs
are skipped, §0.1); (b) each engine's env is built independently; (c) overlay/patches apply **after**
engine checkout but **before** first run; (d) everything **idempotent** (safe to re-run).

```
Prereqs check → clone/pin engines → init Vigil submodules → per-engine env build
   → apply overlay + patches → coordinator env → sanity smoke
```

### 5.1 `setup.sh` outline (idempotent, ordered)

```bash
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"

# ── 0. Prereqs (fail fast, actionable messages) ──────────────────────────────
require docker; require "docker compose"; require git; require jq
require uv        # Decepticon + coordinator (Python 3.13)
require python3.10 # Vigil floor
# Ollama presence checked here; models pulled in 03, not 01.

# ── 1. Reproduce engines at pinned SHAs (manifest.toml) — skip if present ─────
clone_or_update decepticon   # git clone/fetch + checkout <sha>  (idempotent)
clone_or_update vigil
clone_or_update vigil-llm

# ── 2. Vigil submodules FIRST (before pip) — §2.1 ────────────────────────────
git -C "$ROOT/vigil" submodule update --init --recursive
git -C "$ROOT/vigil" submodule status | grep -q '^-' && { echo "submodule init incomplete"; exit 1; }

# ── 3. Per-engine environments (native managers; parallelizable) ─────────────
( cd "$ROOT/Decepticon" && uv sync )                              # 3.13 workspace
( cd "$ROOT/vigil"      && python3.10 -m venv venv && . venv/bin/activate && \
                           pip install -U pip && pip install -r requirements.txt )  # editable submodules now resolve
( cd "$ROOT/vigil-llm"  && python3.9  -m venv .venv && . .venv/bin/activate && \
                           pip install -r requirements.txt )      # ISOLATED — never Vigil's venv (§4.1)

# ── 4. Apply additive layer (§3) — idempotent ────────────────────────────────
[[ "${1:-}" != "--no-overlay" ]] && {
  rsync -a "$ROOT/overlay/vigil/"      "$ROOT/vigil/"
  rsync -a "$ROOT/overlay/Decepticon/" "$ROOT/Decepticon/" 2>/dev/null || true
  for p in "$ROOT"/patches/vigil/*.patch; do
     git -C "$ROOT/vigil" apply --3way --whitespace=nowarn "$p" || echo "DRIFT: $p";
  done
  merge_mcp_config   # jq merge, §3.3
}

# ── 5. Coordinator env (Python 3.13, uv) ─────────────────────────────────────
( cd "$ROOT/redblue-coordinator" && uv sync )

# ── 6. Sanity smoke (non-fatal, informational) ───────────────────────────────
( cd "$ROOT/Decepticon" && uv run python -c "import decepticon" )
( cd "$ROOT/vigil" && . venv/bin/activate && python -c "import deeptempo_core, mcp_servers" )  # proves §2 worked
echo "setup complete — next: 02 (compose bring-up), 03 (Ollama models)"
```

**Notes:** Ollama **model pulls** and cloud-egress disablement are `03`, not here (keeps P0
bootstrap fast). Vigil's optional detection-rule download (**~4GB, `SETUP_DETECTION_REPOS=1`**) stays
**off** in `setup.sh` — opt-in later. `.env` files are created from `*.example` but **never
committed** (§6).

---

## 6. License & hygiene

### 6.1 Licenses (all clean — verified)

All three engines are **Apache-2.0**; the coordinator + all new code is **Apache-2.0** to match
(`00` §6). Add a top-level `Purple_Team/LICENSE` (Apache-2.0) for the superproject, and keep each
engine's own `LICENSE`/`THIRD_PARTY_LICENSES.md` untouched. Preserve upstream `NOTICE`/attribution.

### 6.2 GPL/AGPL arm's-length rule (non-negotiable — `00` §6, gotchas memory)

| Component | License | Rule |
|---|---|---|
| Wazuh | GPLv2 | **Deploy as a service, do not fork/redistribute.** Consume via API/agent only. |
| Suricata | GPLv2 | Same — deploy the container, read its EVE JSON; no linking into our code. |
| Shuffle | AGPLv3 | **Never build the coordinator on it.** Coordinator = **LangGraph** (`00` §6). |
| Infection Monkey / RedTeamAgent | GPLv3 / no OSI license | Out of scope; do not vendor. |

Keep all copyleft tools behind a **network boundary** (separate containers, data exchanged over
API/files) so nothing copyleft is statically or dynamically linked into our Apache-2.0 code.

### 6.3 `.gitignore` (superproject) — must include

```gitignore
# Engines are reproduced by setup.sh, never committed here:
/Decepticon/
/vigil/
/vigil-llm/
# Envs / build:
**/.venv/    **/venv/    **/__pycache__/    **/node_modules/    **/*.egg-info/
# Secrets / env:
**/.env      **/.env.*   !**/.env.example   !**/env.example
deploy/.env
# Runtime / evidence spill:
**/logs/     **/.dogfood/   **/workspace/   telemetry/**/data/
```
(Each engine already ignores its own `.env`, `.venv`, `venv/`, `node_modules`, secrets — verified in
`vigil/.gitignore` and `Decepticon/.gitignore`. We add the top-level engine-dir ignores.)

### 6.4 Secrets handling

- Secrets only in **`.env`** files, sourced at runtime; **`.env.example`** committed with dummy
  values. Coordinator uses **`REDBLUE_`** prefix (`00` §7).
- **`DEV_MODE=true` is Vigil's `env.example` default and bypasses ALL auth** (gotchas memory +
  `vigil/DEV_MODE.md`). `setup.sh` must **warn** if `DEV_MODE=true` while any red tooling or
  cross-tenant surface is wired; `08` flips it off. Never leave on in a shared/multi-tenant run.
- No credentials in `manifest.toml`, patches, or overlay. Pre-commit secret scan (each engine already
  ships pre-commit; add one for the superproject).

---

## 7. Checklist, acceptance criteria (P0 exit) & risks

### 7.1 P0 exit acceptance criteria (this doc's slice of `00` §8 P0)

- [ ] Superproject git repo initialized at `Purple_Team/`; `.gitignore` excludes the three engine trees; Apache-2.0 `LICENSE` present.
- [ ] `manifest.toml` pins all three engines to the verified SHAs (`e34afba0` / `311790e` / `f2b4c13`).
- [ ] `setup.sh` runs **clean and idempotently** twice in a row (second run is a no-op, exit 0).
- [ ] `git -C vigil submodule status` shows **no leading `-`** for all three (deeptempo-core / mcp-servers / mempalace initialized at pinned SHAs).
- [ ] `import deeptempo_core, mcp_servers` succeeds inside `vigil/venv` (proves §2 + editable installs resolved).
- [ ] `uv sync` green in `Decepticon/` and `redblue-coordinator/`; Vigil `venv` builds; **vigil-llm in its OWN env** (no dep collision with Vigil).
- [ ] `overlay/` files deployed and all `patches/vigil/*.patch` apply with **no DRIFT** against the pinned base.
- [ ] `mcp-config.json` jq-merge adds the decepticon-driver entry idempotently.
- [ ] Decepticon benchmark submodules remain **uninitialized** (not needed for P0).
- [ ] Each engine independently starts on Ollama (hand-off to `02`/`03` for the actual bring-up).

### 7.2 Risks & mitigations

| # | Risk | Likelihood | Mitigation |
|---|---|---|---|
| R1 | Empty Vigil submodules → silent capability gaps (LogLM/MCP/memory) because `filtered_reqs()` **skips** them without erroring (§0.1) | Med | `setup.sh` **hard-fails** if `submodule status` still shows `-`; smoke-test the imports; recommend init (§2.1). |
| R2 | Raw `pip install -r vigil/requirements.txt` (naive Dockerfile/dev) **hard-fails** on `-e ./deeptempo-core` when empty | Med | Always go through `setup.sh` (submodules first); document the trap; if building a container image, init submodules in an earlier layer. |
| R3 | `mempalace` pin (`9b35d9f7`) is **older than upstream HEAD** — a future upstream GC could drop it | Low | Fetch-by-SHA verified today; **mirror the three upstreams to an ESDS internal remote** to freeze provenance (also the §2.2 air-gap answer). |
| R4 | Tier-B patch drift on an engine bump (upstream moves a patched file) | Med | Numbered patches + `git apply --3way`; CI re-applies against the manifest base; a failed apply is a *precise* signal to regenerate one patch. |
| R5 | `DEV_MODE=true` (Vigil default) bypasses auth once red tooling/cross-tenant is wired | High if ignored | `setup.sh` warning + `08` enforces off; never ship with it on. |
| R6 | vigil-llm's pinned `pydantic==1.10.7` / `openai==1.0.0` leak into a shared venv | Med | Enforced isolation (§4.1): own venv + own container + MCP boundary; CI check that vigil-llm is never in Vigil's/coordinator's lockfile. |
| R7 | Four toolchains (uv 3.13, venv 3.10, pip 3.9, uv 3.13) drift/collide on host | Low | Separate venvs per dir, never cross-activated; deploy containerizes each; only Ollama is shared. |
| R8 | Copyleft (Wazuh/Suricata GPLv2, Shuffle AGPLv3) contaminating Apache-2.0 code | Low | Arm's-length via network boundary (§6.2); coordinator on LangGraph, not Shuffle. |

---

## 8. Exact command quick-reference

```bash
# ── verify current state (what §0 found) ──
git -C vigil submodule status                      # 3× leading '-' today = empty
git -C vigil remote -v ; git -C Decepticon remote -v ; git -C vigil-llm remote -v

# ── initialize Vigil submodules (primary path, §2.1) ──
git -C vigil submodule update --init --recursive   # add --depth 1 to save bandwidth
git -C vigil submodule status                      # want: no leading '-'

# ── build the four envs (§4/§5) ──
( cd Decepticon && uv sync )
( cd vigil && python3.10 -m venv venv && . venv/bin/activate && pip install -U pip && pip install -r requirements.txt )
( cd vigil-llm && python3.9 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt )   # ISOLATED
( cd redblue-coordinator && uv sync )

# ── apply additive layer (§3) ──
rsync -a overlay/vigil/ vigil/
for p in patches/vigil/*.patch; do git -C vigil apply --3way "$p"; done

# ── upgrade an engine later (§1.5) ──
git -C vigil fetch origin --tags && git -C vigil checkout <new-tag>
./setup.sh --apply-overlay --apply-patches         # re-apply layer; fix any DRIFT
```

---

## 9. Conflicts & reconciliation with `00_MASTER_PLAN.md`

No blocking conflicts. Two items flagged for the record (not silent divergences):

1. **`00` §3 parenthetical "git subtree/submodule — see 01" vs my Option A.** `00` explicitly
   delegated the mechanism to this doc. I **resolve it as neither subtree nor submodule** but
   **"keep-as-is siblings + thin superproject + manifest pin"** (§1.2). This is the "keep the 3
   engines as-is" option the task named as recommended, and it satisfies `00`'s §3 governing rule
   ("do not edit reused repos in place except via a tracked patch set"). Flagging because the literal
   parenthetical named only subtree/submodule. **Proposed `00` edit:** change the comment on the
   engine lines to `# reused engine (independent checkout, pinned via manifest.toml — see 01)`.

2. **Vigil's own three submodules add a nesting layer.** `00` treats "empty Vigil submodules" as an
   integration cost (§11 risk 3). Confirmed and quantified here (§0.1): they are the reason Option B
   (making the engines *our* submodules) is rejected — it would stack submodules-in-submodules. No
   change to `00` needed; this is corroborating detail.

Everything else — directory layout (§3), coordinator port `8900` / env prefix `REDBLUE_` (§4/§7),
Apache-2.0 + GPL/AGPL arm's-length (§6), phase P0 exit (§8) — is adopted verbatim.
