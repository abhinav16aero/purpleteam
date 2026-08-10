"""P5 — kill-switch API (plan 08 §5): global/per-tenant kill halts new engagements + logs to WORM."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from redblue.api import create_app
from redblue.config.tenants import TenantPolicy, TenantPolicyRegistry
from redblue.evidence.store import EvidenceStore
from redblue.governance import AssetMap, KillSwitch, PolicyEngine, default_response_planner
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
    ev = EvidenceStore()
    engine = PolicyEngine(asset_map=AssetMap(tenant_assets={"10.0.0.5": "t01"}),
                          tenant_policies=TenantPolicyRegistry([TenantPolicy(tenant_id="t01", force_manual=True)]),
                          clock=lambda: 1000.0)
    deps = Deps(red=_FakeRed(),
                attack_source=_Src([{"technique": "T1046", "entity": "10.0.0.5", "ts": 1000.0, "red_action_id": "F1"}]),
                detection_source=_Src([{"technique": "T1046", "entity": "10.0.0.5", "ts": 1010.0, "finding_id": "f-20260805-abcdef0123456789"}]),
                coverage=StaticCoverageOracle(default=True), evidence=ev, clock=lambda: 1000.0,
                policy_engine=engine, killswitch=KillSwitch(evidence=ev),
                response_planner=default_response_planner)
    return TestClient(create_app(deps=deps, store=CoordinatorStore("sqlite://"), checkpointer_kind="memory"))


def test_global_kill_then_engagement_refused(client):
    # governed engagement runs and queues human-tier actions
    r = client.post("/api/engagements", json={"tenant_id": "t01", "hitl_enabled": False, "engagement_id": "eng-t01-20260805-run1",
                                              "scope": {"sandbox_url": "http://sandbox:9999"}})
    assert r.status_code == 200 and r.json()["status"] == "completed"

    # pull the scorecard's governed decisions are recorded in evidence
    kill = client.post("/api/kill", json={"by": "rahul", "reason": "incident"})
    assert kill.status_code == 200 and kill.json()["halted"] is True

    # a new engagement is now refused cleanly (kill switch active) → 409
    r2 = client.post("/api/engagements", json={"tenant_id": "t01", "hitl_enabled": False, "engagement_id": "eng-t01-20260805-run2"})
    assert r2.status_code == 409


def test_tenant_kill_scoped(client):
    k = client.post("/api/tenants/t02/kill", json={"by": "rahul", "reason": "tenant incident"})
    assert k.json()["tenant_id"] == "t02" and k.json()["halted"] is True
    # t01 still runs
    r = client.post("/api/engagements", json={"tenant_id": "t01", "hitl_enabled": False, "engagement_id": "eng-t01-20260805-ok",
                                              "scope": {"sandbox_url": "http://sandbox:9999"}})
    assert r.status_code == 200
