"""P9 observability (plan 09 §1.4/§2) — Prometheus metrics, posture aggregate, SSE timeline."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from redblue.api import create_app
from redblue.evidence.store import EvidenceStore
from redblue.loop import Deps
from redblue.obs.posture import build_posture
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
        attack_source=_Src([{"technique": "T1046", "entity": "10.0.0.5", "ts": 1000.0, "red_action_id": "F1"},
                            {"technique": "T1190", "entity": "10.0.0.9", "ts": 1000.0, "red_action_id": "F2"}]),
        detection_source=_Src([{"technique": "T1046", "entity": "10.0.0.5", "ts": 1010.0,
                                "finding_id": "f-20260805-abcdef0123456789"}]),
        coverage=StaticCoverageOracle(default=True), evidence=EvidenceStore(), clock=lambda: 1000.0)
    return TestClient(create_app(deps=deps, store=CoordinatorStore("sqlite://"), checkpointer_kind="memory"))


def test_metrics_endpoint_after_engagement(client):
    client.post("/api/engagements", json={"tenant_id": "t01", "engagement_id": "eng-t01-20260805-obs1",
                                          "scope": {"sandbox_url": "http://sandbox:9999"}})
    body = client.get("/metrics").text
    assert "redblue_engagements_total" in body
    assert "redblue_attacks_total" in body
    assert "redblue_external_egress_bytes_total" in body     # the sovereignty SLI is exposed
    assert 'redblue_detected_total' in body


def test_posture_aggregate(client):
    client.post("/api/engagements", json={"tenant_id": "t01", "engagement_id": "eng-t01-20260805-p1",
                                          "scope": {"sandbox_url": "http://sandbox:9999"}})
    p = client.get("/api/posture").json()
    assert p["engagements"] == 1
    assert p["totals"] == {"attacked": 2, "detected": 1}
    assert p["detection_rate"] == 0.5                         # instance-weighted
    assert p["mttd"]["mean"] == 10.0
    assert p["attacked_techniques"] == ["T1046", "T1190"]
    assert p["detected_techniques"] == ["T1046"]
    assert p["gap_count"] == 1


def test_sse_timeline(client):
    client.post("/api/engagements", json={"tenant_id": "t01", "engagement_id": "eng-t01-20260805-sse",
                                          "scope": {"sandbox_url": "http://sandbox:9999"}})
    r = client.get("/api/engagements/eng-t01-20260805-sse/events")
    assert r.status_code == 200 and "text/event-stream" in r.headers["content-type"]
    assert "event: engagement.planned" in r.text
    assert "event: scorecard.produced" in r.text
    assert r.text.strip().endswith("event: end\ndata: {}")
    assert client.get("/api/engagements/ghost/events").status_code == 404


def test_posture_builder_pure():
    scs = [
        {"per_finding": [{"detected": True, "mttd_seconds": 5.0}, {"detected": False}],
         "attacked_techniques": ["T1"], "detected_techniques": ["T1"], "gaps": [{"technique_id": "T1"}]},
        {"per_finding": [{"detected": True, "mttd_seconds": 15.0}],
         "attacked_techniques": ["T2"], "detected_techniques": ["T2"], "gaps": []},
    ]
    p = build_posture(scs)
    assert p["totals"] == {"attacked": 3, "detected": 2}
    assert p["detection_rate"] == pytest.approx(2 / 3)
    assert p["mttd"]["mean"] == 10.0
    assert p["attack_coverage"] == {"attacked": 2, "detected": 2}
