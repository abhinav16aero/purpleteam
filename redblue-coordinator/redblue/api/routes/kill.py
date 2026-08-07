"""Kill switch endpoints (plan 08 §5) — un-gated; stopping never needs approval."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter()


class KillRequest(BaseModel):
    by: str
    reason: str


def _active_engagements(store, tenant_id: str | None) -> list[str]:
    rows = store.list_engagements(tenant_id=tenant_id, status="running")
    return [r["engagement_id"] for r in rows]


@router.post("/api/kill")
async def global_kill(req: KillRequest, request: Request) -> dict:
    st = request.app.state
    if st.killswitch is None:
        raise HTTPException(503, "kill switch not configured")
    engs = _active_engagements(st.store, None)
    return st.killswitch.kill(scope="global", by=req.by, reason=req.reason, engagement_ids=engs)


@router.post("/api/tenants/{tenant_id}/kill")
async def tenant_kill(tenant_id: str, req: KillRequest, request: Request) -> dict:
    st = request.app.state
    if st.killswitch is None:
        raise HTTPException(503, "kill switch not configured")
    engs = _active_engagements(st.store, tenant_id)
    return st.killswitch.kill(scope="tenant", tenant_id=tenant_id, by=req.by,
                              reason=req.reason, engagement_ids=engs)
