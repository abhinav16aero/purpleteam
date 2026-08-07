# deploy/sovereignty/ — local-LLM + zero-egress (P1 / plan 03)

Sovereignty is **defense-in-depth** — five independent guarantees, so no single misconfiguration
can leak to a foreign API:

| # | Guarantee | Where |
|---|---|---|
| 1 | **No cloud credentials** — `ANTHROPIC_API_KEY`/`OPENAI_API_KEY`/… left unset | `Decepticon/.env`, `deploy/env/*.env` |
| 2 | **Everything points local** — Decepticon `OLLAMA_MODEL`+`OLLAMA_API_BASE`+`ollama_local`; Vigil `OLLAMA_URL`+`DEFAULT_MODEL=ollama/...` | `Decepticon/.env`, `deploy/overrides/vigil.redblue.yml` |
| 3 | **Bifrost cloud stripped** — Vigil's Bifrost seed is ollama-only, so it *cannot* route to Anthropic/OpenAI | `overlay/vigil/docker/bifrost/config.sovereign.json` |
| 4 | **Telemetry off** — Decepticon `DECEPTICON_TELEMETRY=off`+`DO_NOT_TRACK=1` (closes PostHog egress) | `Decepticon/.env` |
| 5 | **Network egress deny** — host iptables DROP all container→internet (except intra-docker + Ollama) | `egress-lockdown.sh` |

Embeddings are local too (Decepticon `ollama/nomic-embed-text`) — closing the embedding egress vector.

## Model tiers (this host: **no GPU, 14 GB RAM**)
Plan 03's 32B GPU tiers don't fit. Small-model sovereign set (already pulled):
- **Chat/agentic:** `qwen2.5-coder:7b` (all Decepticon tiers collapse to it; Vigil `DEFAULT_MODEL`)
- **Alt:** `qwen3:8b`
- **Embeddings:** `nomic-embed-text` (local, 768-dim)

A GPU host (≥24 GB) can lift the chat model to `qwen2.5-coder:32b` — change `OLLAMA_MODEL` / `DEFAULT_MODEL` only.

## Bring-up order (critical)
```
1. pull images + models     # network needed
2. make up                  # stacks on local Ollama
3. sudo egress-lockdown.sh apply   # LAST — a lockdown before step 1/2 breaks pulls
4. ./verify-egress.sh       # P1 exit gate: ollama reachable + foreign APIs blocked
```
See `../../docs/adr/0002-sovereignty-local-llm.md`.
