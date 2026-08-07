"""Eval endpoint (plan 08 §8 / plan 09 §3.4) — run the red-team-of-the-AI corpus, return the report.

Both a CI quality gate and the demo's proof asset ("injection-catch X%, agent-hijack 0, grounded").
"""
from __future__ import annotations

from fastapi import APIRouter, Request

from ...eval import EvalHarness

router = APIRouter()


@router.get("/api/eval/injection")
async def run_injection_eval(request: Request) -> dict:
    st = request.app.state
    harness = EvalHarness(shield=st.deps.shield, policy_engine=st.deps.policy_engine)
    return harness.run().model_dump()
