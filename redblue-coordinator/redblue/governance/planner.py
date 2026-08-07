"""Default response planner (plan 08 §1, wired into decide_response).

Turns scored detections into candidate response ActionEnvelopes for the PolicyEngine to tier. MVP:
per detected attack, propose (a) a time-boxed `block_ip` on the attacker (AUTO-eligible) and (b) an
`isolate_host` on the popped target (HUMAN by default). The point is to exercise the governance
decision — actual execution via Vigil is the live slice.
"""
from __future__ import annotations

from ..contracts import ActionType
from .envelope import ActionEnvelope


def default_response_planner(state: dict) -> list[ActionEnvelope]:
    eng = state["engagement_id"]
    tenant = state["tenant_id"]
    card = state.get("scorecard", {})
    out: list[ActionEnvelope] = []
    for i, pf in enumerate(card.get("per_finding", [])):
        if not pf.get("detected"):
            continue                                        # respond to confirmed detections only
        target = pf.get("entity")
        if not target:
            continue
        rid = pf.get("red_action_id") or f"{i}"
        # (a) time-boxed IP block — AUTO-eligible (reversible + auto-expiry)
        out.append(ActionEnvelope(
            action_id=f"act-{eng}-{rid}-blockip", tenant_id=tenant, engagement_id=eng,
            origin="coordinator", kind=ActionType.BLOCK_IP.value,
            target={"raw": target}, reversible=True, ttl_seconds=3600,
            evidence_refs=[pf["blue_finding_id"]] if pf.get("blue_finding_id") else [],
        ))
        # (b) isolate the popped host — HIGH impact (HUMAN by default; NEVER if boundary)
        out.append(ActionEnvelope(
            action_id=f"act-{eng}-{rid}-isolate", tenant_id=tenant, engagement_id=eng,
            origin="coordinator", kind=ActionType.ISOLATE_HOST.value,
            target={"raw": target}, reversible=False,
            evidence_refs=[pf["blue_finding_id"]] if pf.get("blue_finding_id") else [],
        ))
    return out
