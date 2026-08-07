#!/usr/bin/env bash
# setup.sh — RedBlue AI superproject bootstrap (P0). Idempotent; safe to re-run.
# Reference: plans/01_REPO_STRUCTURE_AND_SUBMODULES.md
#
# Deviation from plan 01 §5.1 (recorded): the host has no python3.10/python3.9
# binaries (only python3.13), so Vigil (3.10) and vigil-llm (3.9) venvs are
# provisioned via `uv python install` + `uv venv --python <ver>` instead of a
# bare `pythonX.Y -m venv`. Same interpreter versions, uv-managed.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

log()  { printf '\033[1;36m[setup]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m  %s\n' "$*"; }
die()  { printf '\033[1;31m[err]\033[0m   %s\n' "$*" >&2; exit 1; }
require() { command -v "$1" >/dev/null 2>&1 || die "missing required tool: $1"; }

SKIP_ENVS="${SKIP_ENVS:-0}"   # SKIP_ENVS=1 → scaffold + submodules only (fast)

# ── 0. Prereqs ───────────────────────────────────────────────────────────────
log "checking prereqs"
require docker; require git; require jq; require uv
docker compose version >/dev/null 2>&1 || die "docker compose v2.24+ required"
command -v ollama >/dev/null 2>&1 || warn "ollama not on host (needed for P1/P3, not P0)"

# ── 1. Reproduce engines at pinned SHAs (manifest.toml) — verify/clone ────────
eval "$(python3 - <<'PY'
import tomllib, shlex
for k, v in tomllib.load(open("manifest.toml","rb"))["engines"].items():
    var = k.replace("-","_").upper()
    print(f'{var}_URL={shlex.quote(v["url"])}; {var}_SHA={shlex.quote(v["sha"])}')
PY
)"
pin() { # $1=dir  $2=url  $3=sha
  if [ ! -d "$1/.git" ]; then log "cloning $1"; git clone "$2" "$1"; git -C "$1" checkout "$3"; fi
  local cur; cur="$(git -C "$1" rev-parse HEAD)"
  if [ "$cur" = "$3" ]; then log "$1 @ pinned ${3:0:12}"
  else warn "$1 @ ${cur:0:12} but manifest pins ${3:0:12} (not auto-checking-out; verify before bump)"; fi
}
pin Decepticon "$DECEPTICON_URL" "$DECEPTICON_SHA"
pin vigil       "$VIGIL_URL"       "$VIGIL_SHA"
pin vigil-llm   "$VIGIL_LLM_URL"   "$VIGIL_LLM_SHA"

# ── 2. Vigil submodules FIRST (before Vigil's pip step) — plan 01 §2 ──────────
log "initializing Vigil submodules (deeptempo-core, mcp-servers, mempalace)"
git -C vigil submodule update --init --recursive
git -C vigil submodule status | grep -q '^-' && die "vigil submodule init incomplete (leading '-')"
log "vigil submodules initialized"

[ "$SKIP_ENVS" = "1" ] && { log "SKIP_ENVS=1 → done (scaffold + submodules)"; exit 0; }

# ── 3. Per-engine environments (uv provisions the missing interpreters) ───────
uv python install 3.13 3.10 3.9 >/dev/null 2>&1 || true

log "Decepticon env (uv sync, py3.13 workspace)"
( cd Decepticon && uv sync )

log "Vigil env (venv py3.10 via uv; editable submodules resolve now)"
( cd vigil && uv venv --python 3.10 venv \
    && uv pip install --python venv/bin/python -U pip \
    && uv pip install --python venv/bin/python -r requirements.txt )

log "vigil-llm env (ISOLATED venv py3.9 — NEVER Vigil's venv; plan 01 §4.1)"
( cd vigil-llm && uv venv --python 3.9 .venv \
    && uv pip install --python .venv/bin/python -r requirements.txt ) \
  || warn "vigil-llm deps failed (old pins: pydantic==1.10.7, numpy==1.25.2, ...) — NON-BLOCKING for P0; consumed as a container/MCP per plans 04/08"

# ── 4. Additive overlay + patches (empty in P0; no-op) — plan 01 §3 ───────────
if compgen -G "overlay/*/" >/dev/null 2>&1; then
  log "applying overlay/"; for e in overlay/*/; do en="$(basename "$e")"; [ -d "$en" ] && rsync -a "$e" "$en/"; done
fi
if compgen -G "patches/*/*.patch" >/dev/null 2>&1; then
  log "applying patches/ (idempotent — reverse-check skips already-applied)"
  for p in patches/*/*.patch; do
    en="$(basename "$(dirname "$p")")"
    if git -C "$en" apply --reverse --check "$ROOT/$p" >/dev/null 2>&1; then
       log "  already applied: $(basename "$p")"
    elif git -C "$en" apply --3way --whitespace=nowarn "$ROOT/$p"; then
       log "  applied: $(basename "$p")"
    else
       warn "DRIFT: $p (upstream file moved — regenerate this patch)"
    fi
  done
fi

# ── 5. Coordinator env (py3.13, uv) ──────────────────────────────────────────
log "redblue-coordinator env (uv sync, py3.13)"
( cd redblue-coordinator && uv sync )

# ── 6. Sanity smoke (non-fatal) ──────────────────────────────────────────────
log "smoke: import checks"
( cd Decepticon && uv run python -c "import decepticon; print(' decepticon import OK')" ) || warn "decepticon import failed"
# NB: deeptempo-mcp-servers exposes its top-level module as `servers` (not `mcp_servers`).
( cd vigil && ./venv/bin/python -c "import deeptempo_core, servers, mempalace; print(' vigil submodule imports OK')" ) || warn "vigil submodule imports failed (init step 2?)"
( cd redblue-coordinator && uv run python -c "import redblue; print(' redblue-coordinator import OK')" ) || warn "coordinator import failed"

log "P0 setup complete → next: docs 02 (compose bring-up), 03 (Ollama models + egress proof)"
