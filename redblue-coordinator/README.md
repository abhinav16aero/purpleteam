# redblue-coordinator

The LangGraph coordinator that closes the RedBlue AI purple-team loop. Design: `plans/07_COORDINATOR_LANGGRAPH.md`.

- **API** FastAPI on `:8900` · **metrics** `:8902` · env prefix `REDBLUE_`
- **Store** SQLite (MVP) → Postgres 16 + pgvector
- Drives Decepticon over LangGraph `:2024`, Vigil over REST `:6987`, reads the shared Neo4j attack graph `:7687`

P0 = scaffold only (this package + `uv sync`). The loop, connectors, scoring, governance, and evidence
land in P4–P8. See `plans/00_MASTER_PLAN.md §8` for the phase spine.

```bash
uv sync
uv run python -c "import redblue; print(redblue.__version__)"
```
