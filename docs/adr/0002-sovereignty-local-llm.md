# ADR-0002 — Sovereignty: local Ollama, zero foreign-API egress

- **Status:** Accepted (P1, 2026-08-05)
- **Plan ref:** `plans/03_SOVEREIGNTY_LOCAL_LLM.md`, `plans/00_MASTER_PLAN.md §5/§10`

## Context
ESDS Sovereign Cloud requires DPDP/CERT-In compliance: India-resident inference, **no foreign-API
egress**. Both engines default to cloud LLMs and carry *silent* cloud/embedding fallbacks
(Decepticon skillogy→OpenAI embeddings + PostHog telemetry; Vigil `DEFAULT_MODEL=claude-sonnet-4-6`,
Bifrost seeded with Anthropic/OpenAI). Any one of these leaks unless explicitly closed.

## Decision — defense-in-depth (5 independent guarantees)
1. **No cloud credentials** anywhere (factory then selects `ollama_local`; Bifrost cloud keys empty).
2. **Point everything local:** Decepticon `OLLAMA_MODEL`/`OLLAMA_API_BASE`/`DECEPTICON_AUTH_PRIORITY=ollama_local` + `DECEPTICON_SKILLOGY_EMBED_MODEL=ollama/nomic-embed-text`; Vigil `OLLAMA_URL=http://ollama:11434` + `DEFAULT_MODEL=ollama/qwen2.5-coder:7b`.
3. **Strip cloud from Bifrost** — ollama-only seed (`overlay/vigil/docker/bifrost/config.sovereign.json`) so Bifrost *physically cannot* route to a foreign API.
4. **Telemetry off** — `DECEPTICON_TELEMETRY=off` + `DO_NOT_TRACK=1`.
5. **Network egress deny** — `deploy/sovereignty/egress-lockdown.sh` DROPs all container→internet at the host `DOCKER-USER` chain (IMDS `169.254.0.0/16` explicitly dropped), applied *after* provisioning.

One containerized Ollama (`:11434` on `redblue-shared`) serves both LiteLLM (red) and Bifrost (blue),
so the whole LLM path stays on the Docker bridge — no external egress is ever needed.

## Deviation (hardware reality — recorded)
The build host has **no GPU and 14 GB RAM**. Plan 03's 32B tiers are infeasible; the sovereign set is
small models (`qwen2.5-coder:7b` for chat/agentic, `qwen3:8b` alt, `nomic-embed-text` embeddings) — all
already pulled. Decepticon's HIGH/MID/LOW tiers collapse to the one 7B model (its Ollama path uses a
single `OLLAMA_MODEL`). A GPU host lifts `OLLAMA_MODEL`/`DEFAULT_MODEL` to a 32B model with no other change.

## Status / verification
- ✅ **Local inference proven** on this box: `qwen2.5-coder:7b` (CPU) returned a correct completion.
- ✅ Config artifacts written (env, sovereign Bifrost seed, override, egress scripts).
- ⏳ **Full two-engine live egress proof deferred** — running *both* Docker stacks + Ollama exceeds
  14 GB RAM. The P1 exit gate (`verify-egress.sh`: Ollama reachable + foreign APIs blocked under load)
  runs on a provisioned sovereign host (plan 03 §7 sizing: ≥32 GB, GPU recommended). The *config* is
  complete and correct; only the live full-stack run awaits adequate hardware.

## Consequences
- Quality trade-off: 7B local ≪ frontier cloud; extended-thinking (Vigil's 9 thinking-agents) is
  dropped on the Ollama path — accepted for sovereignty (eval harness in plan 09 quantifies the gap).
- Turning sovereignty *off* for a dev spike = add a provider key + revert the Bifrost seed; the
  egress-deny script is the hard backstop that makes "off" a deliberate, auditable act.
