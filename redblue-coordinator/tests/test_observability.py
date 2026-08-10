"""P9 observability (plan 09 §1.4/§2) — Prometheus metrics, posture aggregate, SSE timeline."""
from __future__ import annotations

import hashlib
import hmac

import pytest
from fastapi.testclient import TestClient

from redblue.api import create_app
from redblue.evidence.store import EvidenceStore
from redblue.loop import Deps
from redblue.obs.mitre import build_mitre_rollup
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
    client.post("/api/engagements", json={"tenant_id": "t01", "hitl_enabled": False, "engagement_id": "eng-t01-20260805-obs1",
                                          "scope": {"sandbox_url": "http://sandbox:9999"}})
    body = client.get("/metrics").text
    assert "redblue_engagements_total" in body
    assert "redblue_attacks_total" in body
    assert "redblue_external_egress_bytes_total" in body     # the sovereignty SLI is exposed
    assert 'redblue_detected_total' in body


def test_posture_aggregate(client):
    client.post("/api/engagements", json={"tenant_id": "t01", "hitl_enabled": False, "engagement_id": "eng-t01-20260805-p1",
                                          "scope": {"sandbox_url": "http://sandbox:9999"}})
    p = client.get("/api/posture").json()
    assert p["engagements"] == 1
    assert p["totals"] == {"attacked": 2, "detected": 1}
    assert p["detection_rate"] == 0.5                         # instance-weighted
    assert p["mttd"]["mean"] == 10.0
    assert p["attacked_techniques"] == ["T1046", "T1190"]
    assert p["detected_techniques"] == ["T1046"]
    assert p["gap_count"] == 1


def test_mitre_rollup(client):
    client.post("/api/engagements", json={"tenant_id": "t01", "hitl_enabled": False, "engagement_id": "eng-t01-20260805-m1",
                                          "scope": {"sandbox_url": "http://sandbox:9999"}})
    r = client.get("/api/mitre").json()
    assert r["scorecards"] == 1
    assert r["totals"] == {"attacked": 2, "detected": 1}
    assert r["detection_rate"] == 0.5
    by = {t["technique_id"]: t for t in r["techniques"]}
    assert by["T1046"]["detected"] == 1 and by["T1046"]["detection_rate"] == 1.0
    assert by["T1190"]["detected"] == 0 and by["T1190"]["detection_rate"] == 0.0


def test_mitre_rollup_pure():
    scs = [
        {"per_technique": [{"technique_id": "T1046", "attacked": 2, "detected": 2, "missed": 0, "mttd_seconds": 8.0},
                           {"technique_id": "T1190", "attacked": 1, "detected": 0, "missed": 1}]},
        {"per_technique": [{"technique_id": "T1046", "attacked": 1, "detected": 0, "missed": 1},
                           {"technique_id": "T1110", "attacked": 3, "detected": 3, "missed": 0, "mttd_seconds": 12.0}]},
    ]
    out = build_mitre_rollup(scs)
    by = {t["technique_id"]: t for t in out["techniques"]}
    assert out["scorecards"] == 2 and out["technique_count"] == 3
    # T1046 is aggregated across both engagements: 3 attacked, 2 detected, seen in 2 engagements
    assert by["T1046"]["attacked"] == 3 and by["T1046"]["detected"] == 2 and by["T1046"]["engagements"] == 2
    assert by["T1046"]["detection_rate"] == 2 / 3
    assert by["T1046"]["mttd_seconds"] == 8.0     # detected-weighted: only the first engagement detected T1046
    assert out["totals"] == {"attacked": 7, "detected": 5}
    assert build_mitre_rollup([]) == {"scorecards": 0, "technique_count": 0,
                                      "totals": {"attacked": 0, "detected": 0}, "detection_rate": None, "techniques": []}


def test_evidence_bundle_export(client, monkeypatch):
    monkeypatch.delenv("REDBLUE_EVIDENCE_SIGNING_KEY", raising=False)
    client.post("/api/engagements", json={"tenant_id": "t01", "hitl_enabled": False, "engagement_id": "eng-t01-20260805-bundle",
                                          "scope": {"sandbox_url": "http://sandbox:9999"}})
    r = client.get("/api/engagements/eng-t01-20260805-bundle/evidence/bundle")
    assert r.status_code == 200
    assert 'filename="evidence-eng-t01-20260805-bundle.json"' in r.headers["content-disposition"]
    b = r.json()
    assert b["bundle_version"] == 1 and b["engagement_id"] == "eng-t01-20260805-bundle"
    assert b["count"] == len(b["records"]) and b["count"] >= 1
    assert b["digest_algo"] == "sha256" and len(b["bundle_digest"]) == 64
    assert b["signed"] is False and b["signature"] is None and b["signature_algo"] is None
    assert b["verified"] is True and b["chain_head"] == b["records"][-1]["this_hash"]
    assert client.get("/api/engagements/ghost/evidence/bundle").status_code == 404


def test_evidence_bundle_signed(client, monkeypatch):
    monkeypatch.setenv("REDBLUE_EVIDENCE_SIGNING_KEY", "s3cret-signing-key")
    client.post("/api/engagements", json={"tenant_id": "t01", "hitl_enabled": False, "engagement_id": "eng-t01-20260805-signed",
                                          "scope": {"sandbox_url": "http://sandbox:9999"}})
    b = client.get("/api/engagements/eng-t01-20260805-signed/evidence/bundle").json()
    assert b["signed"] is True and b["signature_algo"] == "hmac-sha256"
    expect = hmac.new(b"s3cret-signing-key", b["bundle_digest"].encode(), hashlib.sha256).hexdigest()
    assert b["signature"] == expect


def test_sse_timeline(client):
    client.post("/api/engagements", json={"tenant_id": "t01", "hitl_enabled": False, "engagement_id": "eng-t01-20260805-sse",
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
