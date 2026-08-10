"""Attack-plan human-in-the-loop (§2.3): the loop pauses AFTER plan_engagement and BEFORE trigger_red
when HITL is on, so an operator can review/edit/approve/reject the plan before red executes. Simulate
and hitl-off runs proceed inline (no pause)."""
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
    def __init__(self, items):
        self._i = items

    def attacks(self, e, w):
        return list(self._i)

    def detections(self, e, w):
        return list(self._i)


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


def _create(client, eng, **extra):
    body = {"tenant_id": "t01", "engagement_id": eng,
            "scope": {"in_scope": ["10.0.0.9"], "sandbox_url": "http://sandbox:9999"}, **extra}
    return client.post("/api/engagements", json=body)


def test_live_engagement_pauses_for_plan_review(client):
    eng = "eng-t01-20260805-hitl1"
    r = _create(client, eng)                                   # hitl_enabled defaults True → pause
    assert r.status_code == 200
    b = r.json()
    assert b["status"] == "awaiting_plan_approval"             # red has NOT run
    assert b["plan"]["in_scope"] == ["10.0.0.9"] and b["plan"]["status"] == "proposed"
    # the engagement row + the plan endpoint both reflect the pause
    assert client.get(f"/api/engagements/{eng}").json()["status"] == "awaiting_plan_approval"
    p = client.get(f"/api/engagements/{eng}/plan").json()
    assert p["awaiting_approval"] is True and p["plan"]["engagement_id"] == eng
    # NO scorecard yet — red hasn't executed
    assert client.get(f"/api/engagements/{eng}/scorecard").status_code == 404


def test_edit_then_approve_resumes_and_scores(client):
    eng = "eng-t01-20260805-hitl2"
    _create(client, eng)
    e = client.patch(f"/api/engagements/{eng}/plan",
                     json={"instruction": "nmap service discovery only — no exploitation",
                           "in_scope": ["10.0.0.9", "10.0.0.10"]})
    assert e.status_code == 200
    assert e.json()["plan"]["instruction"] == "nmap service discovery only — no exploitation"
    assert e.json()["plan"]["in_scope"] == ["10.0.0.9", "10.0.0.10"]
    assert e.json()["plan"]["status"] == "edited"
    # approve → resume the checkpointed run → red fires, telemetry settles, score
    a = client.post(f"/api/engagements/{eng}/plan/approve")
    assert a.status_code == 200 and a.json()["status"] == "completed"
    assert a.json()["detection_rate"] == pytest.approx(0.5)
    assert client.get(f"/api/engagements/{eng}").json()["status"] == "completed"
    # the edit + approval are in the (verified) evidence chain, plus the scorecard
    ev = client.get(f"/api/engagements/{eng}/evidence?verify=true").json()
    types = [rec["record_type"] for rec in ev["records"]]
    assert "plan.edited" in types and "plan.approved" in types
    assert "scorecard.produced" in types and ev["verified"] is True
    # approving again is rejected — no longer awaiting
    assert client.post(f"/api/engagements/{eng}/plan/approve").status_code == 409


def test_reject_cancels_without_running_red(client):
    eng = "eng-t01-20260805-hitl3"
    assert _create(client, eng).json()["status"] == "awaiting_plan_approval"
    rj = client.post(f"/api/engagements/{eng}/plan/reject", json={"reason": "scope too broad"})
    assert rj.status_code == 200 and rj.json()["status"] == "rejected"
    assert client.get(f"/api/engagements/{eng}").json()["status"] == "rejected"
    assert client.get(f"/api/engagements/{eng}/scorecard").status_code == 404   # red never ran
    # rejecting again → 409
    assert client.post(f"/api/engagements/{eng}/plan/reject", json={"reason": "x"}).status_code == 409


def test_simulate_and_hitl_off_run_inline(client):
    # simulate → no pause (hitl is bypassed for pre-seeded scoring)
    s = _create(client, "eng-t01-20260805-sim", simulate=True)
    assert s.json()["status"] == "completed" and s.json()["plan"] is None
    # explicit hitl_enabled=False → no pause
    h = _create(client, "eng-t01-20260805-nohitl", hitl_enabled=False)
    assert h.json()["status"] == "completed"


def test_plan_endpoints_409_when_not_awaiting(client):
    # a completed (hitl-off) engagement is not awaiting → plan mutations 409, GET plan still returns it
    eng = "eng-t01-20260805-done"
    _create(client, eng, hitl_enabled=False)
    assert client.patch(f"/api/engagements/{eng}/plan", json={"instruction": "x"}).status_code == 409
    assert client.post(f"/api/engagements/{eng}/plan/approve").status_code == 409
    assert client.get(f"/api/engagements/{eng}/plan").json()["awaiting_approval"] is False
