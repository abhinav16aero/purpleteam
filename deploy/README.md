# deploy/ — unified bring-up (multi-project compose)

Design: `plans/02_INFRA_COMPOSE_AND_PORTS.md`. Each stack runs as its **own** Compose project joined by
one **external** network `redblue-shared` (a single merged file is impossible — both engines define a
service named `postgres`).

- `docker-compose.redblue.yml` — coordinator + shared `ollama` + declares `redblue-shared`
- `overrides/{decepticon,vigil}.redblue.yml` — attach engine services to the bus; remap collided ports
- `env/{decepticon,vigil,shared}.env` — host-port remaps + `OLLAMA_URL` + `REDBLUE_*`
- `Makefile` — `make net|ollama|red-only|blue-only|lab|up|down|health|clean` (the real orchestrator)

Port map is authoritative in `plans/00_MASTER_PLAN.md §4`. Built in P0→P4. Requires Compose v2.24+.
