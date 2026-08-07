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

.PHONY: net dec-env ollama red-only blue-only telemetry lab up down logs ps config health clean help

help:            ## list targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | sed 's/:.*##/ →/' | sort

net:             ## create the shared bus + the isolated target range once (idempotent)
	@docker network inspect redblue-shared >/dev/null 2>&1 || docker network create redblue-shared
	@docker network inspect range-net      >/dev/null 2>&1 || docker network create range-net

dec-env:         ## Decepticon services use `env_file: .env` — ensure it exists so compose renders
	@[ -f ../Decepticon/.env ] || { \
	  echo "[deploy] creating minimal ../Decepticon/.env stub (replaced by 'decepticon onboard' / doc 03)"; \
	  printf '# minimal stub for compose render; real LLM auth added in doc 03 / by decepticon onboard\n' > ../Decepticon/.env; }

ollama: net      ## P1: bring up the shared Ollama
	$(CO) up -d ollama

red-only: net dec-env  ## P0/P1: Decepticon standalone (core profile)
	$(DEC) $(DEC_PROF) up -d --wait

blue-only: net   ## P0/P1: Vigil standalone (core profile)
	$(VIG) $(VIG_PROF) up -d --wait

telemetry: net   ## P2: sensor plane (Wazuh/Suricata/Falco). HEAVY — needs sysctl vm.max_map_count=262144. Add PROFILES=target for DVWA
	$(TEL) $(TEL_PROF) up -d --wait

lab: red-only blue-only telemetry  ## P2: engines + sensors (the purple loop minus coordinator)
	@echo "[deploy] lab up: red + blue + telemetry — attack the range, watch Vigil findings"

up: net dec-env  ## P4: full loop (coordinator image must be built; telemetry is P2)
	$(CO) up -d --wait
	$(DEC) $(DEC_PROF) up -d --wait
	$(VIG) $(VIG_PROF) up -d --wait
	@$(MAKE) health

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
