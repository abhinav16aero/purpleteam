"""Node 7 — report_evidence (plan 07 §2.3).

Seal the engagement: write the terminal evidence record and mark the run completed. Every scorecard
number already carries an evidence_ref (score node); this record closes the chain for the engagement.
"""
from __future__ import annotations

from ..ports import Deps
from ..state import LoopState


def make_report_evidence(deps: Deps):
    async def report_evidence(state: LoopState) -> dict:
        eng, tenant = state["engagement_id"], state["tenant_id"]
        card = state.get("scorecard", {})
        rec = deps.evidence.append(
            engagement_id=eng, tenant_id=tenant, actor="coordinator",
            record_type="engagement.completed", ts=deps.clock(),
            payload={"scorecard_id": card.get("scorecard_id"),
                     "detection_rate": card.get("detection_rate"),
                     "attacked": len(card.get("attacked_techniques", [])),
                     "detected": len(card.get("detected_techniques", [])),
                     "coverage_gaps": len(state.get("coverage_gaps", [])),
                     "chain_len": len(deps.evidence.chain(eng)) + 1},
            ref={"scorecard_id": card.get("scorecard_id")},
        )
        return {"status": "completed", "evidence_refs": [rec.this_hash]}

    return report_evidence
