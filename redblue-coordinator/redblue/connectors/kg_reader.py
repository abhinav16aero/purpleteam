"""Read-only, engagement-scoped reader for Decepticon's Neo4j attack graph (plan 06 §2).

Every read MUST bind $engagement (Decepticon's KGStore enforces this server-side; we enforce it
client-side too so a read can never span tenants). Read-only role; no annotate-back in v1 (§2.4).
"""
from __future__ import annotations

from typing import Any

import neo4j


class ScopeError(ValueError):
    """Raised when a KG read is not engagement-scoped."""


def require_scoped(cypher: str) -> None:
    if "$engagement" not in cypher:
        raise ScopeError("every KG read must bind $engagement (tenant isolation)")


class RedKGReader:
    def __init__(self, uri: str, user: str, password: str, database: str = "neo4j"):
        self._driver = neo4j.GraphDatabase.driver(uri, auth=(user, password))
        self._db = database

    def close(self) -> None:
        self._driver.close()

    def _read(self, cypher: str, engagement: str, **params: Any) -> list[dict]:
        require_scoped(cypher)
        with self._driver.session(database=self._db, default_access_mode=neo4j.READ_ACCESS) as s:
            return s.execute_read(
                lambda tx: [dict(r) for r in tx.run(cypher, engagement=engagement, **params)]
            )

    # what red actually touched (the detection denominator, plan 05 §4.5)
    def attacked_surface(self, engagement: str) -> list[dict]:
        return self._read(
            "MATCH (f:Finding) WHERE f.engagement=$engagement "
            "OPTIONAL MATCH (f)<-[:REACHES|LEADS_TO*0..2]-(h:Host) "
            "RETURN f.key AS finding, f.label AS label, collect(DISTINCT h.key) AS hosts",
            engagement,
        )

    # attack ground-truth for scoring: the FULL Finding property bag + reachable hosts, so the
    # coordinator can extract (technique, entity, ts) regardless of which property Decepticon stamps
    # the MITRE technique / timestamp onto. The KG — not events.jsonl — is where the technique lives
    # (the disk finding.created payload is only {"tool": ...}, plan 05 §5). `properties(f)` returns
    # the whole node as a map; `scoring.kg_attacks` does the schema-defensive extraction.
    def attack_events(self, engagement: str) -> list[dict]:
        return self._read(
            "MATCH (f:Finding) WHERE f.engagement=$engagement "
            "OPTIONAL MATCH (f)<-[:REACHES|LEADS_TO*0..2]-(h:Host) "
            "RETURN properties(f) AS finding, collect(DISTINCT h.key) AS hosts",
            engagement,
        )

    # the FULL engagement-scoped graph (every node carrying this engagement + the edges between them)
    # → the console's interactive recon/attack graph. Scoped by the `engagement` property, so it needs
    # that on the nodes (Decepticon findings carry it; demo-seed sets it on the whole recon chain).
    def graph(self, engagement: str) -> list[dict]:
        return self._read(
            "MATCH (n) WHERE n.engagement=$engagement "
            "OPTIONAL MATCH (n)-[r]->(m) WHERE m.engagement=$engagement "
            "RETURN elementId(n) AS nid, labels(n) AS nl, "
            "coalesce(n.key,n.label,n.name,elementId(n)) AS nk, "
            "type(r) AS rt, elementId(m) AS mid",
            engagement,
        )

    # neighborhood expansion for the interactive graph (§8/§29 "expand neighbors"). STILL scoped:
    # both the anchor and every neighbor must carry this engagement, so an expand can never walk
    # across the tenant boundary. Emits the anchor AND each neighbor as a node (ml/mk) so the
    # returned rows build a self-contained {nodes, edges} subgraph.
    def neighbors(self, engagement: str, node_id: str) -> list[dict]:
        return self._read(
            "MATCH (n) WHERE elementId(n)=$node AND n.engagement=$engagement "
            "OPTIONAL MATCH (n)-[r]-(m) WHERE m.engagement=$engagement "
            "RETURN elementId(n) AS nid, labels(n) AS nl, "
            "coalesce(n.key,n.label,n.name,elementId(n)) AS nk, "
            "type(r) AS rt, elementId(m) AS mid, labels(m) AS ml, "
            "coalesce(m.key,m.label,m.name,elementId(m)) AS mk",
            engagement, node=node_id,
        )

    # shortest path between two nodes for attack-path tracing (§13/§29). Scoped: both endpoints and
    # every hop must carry this engagement. Returns one row {pnodes, pedges} (empty list if no path).
    def shortest_path(self, engagement: str, source: str, target: str) -> list[dict]:
        return self._read(
            "MATCH (a) WHERE elementId(a)=$source AND a.engagement=$engagement "
            "MATCH (b) WHERE elementId(b)=$target AND b.engagement=$engagement "
            "MATCH p=shortestPath((a)-[*..8]-(b)) "
            "WHERE all(x IN nodes(p) WHERE x.engagement=$engagement) "
            "RETURN [x IN nodes(p) | {id:elementId(x), nl:labels(x), "
            "  nk:coalesce(x.key,x.label,x.name,elementId(x))}] AS pnodes, "
            "[r IN relationships(p) | {s:elementId(startNode(r)), t:elementId(endNode(r)), "
            "  rel:type(r)}] AS pedges",
            engagement, source=source, target=target,
        )

    # blue_cell ground truth: DetectionFired -[:DETECTED]-> t, -[:USES_RULE]-> rule
    def detection_coverage(self, engagement: str) -> list[dict]:
        return self._read(
            "MATCH (d:DetectionFired)-[:DETECTED]->(t) WHERE d.engagement=$engagement "
            "OPTIONAL MATCH (d)-[:USES_RULE]->(a) "
            "RETURN t.key AS caught, d.key AS detection, a.label AS rule",
            engagement,
        )

    # findings with NO inbound DETECTED edge = what red did that nothing caught
    def detection_gaps(self, engagement: str) -> list[dict]:
        return self._read(
            "MATCH (f:Finding) WHERE f.engagement=$engagement "
            "AND NOT (f)<-[:DETECTED]-(:DetectionFired) RETURN f.key AS undetected",
            engagement,
        )
