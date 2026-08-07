"""P4 loop acceptance (plan 07 §7.3) — one engagement → scored scorecard, with no live engine.

Uses in-memory fakes injected via Deps (the ports seam). Covers: end-to-end run producing a
Scorecard (detection-rate, MTTD, gaps), evidence-chain integrity, the coverage-oracle honesty
re-label (missed → sensor_blind), and checkpoint persistence (restart-resume).
"""
from __future__ import annotations

import pytest

from redblue.contracts import MatchState, correlate, verify_chain
from redblue.evidence.store import EvidenceStore
from redblue.loop import Deps, build_graph, make_checkpointer
from redblue.scoring import StaticCoverageOracle


# ── in-memory fakes (stand in for the real connectors) ──
class FakeRed:
    async def launch(self, *, engagement, workspace, sandbox_url, tenant, instruction):
        return {"thread_id": engagement, "run_id": "run-1", "status": "success",
                "started_at": 1000.0, "ended_at": 1005.0}


class FakeAttacks:
    def __init__(self, items): self._items = items
    def attacks(self, engagement, window): return list(self._items)


class FakeDetections:
    def __init__(self, items): self._items = items
    def detections(self, engagement, window): return list(self._items)


# T1046 scanned 10.0.0.5 and was detected (mttd 10s); T1190 hit 10.0.0.9 and was missed.
ATTACKS = [
    {"technique": "T1046", "entity": "10.0.0.5", "ts": 1000.0, "red_action_id": "FIND-001"},
    {"technique": "T1190", "entity": "10.0.0.9", "ts": 1000.0, "red_action_id": "FIND-002"},
]
DETECTIONS = [
    {"technique": "T1046", "entity": "10.0.0.5", "ts": 1010.0, "finding_id": "f-20260805-abcdef0123456789"},
]

INPUT = {
    "engagement_id": "eng-t01-20260805-ab12", "tenant_id": "t01", "mode": "on_demand",
    "scope": {"in_scope": ["10.0.0.0/24"], "sandbox_url": "http://sandbox:9999"},
    "enforcement_mode": "enforce", "hitl_enabled": True, "version": 1,
}


def _deps(coverage=None, evidence=None, clock=None):
    ev = evidence or EvidenceStore()
    return Deps(
        red=FakeRed(), attack_source=FakeAttacks(ATTACKS), detection_source=FakeDetections(DETECTIONS),
        coverage=coverage or StaticCoverageOracle(default=True), evidence=ev,
        clock=clock or (lambda: 1000.0),
    )


def _cfg(eng="eng-t01-20260805-ab12"):
    return {"configurable": {"thread_id": eng}}


@pytest.mark.asyncio
async def test_loop_produces_scorecard():
    ev = EvidenceStore()
    graph = build_graph(_deps(evidence=ev), checkpointer=make_checkpointer("memory"))
    final = await graph.ainvoke(INPUT, _cfg())

    assert final["status"] == "completed"
    sc = final["scorecard"]
    assert sorted(sc["attacked_techniques"]) == ["T1046", "T1190"]
    assert sc["detected_techniques"] == ["T1046"]
    assert sc["detection_rate"] == pytest.approx(0.5)          # 1 of 2 attacked techniques detected
    assert sc["mttd"]["mean"] == pytest.approx(10.0)           # 1010 − 1000
    assert [g["technique_id"] for g in sc["gaps"]] == ["T1190"]
    assert sc["evidence_refs"]                                  # every number is evidence-backed


@pytest.mark.asyncio
async def test_evidence_chain_verifies():
    ev = EvidenceStore()
    graph = build_graph(_deps(evidence=ev), checkpointer=make_checkpointer("memory"))
    await graph.ainvoke(INPUT, _cfg())

    chain = ev.chain("eng-t01-20260805-ab12")
    kinds = [r.record_type for r in chain]
    assert kinds == ["engagement.planned", "red.launched", "telemetry.collected",
                     "scorecard.produced", "engagement.completed"]
    assert ev.verify("eng-t01-20260805-ab12") is True
    # tamper → chain breaks
    chain[2].payload_hash = "sha256:deadbeef"
    assert verify_chain(chain) is False


@pytest.mark.asyncio
async def test_coverage_oracle_reclassifies_missed_as_sensor_blind():
    # Sensors only cover T1046 → the T1190 miss is a coverage gap, NOT a blue miss.
    graph = build_graph(_deps(coverage=StaticCoverageOracle(covered_techniques=["T1046"])),
                        checkpointer=make_checkpointer("memory"))
    final = await graph.ainvoke(INPUT, _cfg())
    sc = final["scorecard"]
    assert sc["detection_rate"] == pytest.approx(1.0)          # T1190 excluded from denominator
    assert sc["gaps"] == []
    assert [g["technique"] for g in final["coverage_gaps"]] == ["T1190"]


@pytest.mark.asyncio
async def test_checkpoint_persists_final_state():
    graph = build_graph(_deps(), checkpointer=make_checkpointer("memory"))
    cfg = _cfg()
    await graph.ainvoke(INPUT, cfg)
    snap = graph.get_state(cfg)                                # restart would resume from here
    assert snap.values["status"] == "completed"
    assert snap.values["scorecard"]["scorecard_id"] == "sc-eng-t01-20260805-ab12-v1"


def test_correlate_and_coverage_units():
    corr = correlate(ATTACKS, DETECTIONS)
    states = {c["technique"]: c["state"] for c in corr}
    assert states == {"T1046": MatchState.DETECTED, "T1190": MatchState.MISSED}
    assert next(c for c in corr if c["technique"] == "T1046")["mttd_seconds"] == 10.0
