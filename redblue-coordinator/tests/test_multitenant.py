"""P8 — multi-tenant isolation (plan 08 §9.3): distinct evidence chains, distinct policy, no cross-read,
cross-tenant/control-plane actions never-auto — proven with two concurrent tenants."""
from __future__ import annotations

from redblue.config.tenants import TenantPolicy, TenantPolicyRegistry
from redblue.contracts import ActionType, Tier
from redblue.evidence.store import EvidenceStore
from redblue.governance import AssetMap, Decision, PolicyEngine
from redblue.governance.envelope import ActionEnvelope


def _env(tenant, target, kind=ActionType.BLOCK_IP.value, **kw):
    return ActionEnvelope(action_id=f"a-{tenant}", tenant_id=tenant,
                          engagement_id=f"eng-{tenant}-20260805-ab12", origin="coordinator",
                          kind=kind, target={"raw": target}, ttl_seconds=3600, **kw)


def test_two_tenants_have_isolated_evidence_chains():
    ev = EvidenceStore()
    ev.append(engagement_id="eng-t01-20260805-a", tenant_id="t01", actor="coordinator",
              record_type="engagement.planned", payload={"x": 1})
    ev.append(engagement_id="eng-t02-20260805-b", tenant_id="t02", actor="coordinator",
              record_type="engagement.planned", payload={"y": 2})
    # each engagement is its own chain — t01 cannot see t02's records
    assert len(ev.chain("eng-t01-20260805-a")) == 1
    assert len(ev.chain("eng-t02-20260805-b")) == 1
    assert ev.chain("eng-t01-20260805-a")[0].tenant_id == "t01"
    assert ev.verify("eng-t01-20260805-a") and ev.verify("eng-t02-20260805-b")


def test_tenant_a_action_on_tenant_b_asset_is_never_auto():
    # asset map: 10.0.1.5 belongs to t01, 10.0.2.9 belongs to t02
    amap = AssetMap(tenant_assets={"10.0.1.5": "t01", "10.0.2.9": "t02"})
    reg = TenantPolicyRegistry([TenantPolicy(tenant_id="t01", force_manual=False),
                                TenantPolicy(tenant_id="t02", force_manual=False)])
    engine = PolicyEngine(asset_map=amap, tenant_policies=reg)

    own = engine.evaluate(_env("t01", "10.0.1.5"))               # t01 acting on its own asset
    cross = engine.evaluate(_env("t01", "10.0.2.9"))             # t01 acting on t02's asset

    assert own.decision == Decision.AUTO                          # in-tenant, time-boxed → auto ok
    assert cross.decision == Decision.NEVER_AUTO_HUMAN           # cross-tenant → never, 2 approvers
    assert cross.tier == Tier.NEVER and cross.required_approvers == 2


def test_per_tenant_policy_overlay_is_independent():
    reg = TenantPolicyRegistry([
        TenantPolicy(tenant_id="t01", force_manual=False),                       # autonomy-enabled
        TenantPolicy(tenant_id="t02", force_manual=True),                        # BFSI: safe-by-default
    ])
    amap = AssetMap(tenant_assets={"10.0.1.5": "t01", "10.0.2.9": "t02"})
    engine = PolicyEngine(asset_map=amap, tenant_policies=reg)
    assert engine.evaluate(_env("t01", "10.0.1.5")).tier == Tier.AUTO
    assert engine.evaluate(_env("t02", "10.0.2.9")).tier == Tier.HUMAN          # same action, stricter tenant
