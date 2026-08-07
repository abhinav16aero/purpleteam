"""The single authoritative pre-action hook (plan 08 §1, §2). Deterministic code — never an LLM.

evaluate(env) → PolicyDecision. Order (each step can only ratchet the tier UP):
  1. boundary predicate FIRST — cross-tenant / control-plane ⇒ T2_NEVER_AUTO (the hard rule, 00 §10)
  2. base tier from the action kind (time-boxed / mutating-SPL adjustments)
  3. confidence (blue) < 0.90 raises AUTO→HUMAN; engine_risk (red) == high raises to ≥HUMAN
  4. per-tenant overlay + force_manual (raise only)
Fail-CLOSED: any error ⇒ DENY.
"""
from __future__ import annotations

import time

from ..contracts import ActionType, Tier
from .assets import AssetMap
from .envelope import (
    CONTROL_PLANE,
    FORCE_MANUAL,
    HIGH_ENGINE_RISK,
    HIGH_IMPACT,
    LOW_BLAST,
    LOW_CONFIDENCE,
    MUTATING_QUERY,
    NOT_TIME_BOXED,
    POLICY_ERROR,
    ROE_REFUSED,
    TENANT_BOUNDARY,
    TENANT_OVERRIDE,
    ActionEnvelope,
    Boundary,
    Decision,
    PolicyDecision,
)
from .policy_map import BLUE_BASE_TIER, RED_BASE_TIER, is_mutating_spl, max_tier

CONFIDENCE_GATE = 0.90                 # reconciled with Vigil's authoritative gate (plan 08 §0)


class PolicyEngine:
    def __init__(self, asset_map: AssetMap | None = None, tenant_policies=None,
                 clock=time.time) -> None:
        self._assets = asset_map or AssetMap()
        self._policies = tenant_policies                    # TenantPolicyRegistry | None
        self._clock = clock

    def _tenant_policy(self, tenant_id: str):
        if self._policies is None:
            from ..config.tenants import TenantPolicy
            return TenantPolicy(tenant_id=tenant_id)        # default: force_manual=True (safe-by-default)
        return self._policies.get(tenant_id)

    def _base_tier(self, env: ActionEnvelope) -> tuple[Tier, str]:
        if env.origin == "decepticon":
            if env.roe_decision == "refuse":
                return Tier.NEVER, ROE_REFUSED
            t = RED_BASE_TIER.get(env.kind, Tier.HUMAN)
            return t, (LOW_BLAST if t == Tier.AUTO else HIGH_IMPACT)
        # blue / coordinator ActionType
        k = env.kind
        if k == ActionType.EXECUTE_SPL_QUERY.value and is_mutating_spl(env.query):
            return Tier.HUMAN, MUTATING_QUERY
        if k in (ActionType.BLOCK_IP.value, ActionType.BLOCK_DOMAIN.value) and not env.ttl_seconds:
            return Tier.HUMAN, NOT_TIME_BOXED               # not time-boxed ⇒ human
        base = BLUE_BASE_TIER.get(k, Tier.HUMAN)
        return base, (LOW_BLAST if base == Tier.AUTO else HIGH_IMPACT)

    def evaluate(self, env: ActionEnvelope) -> PolicyDecision:
        try:
            pol = self._tenant_policy(env.tenant_id)

            # 1. boundary FIRST — never-auto, regardless of anything else. Uses the tenant's
            #    two-person requirement (the strongest case must not get the weakest approver count).
            boundary = self._assets.crosses_boundary(env)
            if boundary != Boundary.NONE:
                return PolicyDecision(
                    action_id=env.action_id, decision=Decision.NEVER_AUTO_HUMAN, tier=Tier.NEVER,
                    reason_code=(CONTROL_PLANE if boundary == Boundary.CONTROL_PLANE else TENANT_BOUNDARY),
                    boundary=boundary, required_approvers=getattr(pol, "required_approvers_t2", 2),
                    rationale="crosses a tenant/control-plane boundary — never auto (00 §10)")

            tier, reason = self._base_tier(env)
            if env.roe_decision == "refuse":                # red hard-deny
                return PolicyDecision(action_id=env.action_id, decision=Decision.DENY, tier=Tier.NEVER,
                                      reason_code=ROE_REFUSED, rationale="RoE refused the action")

            # 2. confidence (blue) / engine_risk (red) can only raise. A Vigil-origin action is
            #    expected to carry a summed-evidence confidence — MISSING confidence fails CLOSED
            #    (can't confirm >= gate). Coordinator-origin actions are tiered by kind, not confidence.
            if tier == Tier.AUTO:
                low_confidence = env.confidence is not None and env.confidence < CONFIDENCE_GATE
                missing_confidence = env.confidence is None and env.origin == "vigil"  # fail-closed
                if low_confidence or missing_confidence:
                    tier, reason = Tier.HUMAN, LOW_CONFIDENCE
            if env.engine_risk == "high" and tier == Tier.AUTO:
                tier, reason = Tier.HUMAN, HIGH_ENGINE_RISK

            # 3. per-tenant overlay + force_manual (raise only)
            overlay = pol.overrides.get(env.kind)
            if overlay is not None and max_tier(tier, overlay) != tier:
                tier, reason = overlay, TENANT_OVERRIDE
            if pol.force_manual and tier == Tier.AUTO:
                tier, reason = Tier.HUMAN, FORCE_MANUAL

            return self._decide(env, tier, reason, pol)
        except Exception as e:  # fail-closed
            return PolicyDecision(action_id=env.action_id, decision=Decision.DENY, tier=Tier.NEVER,
                                  reason_code=POLICY_ERROR, rationale=str(e))

    def _decide(self, env: ActionEnvelope, tier: Tier, reason: str, pol) -> PolicyDecision:
        if tier == Tier.AUTO:
            expiry = (self._clock() + env.ttl_seconds) if env.ttl_seconds else None
            return PolicyDecision(action_id=env.action_id, decision=Decision.AUTO, tier=tier,
                                  reason_code=reason, required_approvers=0, expiry_at=expiry)
        if tier == Tier.HUMAN:
            return PolicyDecision(action_id=env.action_id, decision=Decision.HUMAN_APPROVAL, tier=tier,
                                  reason_code=reason, required_approvers=1)
        return PolicyDecision(action_id=env.action_id, decision=Decision.NEVER_AUTO_HUMAN, tier=tier,
                              reason_code=reason,
                              required_approvers=getattr(pol, "required_approvers_t2", 2))
