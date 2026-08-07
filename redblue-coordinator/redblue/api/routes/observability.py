"""Observability endpoints (plan 09 §1.4/§2): Prometheus /metrics, posture aggregate, SSE timeline."""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

from ...obs import render
from ...obs.posture import build_posture

router = APIRouter()


@router.get("/metrics")
async def metrics() -> Response:
    payload, content_type = render()
    return Response(content=payload, media_type=content_type)


@router.get("/api/posture")
async def posture(request: Request, tenant_id: str | None = None) -> dict:
    scorecards = request.app.state.store.list_scorecards(tenant_id=tenant_id)
    return build_posture(scorecards)


@router.get("/api/engagements/{engagement_id}/events")
async def engagement_events(engagement_id: str, request: Request) -> StreamingResponse:
    """SSE timeline of the engagement's evidence records (plan 09 §1.6). The console consumes this
    via `streamFetch`. MVP replays the persisted chain as `data:` events (the loop runs inline; a
    truly-live push is the background-execution slice). One SSE endpoint, no WebSocket."""
    st = request.app.state
    if st.store.get_engagement(engagement_id) is None:
        raise HTTPException(404, "engagement not found")
    records = st.store.get_evidence(engagement_id)

    def gen():
        for r in records:
            yield f"event: {r['record_type']}\ndata: {json.dumps(r)}\n\n"
        yield "event: end\ndata: {}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
