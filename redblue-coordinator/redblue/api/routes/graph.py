"""Knowledge-graph endpoints (prompt §36–37): global graph, neighbor-expand, shortest-path.

The *global* graph is the UNION of the caller-tenant's engagement-scoped subgraphs — every Neo4j read
stays engagement-bound (`RedKGReader.require_scoped`), so tenant isolation holds; the coordinator only
composes the results. Expand + path are single-engagement (also scoped). All degrade to an empty graph
(never 500) when the KG is unconfigured/unreachable, and the global graph is capped by `limit` with a
`truncated` flag so a very large graph is paginated rather than dumped (§37).
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ...config.settings import get_settings
from ...connectors import RedKGReader
from ...scoring import kg_graph

router = APIRouter()


def _reader():
    s = get_settings()
    if not s.decepticon_neo4j_password:
        return None
    return RedKGReader(s.decepticon_neo4j_uri, s.decepticon_neo4j_user,
                       s.decepticon_neo4j_password, s.decepticon_neo4j_database)


@router.get("/api/graph")
async def global_graph(request: Request, tenant_id: str | None = None, limit: int = 500) -> dict:
    """Union of every engagement's KG for `tenant_id` (all tenants only if none given). Each node is
    tagged with its `engagement` so the client can call /api/graph/node/{id}?engagement=… to expand."""
    reader = _reader()
    if reader is None:
        return {"nodes": [], "edges": [], "truncated": False}
    store = request.app.state.store
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    seen: set[tuple] = set()
    truncated = False
    try:
        for e in store.list_engagements(tenant_id=tenant_id):
            eid = e.get("engagement_id")
            if not eid:
                continue
            detected = (store.get_scorecard(eid) or {}).get("detected_techniques", [])
            try:
                g = kg_graph(reader.graph(eid), detected_techniques=detected)
            except Exception:  # noqa: BLE001, S112 — one bad engagement can't sink the whole graph
                continue
            for n in g["nodes"]:
                if n["id"] in nodes:
                    continue
                if len(nodes) >= limit:
                    truncated = True
                    break
                n["engagement"] = eid
                nodes[n["id"]] = n
            for ed in g["edges"]:
                k = (ed["source"], ed["target"], ed["rel"])
                if k not in seen and ed["source"] in nodes and ed["target"] in nodes:
                    seen.add(k)
                    edges.append(ed)
            if truncated:
                break
    finally:
        reader.close()
    return {"nodes": list(nodes.values()), "edges": edges, "truncated": truncated}


@router.get("/api/graph/node/{node_id:path}")
async def expand_node(node_id: str, request: Request, engagement: str) -> dict:
    """Neighbors of one node, scoped to `engagement` (an expand can't cross the tenant boundary)."""
    reader = _reader()
    if reader is None:
        return {"nodes": [], "edges": []}
    detected = (request.app.state.store.get_scorecard(engagement) or {}).get("detected_techniques", [])
    try:
        rows = reader.neighbors(engagement, node_id)
    except Exception:  # noqa: BLE001
        rows = []
    finally:
        reader.close()
    g = kg_graph(rows, detected_techniques=detected)
    for n in g["nodes"]:
        n["engagement"] = engagement
    return g


class PathRequest(BaseModel):
    engagement: str
    source: str
    target: str


@router.post("/api/graph/path")
async def shortest_path(req: PathRequest, request: Request) -> dict:
    """Shortest path between two nodes within one engagement → `{nodes, edges, path}` where `path` is
    the ordered node-id list to highlight (§13/§29)."""
    reader = _reader()
    if reader is None:
        return {"nodes": [], "edges": [], "path": []}
    try:
        rows = reader.shortest_path(req.engagement, req.source, req.target)
    except Exception:  # noqa: BLE001
        rows = []
    finally:
        reader.close()
    pnodes = rows[0].get("pnodes", []) if rows else []
    pedges = rows[0].get("pedges", []) if rows else []
    by_id = {p["id"]: p for p in pnodes if isinstance(p, dict) and "id" in p}
    kgrows = []
    for pe in pedges:
        s_id, t_id = pe.get("s"), pe.get("t")
        sp, tp = by_id.get(s_id, {}), by_id.get(t_id, {})
        kgrows.append({"nid": s_id, "nl": sp.get("nl"), "nk": sp.get("nk"), "rt": pe.get("rel"),
                       "mid": t_id, "ml": tp.get("nl"), "mk": tp.get("nk")})
    detected = (request.app.state.store.get_scorecard(req.engagement) or {}).get("detected_techniques", [])
    g = kg_graph(kgrows, detected_techniques=detected)
    have = {n["id"] for n in g["nodes"]}
    for p in pnodes:  # a single-node path (source==target) has no edges — still surface the node
        if p["id"] not in have:
            labs = p.get("nl") or []
            g["nodes"].append({"id": p["id"], "kind": (labs[0].lower() if labs else "node"),
                               "label": str(p.get("nk") or p["id"])[:48]})
    g["path"] = [p["id"] for p in pnodes]
    return g
