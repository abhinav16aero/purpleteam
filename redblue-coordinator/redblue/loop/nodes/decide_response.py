"""Node 6 — decide_response (plan 08 §1, §2).

If a PolicyEngine is injected (P5+): plan candidate responses from the scorecard, run EACH through
the authoritative `PolicyEngine.evaluate()`, write a policy_decision evidence record per action, and
split them — AUTO (would execute via Vigil; execution is the live slice) vs HUMAN/NEVER (queued in
pending_actions for the approvals surface). If no PolicyEngine (P4): report-only no-op.

The tier is decided by deterministic code; the LLM never grades blast radius (plan 08 §1.1).
"""
from __future__ import annotations

from ...governance.envelope import Decision
from ...governance.planner import default_response_planner
from ..ports import Deps
from ..state import LoopState


def make_decide_response(deps: Deps):
    async def decide_response(state: LoopState) -> dict:
        if deps.policy_engine is None:
            return {"pending_actions": []}                  # P4 report-only

        eng, tenant = state["engagement_id"], state["tenant_id"]
        planner = deps.response_planner or default_response_planner
        envelopes = planner(dict(state))

        pending: list[dict] = []
        decisions: list[dict] = []
        refs: list[str] = []
        for env in envelopes:
            dec = deps.policy_engine.evaluate(env)
            rec = deps.evidence.append(
                engagement_id=eng, tenant_id=tenant, actor="coordinator",
                record_type="policy_decision", ts=deps.clock(),
                payload={"envelope": env.model_dump(), "decision": dec.model_dump()},
                ref={"action_id": env.action_id},
            )
            refs.append(rec.this_hash)
            row = {"action_id": env.action_id, "kind": env.kind, "target": env.target,
                   "decision": dec.decision.value, "tier": dec.tier.value,
                   "reason": dec.reason_code, "required_approvers": dec.required_approvers}
            decisions.append(row)
            # AUTO executes; HUMAN/NEVER await human approval; DENY is TERMINAL (dropped, not queued).
            if dec.decision in (Decision.HUMAN_APPROVAL, Decision.NEVER_AUTO_HUMAN):
                pending.append(row)

        return {"pending_actions": pending, "response_decisions": decisions, "evidence_refs": refs}

    return decide_response
