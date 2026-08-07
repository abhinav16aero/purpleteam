"""FastAPI app factory (plan 07 §6.1). Fronts the LangGraph loop on :8900.

`create_app` is dependency-injectable: pass `deps`/`store` for tests (fakes + in-memory SQLite);
default builds the live connector deps + the configured store. State hangs off `app.state`.
"""
from __future__ import annotations

from fastapi import FastAPI

from ..config.settings import Settings, get_settings
from ..continuous import ContinuousController
from ..governance import KillSwitch
from ..loop import Deps, build_graph, make_checkpointer
from ..store import CoordinatorStore
from .routes import drift, engagements, eval, health, kill, observability


def create_app(
    *, deps: Deps | None = None, store: CoordinatorStore | None = None,
    checkpointer_kind: str | None = None, settings: Settings | None = None,
) -> FastAPI:
    s = settings or get_settings()
    if deps is None:
        from ..loop.live import build_live_deps
        deps = build_live_deps(s)
    # ensure a kill switch bound to the same evidence store (plan 08 §5); set BEFORE build_graph so
    # plan_engagement sees it.
    if deps.killswitch is None:
        deps.killswitch = KillSwitch(evidence=deps.evidence)
    store = store or CoordinatorStore(s.db_url)
    graph = build_graph(deps, checkpointer=make_checkpointer(
        checkpointer_kind or s.checkpointer, s.checkpointer_path))

    app = FastAPI(title="RedBlue AI Coordinator", version="0.0.1")
    app.state.deps = deps
    app.state.store = store
    app.state.graph = graph
    app.state.killswitch = deps.killswitch
    app.state.continuous = ContinuousController(
        evidence=deps.evidence, debounce_s=s.drift_debounce_s,
        max_replays_per_hour=s.max_replays_per_hour)
    app.include_router(health.router)
    app.include_router(engagements.router)
    app.include_router(kill.router)
    app.include_router(drift.router)
    app.include_router(eval.router)
    app.include_router(observability.router)
    return app
