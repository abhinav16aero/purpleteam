"""Observability endpoints (plan 09 §1.4/§2): Prometheus /metrics, posture aggregate, SSE timeline."""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

from ...obs import render
from ...obs.mitre import build_mitre_rollup
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
    from ...scoring import attack_graph, kg_graph

    s = get_settings()
    graph_rows: list[dict] = []
    surface_rows: list[dict] = []
    if s.decepticon_neo4j_password:
        reader = RedKGReader(s.decepticon_neo4j_uri, s.decepticon_neo4j_user,
                             s.decepticon_neo4j_password, s.decepticon_neo4j_database)
        try:
            graph_rows = reader.graph(engagement_id)          # full engagement-scoped graph
            if not graph_rows:                                 # fallback: finding→host→technique surface
                surface_rows = reader.attack_events(engagement_id)
        except Exception:  # noqa: BLE001 — KG hiccup → empty graph, not a 500
            graph_rows, surface_rows = [], []
        finally:
            reader.close()
    detected = (request.app.state.store.get_scorecard(engagement_id) or {}).get("detected_techniques", [])
    if graph_rows:
        return kg_graph(graph_rows, detected_techniques=detected)
    return attack_graph(surface_rows, detected_techniques=detected)


@router.get("/api/mitre")
async def mitre_rollup(request: Request, tenant_id: str | None = None) -> dict:
    """ATT&CK coverage rolled up across every engagement's latest scorecard (prompt §21) — the org-wide
    MITRE matrix, versus the per-engagement view the scorecard already gives."""
    scorecards = request.app.state.store.list_scorecards(tenant_id=tenant_id)
    return build_mitre_rollup(scorecards)


@router.get("/api/sensors")
async def sensors() -> dict:
    """Component health the coordinator can ACTUALLY probe — nothing fabricated. It reports itself
    (up), a live Neo4j connectivity check, and declares the telemetry sensors (Wazuh/Suricata/Falco)
    as `external` (their health is owned by the telemetry stack / Prometheus, not the coordinator), so
    the UI can show a Vigil `connections/status` panel beside these rather than invent CPU sparklines."""
    import time

    import neo4j

    from ...config.settings import get_settings

    s = get_settings()
    out: list[dict] = [{"name": "Coordinator", "kind": "LangGraph", "status": "healthy", "source": "self"}]
    if s.decepticon_neo4j_password:
        st, lat = "down", None
        try:
            drv = neo4j.GraphDatabase.driver(
                s.decepticon_neo4j_uri, auth=(s.decepticon_neo4j_user, s.decepticon_neo4j_password),
                connection_timeout=2.0)
            t0 = time.perf_counter()
            drv.verify_connectivity()                      # connection probe only — not a scoped read
            lat = round((time.perf_counter() - t0) * 1000, 1)
            st = "healthy"
            drv.close()
        except Exception:  # noqa: BLE001 — a down dependency is a status, not a 500
            st = "down"
        out.append({"name": "Neo4j", "kind": "Knowledge Graph", "status": st, "latency_ms": lat, "source": "probe"})
    else:
        out.append({"name": "Neo4j", "kind": "Knowledge Graph", "status": "unconfigured", "source": "probe"})
    for nm, kind in (("Wazuh", "HIDS / SIEM"), ("Suricata", "NIDS"), ("Falco", "Runtime")):
        out.append({"name": nm, "kind": kind, "status": "external", "source": "telemetry",
                    "note": "health reported by the telemetry stack, not the coordinator"})
    return {"sensors": out}


@router.get("/api/agents")
async def agents(request: Request, tenant_id: str | None = None) -> dict:
    """The coordinator's HONEST view of the red side: per-agent telemetry (Decepticon's ~25 agents) is
    internal to Decepticon and not exposed here, so this reports the red-RUN execution status per
    engagement (what the coordinator actually drives). The blue roster (Vigil's 13 agents) comes from
    Vigil's own /api/agents — the AI-Agents screen composes both."""
    engs = request.app.state.store.list_engagements(tenant_id=tenant_id)
    runs = [{"engagement_id": e.get("engagement_id"), "tenant_id": e.get("tenant_id"),
             "status": e.get("status"), "thread_id": e.get("thread_id"),
             "target": e.get("target"), "team": "red", "role": "Decepticon red run"}
            for e in engs]
    return {"team": "red", "engine": "Decepticon",
            "note": "per-agent detail is internal to Decepticon; the coordinator reports red-run status per engagement",
            "runs": runs, "active": sum(1 for r in runs if r["status"] == "running")}


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
