"""Node 1 — plan_engagement (plan 07 §2.3).

Validate the engagement slug, assert the per-tenant safety posture (RoE enforce + HITL, plan
decepticon-safety-gates), open the scoring window, and write the first evidence record.
P4 records a warning if the safety gate isn't set; P5 (R6) hard-refuses.
"""
from __future__ import annotations

from ...connectors import valid_engagement
from ..ports import Deps
from ..state import LoopState


def make_plan_engagement(deps: Deps):
    async def plan_engagement(state: LoopState) -> dict:
        eng, tenant = state["engagement_id"], state["tenant_id"]
        if not valid_engagement(eng):
            raise ValueError(f"invalid engagement slug {eng!r} (fails Decepticon regex)")
        # kill switch (plan 08 §5): refuse to start a halted tenant/global.
        if deps.killswitch is not None and deps.killswitch.is_halted(tenant):
            raise RuntimeError(f"kill switch active for tenant {tenant!r} — engagement refused")

        enforce = state.get("enforcement_mode", "enforce")
        hitl = state.get("hitl_enabled", True)
        errors: list[dict] = []
        if enforce != "enforce":
            errors.append({"node": "plan_engagement",
                           "warn": f"enforcement_mode={enforce!r} — RoE not enforced (P5 will hard-refuse)"})
        if not hitl:
            errors.append({"node": "plan_engagement", "warn": "HITL disabled (P5 will hard-refuse)"})

        now = deps.clock()
        # The editable attack plan a human reviews before red executes (graph interrupts before
        # trigger_red when HITL is on). `instruction` is the ONLY directive that reaches Decepticon's
        # agents, so it is the primary editable field; scope/objective ride along for the operator.
        scope = state.get("scope") or {}
        plan = {
            "engagement_id": eng, "tenant_id": tenant,
            "objective": "Recon the in-scope assets, then attempt and validate exploitation of the "
                         "highest-value findings.",
            "instruction": state.get("instruction", ""),
            "in_scope": scope.get("in_scope", []),
            "sandbox_url": scope.get("sandbox_url"),
            "enforcement_mode": enforce, "hitl_enabled": hitl,
            "mode": state.get("mode", "on_demand"),
            "status": "proposed", "proposed_at": now,
        }
        rec = deps.evidence.append(
            engagement_id=eng, tenant_id=tenant, actor="coordinator",
            record_type="engagement.planned", ts=now,
            payload={"scope": scope, "budget": state.get("budget", {}),
                     "enforcement_mode": enforce, "hitl_enabled": hitl,
                     "mode": state.get("mode", "on_demand"), "plan": plan},
        )
        out: dict = {"status": "running", "window": {"t_start": now}, "plan": plan,
                     "version": state.get("version", 1), "evidence_refs": [rec.this_hash]}
        if errors:
            out["errors"] = errors
        return out

    return plan_engagement
