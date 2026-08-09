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


@router.get("/api/engagements/{engagement_id}/graph")
async def engagement_graph(engagement_id: str, request: Request) -> dict:
    """The engagement's attack graph from Decepticon's Neo4j KG → `{nodes, edges}` for the console's
    force-graph. Findings are colored detected/missed from the stored scorecard. Read failures (KG
    unconfigured/unreachable) degrade to an empty graph — never 500."""
    from ...config.settings import get_settings
    from ...connectors import RedKGReader
    from ...scoring import attack_graph

    s = get_settings()
    rows: list[dict] = []
    if s.decepticon_neo4j_password:
        reader = RedKGReader(s.decepticon_neo4j_uri, s.decepticon_neo4j_user,
                             s.decepticon_neo4j_password, s.decepticon_neo4j_database)
        try:
            rows = reader.attack_events(engagement_id)
        except Exception:  # noqa: BLE001 — KG hiccup → empty graph, not a 500
            rows = []
        finally:
            reader.close()
    sc = request.app.state.store.get_scorecard(engagement_id) or {}
    return attack_graph(rows, detected_techniques=sc.get("detected_techniques", []))


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
