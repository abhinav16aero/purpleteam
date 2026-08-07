"""P4 API acceptance (plan 07 §6/§7.3) — create engagement over HTTP → scored scorecard + evidence.

Injects fake deps + an in-memory SQLite store + memory checkpointer, so the whole control plane is
exercised end-to-end with no live engine.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from redblue.api import create_app
from redblue.evidence.store import EvidenceStore
from redblue.loop import Deps
from redblue.scoring import StaticCoverageOracle
from redblue.store import CoordinatorStore

ATTACKS = [
    {"technique": "T1046", "entity": "10.0.0.5", "ts": 1000.0, "red_action_id": "FIND-001"},
    {"technique": "T1190", "entity": "10.0.0.9", "ts": 1000.0, "red_action_id": "FIND-002"},
]
DETECTIONS = [{"technique": "T1046", "entity": "10.0.0.5", "ts": 1010.0,
               "finding_id": "f-20260805-abcdef0123456789"}]


class FakeRed:
    async def launch(self, *, engagement, workspace, sandbox_url, tenant, instruction):
        return {"thread_id": engagement, "run_id": "run-1", "status": "success",
                "started_at": 1000.0, "ended_at": 1005.0}


class FakeAttacks:
    def attacks(self, engagement, window): return list(ATTACKS)


class FakeDetections:
    def detections(self, engagement, window): return list(DETECTIONS)


@pytest.fixture
def client():
    deps = Deps(red=FakeRed(), attack_source=FakeAttacks(), detection_source=FakeDetections(),
                coverage=StaticCoverageOracle(default=True), evidence=EvidenceStore(),
                clock=lambda: 1000.0)
    app = create_app(deps=deps, store=CoordinatorStore("sqlite://"), checkpointer_kind="memory")
    return TestClient(app)


def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_create_engagement_produces_scored_scorecard(client):
    body = {"tenant_id": "t01", "engagement_id": "eng-t01-20260805-ab12", "mode": "on_demand",
            "scope": {"in_scope": ["10.0.0.0/24"], "sandbox_url": "http://sandbox:9999"}}
    r = client.post("/api/engagements", json=body)
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "completed"
    assert data["detection_rate"] == pytest.approx(0.5)
    assert data["scorecard_id"] == "sc-eng-t01-20260805-ab12-v1"

    # persisted + queryable
    eng = client.get("/api/engagements/eng-t01-20260805-ab12").json()
    assert eng["status"] == "completed" and eng["tenant_id"] == "t01"

    sc = client.get("/api/engagements/eng-t01-20260805-ab12/scorecard").json()
    assert sc["detected_techniques"] == ["T1046"]
    assert [g["technique_id"] for g in sc["gaps"]] == ["T1190"]

    ev = client.get("/api/engagements/eng-t01-20260805-ab12/evidence?verify=true").json()
    assert ev["count"] == 5 and ev["verified"] is True
    assert [r["record_type"] for r in ev["records"]][0] == "engagement.planned"


def test_reject_bad_slug(client):
    r = client.post("/api/engagements", json={"tenant_id": "t01", "engagement_id": "bad slug!"})
    assert r.status_code == 400


def test_list_and_404(client):
    client.post("/api/engagements", json={"tenant_id": "t01", "engagement_id": "eng-t01-20260805-cd34"})
    lst = client.get("/api/engagements?tenant_id=t01").json()
    assert any(e["engagement_id"] == "eng-t01-20260805-cd34" for e in lst)
    assert client.get("/api/engagements/does-not-exist").status_code == 404
