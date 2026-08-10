"""Knowledge-graph endpoints (prompt §36–37): global graph, neighbor-expand, shortest-path.

Exercises routing + response shape + the KG-unreachable degrade path (never 500). The live Neo4j path
is covered end-to-end by deploy/demo-seed.sh, same as the per-engagement /graph endpoint.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from redblue.api import create_app
from redblue.evidence.store import EvidenceStore
from redblue.loop import Deps
from redblue.scoring import StaticCoverageOracle
from redblue.store import CoordinatorStore


class _FakeRed:
    async def launch(self, **k):
        return {"thread_id": k["engagement"], "run_id": "r", "status": "success",
                "started_at": 1000.0, "ended_at": 1005.0}


class _Src:
    def attacks(self, e, w):
        return []

    def detections(self, e, w):
        return []


@pytest.fixture
def client():
    deps = Deps(red=_FakeRed(), attack_source=_Src(), detection_source=_Src(),
                coverage=StaticCoverageOracle(default=True), evidence=EvidenceStore(), clock=lambda: 1000.0)
    return TestClient(create_app(deps=deps, store=CoordinatorStore("sqlite://"), checkpointer_kind="memory"))


def test_global_graph_degrades_to_empty(client):
    r = client.get("/api/graph", params={"tenant_id": "t01"})
    assert r.status_code == 200
    body = r.json()
    assert body["nodes"] == [] and body["edges"] == [] and body["truncated"] is False


def test_expand_node_degrades_to_empty(client):
    r = client.get("/api/graph/node/4:abc:5", params={"engagement": "eng-x"})
    assert r.status_code == 200
    assert r.json() == {"nodes": [], "edges": []}


def test_shortest_path_degrades_to_empty(client):
    r = client.post("/api/graph/path", json={"engagement": "eng-x", "source": "a", "target": "b"})
    assert r.status_code == 200
    body = r.json()
    assert body["nodes"] == [] and body["edges"] == [] and body["path"] == []


def test_sensors_reports_probeable_components(client):
    r = client.get("/api/sensors")
    assert r.status_code == 200
    names = {s["name"]: s for s in r.json()["sensors"]}
    assert names["Coordinator"]["status"] == "healthy"
    assert "Neo4j" in names  # probed (unconfigured in tests, never hangs/500s)
    # telemetry sensors are declared external — the coordinator does not fabricate their health
    assert names["Wazuh"]["status"] == "external" and names["Suricata"]["source"] == "telemetry"


def test_agents_reports_red_runs_not_fabricated_roster(client):
    r = client.get("/api/agents")
    assert r.status_code == 200
    body = r.json()
    assert body["team"] == "red" and body["engine"] == "Decepticon"
    assert isinstance(body["runs"], list) and "per-agent detail is internal" in body["note"]
