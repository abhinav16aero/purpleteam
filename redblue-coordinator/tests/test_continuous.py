"""P7 CART continuous mode (plan 07 §5) — drift → gated replay → re-score."""
from __future__ import annotations

import pytest

from redblue.continuous import (
    ChangeEvent,
    ContinuousController,
    Debouncer,
    ReplayBudget,
    build_replay_plan,
    tenant_of,
)
from redblue.evidence.store import EvidenceStore


def _ce(resource="s3://bucket", techs=("T1530",), ts=1000.0):
    return ChangeEvent(source="cloudtrail", event_type="PutBucketPolicy", resource_id=resource,
                       technique_tags=list(techs), observed_at=ts)


# ── pure CART units ──
def test_build_replay_plan_maps_techniques_and_first_is_dry_run():
    p = build_replay_plan("eng-t01-20260805-ab12", _ce(techs=["T1530", "bogus"]), first_replay=True)
    assert p.dry_run is True
    assert p.selected_objectives == ["replay T1530 against s3://bucket"]   # bogus dropped
    assert "cloudtrail:PutBucketPolicy" in p.delta_summary


def test_debouncer_collapses_same_resource_within_window():
    d = Debouncer(window_s=300.0)
    assert d.should_process("r1", 1000.0) is True
    assert d.should_process("r1", 1100.0) is False        # within 300s → collapsed
    assert d.should_process("r1", 1400.0) is True         # window elapsed
    assert d.should_process("r2", 1100.0) is True         # different resource


def test_replay_budget_caps_per_hour():
    b = ReplayBudget(max_per_hour=2)
    assert b.allow(1000.0) is True and b.allow(1001.0) is True
    assert b.allow(1002.0) is False                       # 3rd within the hour → denied
    assert b.allow(1000.0 + 3601) is True                 # window slid


def test_tenant_of():
    assert tenant_of("eng-t07-20260805-abcd") == "t07"
    assert tenant_of("weird") == "*"


# ── controller: dry-run-first gate + debounce + budget + evidence ──
@pytest.mark.asyncio
async def test_controller_first_replay_needs_approval_then_runs_live():
    ev = EvidenceStore()
    ctrl = ContinuousController(evidence=ev)
    ran: list[str] = []

    async def run(plan):
        ran.append(plan.plan_id)
        return {"version": 2, "detection_rate": 0.75}

    eng = "eng-t01-20260805-ab12"
    r1 = await ctrl.on_drift(eng, _ce(), run)
    assert r1["status"] == "needs_approval" and not ran   # dry-run: NOT executed
    plan_id = r1["plan"]["plan_id"]

    r2 = await ctrl.approve(plan_id, run, now=1001.0)
    assert r2["status"] == "replayed" and ran == [plan_id]  # live after approval
    assert r2["result"]["detection_rate"] == 0.75

    # a second drift (engagement already seen) is live-eligible, but debounced on same resource
    r3 = await ctrl.on_drift(eng, _ce(ts=1050.0), run)
    assert r3["status"] == "debounced"

    kinds = [r.record_type for r in ev.chain(eng)]
    assert "drift" in kinds and "replay.live" in kinds
    assert ev.verify(eng) is True


@pytest.mark.asyncio
async def test_controller_over_budget_blocks():
    ctrl = ContinuousController(max_replays_per_hour=1)
    ctrl._seen.add("eng-t01-20260805-ab12")               # already seen ⇒ live-eligible

    async def run(plan):
        return {"ok": True}

    a = await ctrl.on_drift("eng-t01-20260805-ab12", _ce(resource="r1", ts=1000.0), run)
    b = await ctrl.on_drift("eng-t01-20260805-ab12", _ce(resource="r2", ts=1001.0), run)
    assert a["status"] == "replayed"
    assert b["status"] == "over_budget"                    # 2nd replay in the hour → capped
