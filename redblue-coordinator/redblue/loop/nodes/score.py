"""Node 5 — score (plan 07 §2.3 / §4).

Correlate attacked-vs-detected, apply the coverage oracle (MISSED → SENSOR_BLIND where no sensor
exists), build the Scorecard from the scored (detected+missed) set, and stamp its evidence hash.
SENSOR_BLIND is excluded from the detection denominator and reported separately as coverage gaps.
"""
from __future__ import annotations

from ...contracts import MatchState, build_scorecard, correlate
from ...scoring import apply_coverage
from ..ports import Deps
from ..state import LoopState


def make_score(deps: Deps):
    async def score(state: LoopState) -> dict:
        eng, tenant = state["engagement_id"], state["tenant_id"]
        window = state.get("window", {})
        version = state.get("version", 1)

        corr = apply_coverage(correlate(state.get("attacks", []), state.get("detections", [])), deps.coverage)
        scored = [c for c in corr if c["state"] != MatchState.SENSOR_BLIND]
        blind = [c for c in corr if c["state"] == MatchState.SENSOR_BLIND]

        card = build_scorecard(engagement_id=eng, tenant_id=tenant, window=window,
                               correlations=scored, version=version)
        rec = deps.evidence.append(
            engagement_id=eng, tenant_id=tenant, actor="coordinator",
            record_type="scorecard.produced", payload=card.model_dump(), ts=deps.clock(),
            ref={"scorecard_id": card.scorecard_id},
        )
        card = card.model_copy(update={"evidence_refs": [rec.this_hash]})
        return {"scorecard": card.model_dump(), "status": "scoring",
                "coverage_gaps": [{"technique": c["technique"], "entity": c.get("entity")} for c in blind],
                "evidence_refs": [rec.this_hash]}

    return score
