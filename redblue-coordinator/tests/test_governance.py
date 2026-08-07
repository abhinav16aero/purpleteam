"""P5 governance acceptance (plan 08 §9.1) — tiered autonomy, boundary never-auto, unified decision."""
from __future__ import annotations

import pytest

from redblue.config.tenants import TenantPolicy, TenantPolicyRegistry
from redblue.contracts import ActionType, Tier
from redblue.governance import AssetMap, Decision, PolicyEngine
from redblue.governance.envelope import (
    CONTROL_PLANE,
    FORCE_MANUAL,
    LOW_CONFIDENCE,
    NOT_TIME_BOXED,
    TENANT_BOUNDARY,
    ActionEnvelope,
    Boundary,
)


def _env(kind, tenant="t01", target="10.0.0.5", **kw):
    return ActionEnvelope(action_id="a1", tenant_id=tenant, engagement_id="eng-t01-20260805-ab12",
                          origin="coordinator", kind=kind, target={"raw": target}, **kw)


def _engine(force_manual=False, assets=None):
    reg = TenantPolicyRegistry([TenantPolicy(tenant_id="t01", force_manual=force_manual)])
    amap = assets or AssetMap(tenant_assets={"10.0.0.5": "t01", "10.0.0.9": "t01"})
    return PolicyEngine(asset_map=amap, tenant_policies=reg, clock=lambda: 1000.0)


def test_time_boxed_block_ip_is_auto_when_not_force_manual():
    d = _engine(force_manual=False).evaluate(_env(ActionType.BLOCK_IP.value, ttl_seconds=3600, reversible=True))
    assert d.decision == Decision.AUTO and d.tier == Tier.AUTO
    assert d.expiry_at == pytest.approx(4600.0)             # 1000 + 3600 auto-expiry


def test_force_manual_promotes_auto_to_human():
    d = _engine(force_manual=True).evaluate(_env(ActionType.BLOCK_IP.value, ttl_seconds=3600, reversible=True))
    assert d.decision == Decision.HUMAN_APPROVAL and d.tier == Tier.HUMAN and d.reason_code == FORCE_MANUAL


def test_non_time_boxed_block_ip_is_human():
    d = _engine(force_manual=False).evaluate(_env(ActionType.BLOCK_IP.value))
    assert d.tier == Tier.HUMAN and d.reason_code == NOT_TIME_BOXED


def test_isolate_host_is_human():
    d = _engine(force_manual=False).evaluate(_env(ActionType.ISOLATE_HOST.value))
    assert d.decision == Decision.HUMAN_APPROVAL and d.tier == Tier.HUMAN


def test_cross_tenant_target_is_never_auto_regardless_of_everything():
    # target belongs to another tenant → T2, even time-boxed + reversible + not force_manual
    amap = AssetMap(tenant_assets={"10.9.9.9": "t02"})
    d = _engine(force_manual=False, assets=amap).evaluate(
        _env(ActionType.BLOCK_IP.value, target="10.9.9.9", ttl_seconds=3600, reversible=True))
    assert d.decision == Decision.NEVER_AUTO_HUMAN and d.tier == Tier.NEVER
    assert d.boundary == Boundary.TENANT and d.reason_code == TENANT_BOUNDARY and d.required_approvers == 2


def test_control_plane_target_is_never_auto():
    d = _engine(force_manual=False).evaluate(_env(ActionType.BLOCK_IP.value, target="ollama", ttl_seconds=3600))
    assert d.tier == Tier.NEVER and d.reason_code == CONTROL_PLANE and d.boundary == Boundary.CONTROL_PLANE


def test_unknown_target_fails_closed_to_never():
    amap = AssetMap(tenant_assets={})                       # nothing known
    d = _engine(force_manual=False, assets=amap).evaluate(
        _env(ActionType.BLOCK_IP.value, target="203.0.113.7", ttl_seconds=3600))
    assert d.tier == Tier.NEVER                             # unknown ⇒ assumed foreign


def test_low_confidence_raises_auto_to_human():
    d = _engine(force_manual=False).evaluate(
        _env(ActionType.BLOCK_IP.value, ttl_seconds=3600, confidence=0.5))
    assert d.tier == Tier.HUMAN and d.reason_code == LOW_CONFIDENCE


def test_mutating_spl_is_human_read_only_is_auto():
    e = _engine(force_manual=False)
    ro = e.evaluate(_env(ActionType.EXECUTE_SPL_QUERY.value, query="search index=main | stats count"))
    mut = e.evaluate(_env(ActionType.EXECUTE_SPL_QUERY.value, query="search index=main | delete"))
    assert ro.tier == Tier.AUTO and mut.tier == Tier.HUMAN


def test_tenant_overlay_can_only_raise():
    reg = TenantPolicyRegistry([TenantPolicy(tenant_id="t01", force_manual=False,
                                             overrides={ActionType.BLOCK_IP.value: Tier.NEVER})])
    amap = AssetMap(tenant_assets={"10.0.0.5": "t01"})
    d = PolicyEngine(asset_map=amap, tenant_policies=reg).evaluate(
        _env(ActionType.BLOCK_IP.value, ttl_seconds=3600))
    assert d.tier == Tier.NEVER                             # overlay raised AUTO→NEVER


def test_red_recon_auto_exploit_human_destruction_never():
    e = _engine(force_manual=False, assets=AssetMap(tenant_assets={"10.0.0.5": "t01"}))
    def red(kind, **kw):
        return ActionEnvelope(action_id="r", tenant_id="t01", engagement_id="eng-t01-20260805-ab12",
                              origin="decepticon", kind=kind, target={"raw": "10.0.0.5"}, **kw)
    assert e.evaluate(red("recon")).tier == Tier.AUTO
    assert e.evaluate(red("exploit")).tier == Tier.HUMAN
    assert e.evaluate(red("destruction")).tier == Tier.NEVER
    assert e.evaluate(red("recon", roe_decision="refuse")).decision == Decision.DENY
