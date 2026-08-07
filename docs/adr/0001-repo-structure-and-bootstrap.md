# ADR-0001 — Repo structure, engine pinning & bootstrap

- **Status:** Accepted (P0, 2026-08-05)
- **Plan ref:** `plans/01_REPO_STRUCTURE_AND_SUBMODULES.md`, `plans/00_MASTER_PLAN.md §3/§6`

## Context
RedBlue AI integrates three upstream open-source engines — Decepticon (red), Vigil (blue),
vigil-llm (injection scanner) — and adds new code (coordinator, telemetry, deploy). The engines are
commodities we must keep **cheaply re-pullable** from upstream; our value is the glue + governance +
sovereignty, not the engines. We must not fork them into a merge war.

## Decision
1. **Option A — sibling checkouts + thin superproject + manifest pin.** `Purple_Team/` is a new git
   repo that tracks *only* the authored dirs (`redblue-coordinator/`, `telemetry/`, `deploy/`,
   `overlay/`, `patches/`, `plans/`, `docs/`, `manifest.toml`, `setup.sh`, `LICENSE`, `README.md`) and
   **gitignores** the three engine trees. Engines are **reproduced** (cloned at pinned SHAs from
   `manifest.toml`), never vendored. Rejected: engines-as-submodules (Vigil already nests 3 of its own →
   submodules-in-submodules), git subtree (history bloat), monorepo (kills upstream mergeability).
2. **Additive-only engine changes via a two-tier overlay.** New files → `overlay/<engine>/…` (copied in;
   never conflicts). Edits to existing upstream files → `patches/<engine>/NNNN-*.patch` (re-applied with
   `git apply --3way`; a failed apply is a precise "upstream moved this file" signal). Config files (e.g.
   `mcp-config.json`) → `jq` merge, not line-diff. Both tiers are empty in P0.
3. **`manifest.toml` pins** each engine to a tested-good SHA. Verified on disk: Decepticon
   `e34afba0` (v1.1.40), vigil `311790e2` (v0.4.0), vigil-llm `f2b4c134` (v0.10.3-alpha). Bump only after
   re-testing the overlay/patch set.
4. **Vigil submodules initialized** (`deeptempo-core`, `mcp-servers`, `mempalace`) — all three upstreams
   are public + reachable; leaving them empty seeds silent capability gaps (LogLM/MCP/memory). Decepticon
   benchmark submodules stay uninitialized (not on the runtime path).
5. **Four coexisting toolchains, never cross-activated:** Decepticon (uv, 3.13 workspace), Vigil (venv,
   3.10), vigil-llm (**isolated** venv, 3.9 — its `pydantic==1.10.7`/`openai==1.0.0` pins conflict with
   Vigil, so it is consumed only as a container/MCP), coordinator (uv, 3.13).

## Deviation (recorded)
The build host has **no `python3.10`/`python3.9`** binaries (only `python3.13`). Plan `01 §5.1`'s
`pythonX.Y -m venv` is therefore replaced by **`uv python install` + `uv venv --python <ver>`**, which
provisions the exact required interpreters. Same versions; uv-managed. This is captured in `setup.sh`'s
header and is the only deviation from plan `01` in P0.

## Consequences
- Upgrading an engine is a ritual (bump SHA → re-apply overlay/patches → re-test), not a merge.
- 100% of authored code is isolated from the engine trees; upstream `git pull` stays clean.
- `setup.sh` is the single idempotent bootstrap; `SKIP_ENVS=1` gives a fast scaffold-only path.
- vigil-llm's env may fail to build against 3.9 pins on some hosts — **non-blocking** by design (it is a
  container/MCP dependency, not on the coordinator's import path).
- The GPL/AGPL sensor components (Wazuh/Suricata, added P2) stay arm's-length (deployed images only).
