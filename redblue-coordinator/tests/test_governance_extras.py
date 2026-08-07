"""P5 — verification gate, WORM/HMAC evidence, kill switch, and a full governed loop run."""
from __future__ import annotations

import pytest

from redblue.config.tenants import TenantPolicy, TenantPolicyRegistry
from redblue.contracts import ActionType
from redblue.evidence.store import EvidenceStore
from redblue.evidence.worm import WormEvidenceStore
from redblue.governance import AssetMap, KillSwitch, PolicyEngine, verify
from redblue.loop import Deps, build_graph, make_checkpointer
from redblue.scoring import StaticCoverageOracle


# ── verification gate (plan 08 §7) ──
def test_verification_rejects_unbacked_and_passes_grounded():
    assert verify({"evidence_refs": []}, "blue_verdict").ok is False
    assert verify({"evidence_refs": ["f-1"]}, "blue_verdict").ok is True
    assert verify({}, "red_finding").ok is False                      # no artifact
    assert verify({"command": "nmap", "output": "80/open"}, "red_finding").ok is True
    assert verify({"command": "x", "output": "y", "roe_decision": "refuse"}, "red_finding").ok is False
    # dereference resolver: a ref that doesn't resolve is rejected
    assert verify({"evidence_refs": ["ghost"]}, "blue_verdict", resolver=lambda r: False).ok is False


# ── WORM / HMAC evidence (plan 08 §4) ──
def test_worm_hmac_verifies_and_localizes_tamper():
    store = WormEvidenceStore(hmac_keys={"t01": "00112233445566778899aabbccddeeff"})
    for i in range(4):
        store.append(engagement_id="e", tenant_id="t01", actor="coordinator",
                     record_type="policy_decision", payload={"i": i}, ts=1000.0 + i)
    v = store.verify_ledger("e")
    assert v == {"ok": True, "first_bad_seq": None}
    # tamper record #2 → chain + hmac break there
    store.chain("e")[2].payload_hash = "sha256:deadbeef"
    bad = store.verify_ledger("e")
    assert bad["ok"] is False and bad["first_bad_seq"] == 2


# ── kill switch (plan 08 §5) ──
def test_kill_switch_halts_and_logs(tmp_path):
    ev = EvidenceStore()
    ks = KillSwitch(evidence=ev, workspace_root=str(tmp_path))
    (tmp_path / "eng-t01-20260805-ab12").mkdir()
    assert ks.is_halted("t01") is False
    res = ks.kill(scope="tenant", tenant_id="t01", by="rahul", reason="incident",
                  engagement_ids=["eng-t01-20260805-ab12"])
    assert ks.is_halted("t01") is True and ks.is_halted("t02") is False
    assert (tmp_path / "eng-t01-20260805-ab12" / ".abort").exists()   # .abort marker written
    assert [r.record_type for r in ev.chain("t01")] == ["kill_switch"]


def test_kill_switch_refuses_new_engagement():
    ks = KillSwitch()
    ks.kill(scope="global", by="rahul", reason="stop everything")
    deps = _governed_deps(killswitch=ks)
    graph = build_graph(deps, checkpointer=make_checkpointer("memory"))
    import anyio
    with pytest.raises(Exception):
        anyio.run(graph.ainvoke, _INPUT, {"configurable": {"thread_id": "eng-t01-20260805-ab12"}})


# ── full governed loop (plan 08 §2, decide_response wired) ──
ATTACKS = [{"technique": "T1046", "entity": "10.0.0.5", "ts": 1000.0, "red_action_id": "FIND-001"}]
DETECTIONS = [{"technique": "T1046", "entity": "10.0.0.5", "ts": 1010.0,
               "finding_id": "f-20260805-abcdef0123456789"}]
_INPUT = {"engagement_id": "eng-t01-20260805-ab12", "tenant_id": "t01", "mode": "on_demand",
          "scope": {"sandbox_url": "http://sandbox:9999"}, "enforcement_mode": "enforce",
          "hitl_enabled": True, "version": 1}


class _FakeRed:
    async def launch(self, **k):
        return {"thread_id": k["engagement"], "run_id": "r", "status": "success",
                "started_at": 1000.0, "ended_at": 1005.0}


class _Src:
    def __init__(self, items): self._i = items
    def attacks(self, e, w): return list(self._i)
    def detections(self, e, w): return list(self._i)


def _governed_deps(force_manual=True, killswitch=None):
    reg = TenantPolicyRegistry([TenantPolicy(tenant_id="t01", force_manual=force_manual)])
    engine = PolicyEngine(asset_map=AssetMap(tenant_assets={"10.0.0.5": "t01"}),
                          tenant_policies=reg, clock=lambda: 1000.0)
    return Deps(red=_FakeRed(), attack_source=_Src(ATTACKS), detection_source=_Src(DETECTIONS),
                coverage=StaticCoverageOracle(default=True), evidence=EvidenceStore(),
                clock=lambda: 1000.0, policy_engine=engine, killswitch=killswitch)


@pytest.mark.asyncio
async def test_governed_loop_tiers_and_queues_actions():
    deps = _governed_deps(force_manual=True)
    graph = build_graph(deps, checkpointer=make_checkpointer("memory"))
    final = await graph.ainvoke(_INPUT, {"configurable": {"thread_id": "eng-t01-20260805-ab12"}})

    decisions = {d["kind"]: d for d in final["response_decisions"]}
    # force_manual ⇒ the time-boxed block_ip is promoted to HUMAN; isolate_host is HUMAN
    assert decisions[ActionType.BLOCK_IP.value]["tier"] == "human"
    assert decisions[ActionType.ISOLATE_HOST.value]["tier"] == "human"
    assert len(final["pending_actions"]) == 2               # both queued for approval
    # every policy decision is evidence-backed
    kinds = [r.record_type for r in deps.evidence.chain("eng-t01-20260805-ab12")]
    assert kinds.count("policy_decision") == 2
    assert deps.evidence.verify("eng-t01-20260805-ab12") is True
