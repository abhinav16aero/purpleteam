"""P7 — the continuous flow through the API: engagement → drift → dry-run plan → approve → Scorecard v2."""
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
    def __init__(self, items): self._i = items
    def attacks(self, e, w): return list(self._i)
    def detections(self, e, w): return list(self._i)


@pytest.fixture
def client():
    deps = Deps(
        red=_FakeRed(),
        attack_source=_Src([{"technique": "T1046", "entity": "10.0.0.5", "ts": 1000.0, "red_action_id": "F1"}]),
        detection_source=_Src([{"technique": "T1046", "entity": "10.0.0.5", "ts": 1010.0,
                                "finding_id": "f-20260805-abcdef0123456789"}]),
        coverage=StaticCoverageOracle(default=True), evidence=EvidenceStore(), clock=lambda: 1000.0)
    return TestClient(create_app(deps=deps, store=CoordinatorStore("sqlite://"), checkpointer_kind="memory"))


def test_drift_dry_run_then_approve_rescores(client):
    eng = "eng-t01-20260805-cont"
    # 1) initial engagement → Scorecard v1
    r = client.post("/api/engagements", json={"tenant_id": "t01", "engagement_id": eng,
                                              "mode": "continuous", "scope": {"sandbox_url": "http://sandbox:9999"}})
    assert r.status_code == 200
    assert client.get(f"/api/engagements/{eng}/scorecard").json()["version"] == 1

    # 2) drift event → first replay is DRY-RUN (needs approval), not executed
    ce = {"source": "cloudtrail", "event_type": "PutBucketPolicy", "resource_id": "s3://tenant-bucket",
          "technique_tags": ["T1530"], "observed_at": 2000.0}
    d = client.post(f"/api/engagements/{eng}/drift", json=ce)
    assert d.status_code == 200 and d.json()["status"] == "needs_approval"
    plan_id = d.json()["plan"]["plan_id"]
    assert d.json()["plan"]["dry_run"] is True

    # 3) approve → live replay re-scores to version 2
    a = client.post(f"/api/engagements/{eng}/drift/{plan_id}/approve")
    assert a.status_code == 200 and a.json()["status"] == "replayed"
    assert a.json()["result"]["version"] == 2
    assert client.get(f"/api/engagements/{eng}/scorecard?version=2").json()["version"] == 2


def test_drift_on_unknown_engagement_404(client):
    ce = {"source": "terraform", "event_type": "apply", "resource_id": "x", "observed_at": 1.0}
    assert client.post("/api/engagements/eng-t01-20260805-ghost/drift", json=ce).status_code == 404
