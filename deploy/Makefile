# deploy/Makefile — the real orchestrator of the multi-project stack.
# Plan: plans/02_INFRA_COMPOSE_AND_PORTS.md §5.  Run from deploy/.
SHELL := /bin/bash

DEC := docker compose -p decepticon --env-file env/decepticon.env \
         -f ../Decepticon/docker-compose.yml -f overrides/decepticon.redblue.yml
VIG := docker compose -p vigil --env-file env/vigil.env \
         -f ../vigil/docker/docker-compose.yml -f overrides/vigil.redblue.yml
CO  := docker compose -p coordinator -f docker-compose.redblue.yml
TEL := docker compose -p telemetry -f ../telemetry/docker-compose.telemetry.yml

PROFILES ?=
DEC_PROF := $(foreach p,$(PROFILES),--profile $(p))
VIG_PROF := $(foreach p,$(PROFILES),--profile $(p))
TEL_PROF := $(foreach p,$(PROFILES),--profile $(p))   # e.g. PROFILES=target brings up the DVWA victim
# red+blue local model; override on the CLI: make ollama OLLAMA_MODEL=<tag>. (No inline comment on
# the next line — Make would fold the trailing spaces into the value and break `ollama pull`.)
OLLAMA_MODEL ?= qwen2.5-coder:7b
export OLLAMA_MODEL                                   # so `docker compose` sees it for ${OLLAMA_MODEL} interpolation

.PHONY: net dec-env ollama certs red-only blue-only telemetry lab up demo down logs ps config health clean help

help:            ## list targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | sed 's/:.*##/ →/' | sort

net:             ## create the shared bus + the isolated target range once (idempotent)
	@docker network inspect redblue-shared >/dev/null 2>&1 || docker network create redblue-shared
	@docker network inspect range-net      >/dev/null 2>&1 || docker network create --subnet 10.20.0.0/24 range-net

dec-env:         ## write ../Decepticon/.env with the SOVEREIGN Ollama keys if absent (doc 03)
	@[ -f ../Decepticon/.env ] || { \
	  echo "[deploy] writing sovereign ../Decepticon/.env (Ollama-only; no cloud keys)"; \
	  { echo '# RedBlue sovereign defaults (doc 03) — local Ollama only, zero cloud egress.'; \
	    echo 'OLLAMA_API_BASE=http://ollama:11434'; \
	    echo 'OLLAMA_MODEL=$(OLLAMA_MODEL)'; \
	    echo 'DECEPTICON_AUTH_PRIORITY=ollama_local'; \
	    echo '# CPU inference is slow — give each agent turn generous timeouts or the run APITimeouts.'; \
	    echo 'DECEPTICON_LLM__TIMEOUT=900'; \
	    echo 'DECEPTICON_LLM_TIMEOUT_SECONDS=900'; \
	    echo '# Leave ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY UNSET to stay sovereign.'; \
	  } > ../Decepticon/.env; }

ollama: net      ## P1: bring up shared Ollama AND pull the model (red/blue LLM calls 404 without it)
	$(CO) up -d --wait ollama
	@echo "[deploy] pulling $(OLLAMA_MODEL) into redblue-ollama (idempotent — skips if present)…"
	@docker exec redblue-ollama ollama pull $(OLLAMA_MODEL)

red-only: net dec-env  ## P0/P1: Decepticon standalone (core profile)
	$(DEC) $(DEC_PROF) up -d --wait

blue-only: net   ## P0/P1: Vigil standalone (core profile)
	$(VIG) $(VIG_PROF) up -d --wait

certs:           ## P2: one-time Wazuh TLS cert generation → telemetry/wazuh/certs/ (auto-run by telemetry)
	@[ -f ../telemetry/wazuh/certs/root-ca.pem ] || \
	  docker compose -f ../telemetry/generate-indexer-certs.yml run --rm generator
	@echo "[deploy] Wazuh certs present in telemetry/wazuh/certs/"

telemetry: net certs  ## P2: sensor plane (Wazuh/Suricata/Falco). HEAVY — needs sysctl vm.max_map_count=262144. Add PROFILES=target for DVWA
	$(TEL) $(TEL_PROF) up -d --wait

lab: red-only blue-only telemetry  ## P2: engines + sensors (the purple loop minus coordinator)
	@echo "[deploy] lab up: red + blue + telemetry — attack the range, watch Vigil findings"

up: net dec-env  ## P4: full loop (coordinator image must be built; telemetry is P2)
	$(CO) up -d --wait
	$(DEC) $(DEC_PROF) up -d --wait
	$(VIG) $(VIG_PROF) up -d --wait
	@$(MAKE) health

demo: net dec-env  ## ONE-SHOT full demo: (re)build+start coordinator/red/blue, then seed & verify EVERY console tab
	@echo "[demo] 1/4  build + start coordinator (simulate · graph · dashboard) + ollama"
	$(CO) up -d --build --wait
	@echo "[demo] 2/4  start Decepticon (Neo4j KG)"
	$(DEC) $(DEC_PROF) up -d --wait
	@echo "[demo] 3/4  start Vigil (blue ingest)"
	$(VIG) $(VIG_PROF) up -d --wait
	@$(MAKE) --no-print-directory health
	@echo "[demo] 4/4  seed + verify the end-to-end route"
	@bash demo-seed.sh
	@echo ""
	@echo "  > Console:  http://localhost:8900/     (from your laptop:  ssh -L 8900:localhost:8900 <vm-host>)"
	@echo "  > Optional heavy add — the real Wazuh sensor plane + DVWA:  make telemetry PROFILES=target"

down:            ## stop everything, keep volumes
	-$(CO) down
	-$(VIG) down
	-$(DEC) down

ps:              ## per-project status
	-$(DEC) ps
	-$(VIG) ps
	-$(CO)  ps

config: dec-env  ## ACCEPTANCE GATE: every buildable project renders
	@$(DEC) config -q && echo " decepticon ✓"
	@$(VIG) config -q && echo " vigil ✓"
	@$(TEL) config -q && echo " telemetry ✓"
	@$(CO)  config -q && echo " coordinator ✓"

health:          ## probe cross-stack endpoints + the sandbox-isolation invariant
	@docker ps --format '{{.Names}}\t{{.Status}}' | grep -E 'decepticon|deeptempo|redblue' || true
	@curl -sf http://localhost:2024/ok       >/dev/null && echo " langgraph OK"   || echo " langgraph  —"
	@curl -sf http://localhost:6987/health   >/dev/null && echo " vigil OK"       || echo " vigil      —"
	@curl -sf http://localhost:11434/api/tags>/dev/null && echo " ollama OK"      || echo " ollama     —"
	@curl -sf http://localhost:8900/api/health >/dev/null && echo " coordinator OK" || echo " coordinator —"
	@docker network inspect redblue-shared -f '{{range .Containers}}{{.Name}} {{end}}' 2>/dev/null \
	  | grep -Eq 'sandbox|c2-sliver' && echo " !! ISOLATION BREACH: sandbox on shared net" || echo " isolation OK"

clean:           ## down + prune SAFE volumes (keeps ollama_models / postgres / neo4j / coordinator_data)
	@$(MAKE) down
	@echo "safe clean: model, DB, KG, and evidence volumes are preserved (use 'docker volume prune' manually for a full wipe)"

smoke:           ## the "does the loop close?" gate (plan 09 §3.2) — live if coordinator up, else logic-smoke
	@bash smoke.sh

eval:            ## run the red-team-of-the-AI eval (plan 08 §8) — the demo proof asset
	@curl -sf http://localhost:8900/api/eval/injection | (jq . 2>/dev/null || cat) \
	  || ( cd ../redblue-coordinator && uv run python -c "from redblue.eval import EvalHarness; from redblue.governance import InjectionShield, PolicyEngine, AssetMap; from redblue.config.tenants import TenantPolicyRegistry; import json; print(json.dumps(EvalHarness(shield=InjectionShield(), policy_engine=PolicyEngine(AssetMap(), TenantPolicyRegistry())).run().model_dump(), indent=2))" )

posture-dashboard: ## import the Grafana RedBlue posture dashboard (needs Grafana up on :3001)
	@echo "Import deploy/observability/redblue_posture.json into Grafana (:3001), datasource = Prometheus (:9095)."
