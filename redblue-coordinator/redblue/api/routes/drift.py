"""Drift (CART continuous-mode) endpoints (plan 07 §5).

`POST /api/engagements/{id}/drift` feeds an infra ChangeEvent → debounce/budget → ReplayPlan. The
first replay of an engagement is dry-run (needs approval); `.../drift/{plan_id}/approve` runs it live.
A live replay re-invokes the loop for a new scorecard version (thread_id per version).
"""
from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Request

from ...continuous import ChangeEvent, ReplayPlan, tenant_of

router = APIRouter()


def _make_run(app, engagement_id: str):
    """Return a run(plan) that re-invokes the coordinator loop for the next scorecard version."""
    async def run(plan: ReplayPlan) -> dict:
        st = app.state
        eng = st.store.get_engagement(engagement_id) or {}
        latest = st.store.get_scorecard(engagement_id)
        version = (latest["version"] + 1) if latest else 1
        objectives = plan.selected_objectives
        loop_input = {
            "engagement_id": engagement_id,
            "tenant_id": tenant_of(engagement_id),        # robust hyphen-safe parse
            "mode": "continuous", "version": version,
            "red_objectives": objectives,
            # trigger_red reads `instruction`, so carry the delta objectives there too
            "instruction": "CART drift replay: " + "; ".join(objectives),
            "scope": eng.get("scope") or {},              # reuse the engagement's original scope
        }
        final = await st.graph.ainvoke(
            loop_input, {"configurable": {"thread_id": f"{engagement_id}:{plan.plan_id}"}})
        card = final.get("scorecard")
        if card:
            st.store.upsert_scorecard(card, ts=time.time())
        st.store.save_evidence(st.deps.evidence.chain(engagement_id))
        return {"version": version, "scorecard_id": (card or {}).get("scorecard_id"),
                "detection_rate": (card or {}).get("detection_rate")}
    return run


@router.post("/api/engagements/{engagement_id}/drift")
async def post_drift(engagement_id: str, ce: ChangeEvent, request: Request) -> dict:
    st = request.app.state
    if getattr(st, "continuous", None) is None:
        raise HTTPException(503, "continuous controller not configured")
    if st.store.get_engagement(engagement_id) is None:
        raise HTTPException(404, "engagement not found")
    return await st.continuous.on_drift(engagement_id, ce, _make_run(request.app, engagement_id))


@router.post("/api/engagements/{engagement_id}/drift/{plan_id}/approve")
async def approve_replay(engagement_id: str, plan_id: str, request: Request) -> dict:
    st = request.app.state
    if getattr(st, "continuous", None) is None:
        raise HTTPException(503, "continuous controller not configured")
    res = await st.continuous.approve(plan_id, _make_run(request.app, engagement_id), now=time.time())
    if res.get("status") == "not_found":
        raise HTTPException(404, "replay plan not found or already consumed")
    return res
