"""Engagement control + read (plan 07 §6.1).

P4 runs the loop INLINE within the create request (deterministic MVP); P7 moves to a background
task + SSE stream. On completion the scorecard + evidence chain are persisted to the store.
"""
from __future__ import annotations

import secrets
import time
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request

from ... import obs
from ...connectors import valid_engagement
from ...continuous import tenant_of
from ...contracts import Engagement, EngagementStatus, EvidenceRecord, verify_chain
from ..schemas import CreateEngagementRequest, EngagementCreatedResponse

router = APIRouter()


def _mint_slug(tenant_id: str) -> str:
    day = datetime.now(UTC).strftime("%Y%m%d")
    return f"eng-{tenant_id}-{day}-{secrets.token_hex(2)}"


def _default_instruction(scope: dict | None) -> str:
    """A red directive synthesised from scope.in_scope when the caller gives no instruction.

    Decepticon's red agents take their target only from the prose instruction, so this turns a
    structured `in_scope` list into an explicit, authorised task naming the hosts (e.g. range-dvwa).
    """
    targets = [str(t) for t in ((scope or {}).get("in_scope") or []) if t]
    if targets:
        return (
            f"Recon and exploit the in-scope target(s): {', '.join(targets)}. These are authorised "
            "and in scope. Start with nmap service discovery, then probe web endpoints for "
            "injection/auth flaws, and validate each finding with a concrete proof."
        )
    return (
        "Run the scoped engagement per the OPPLAN: recon the authorised in-scope assets, then attempt "
        "exploitation of the highest-value findings and validate each."
    )


@router.post("/api/engagements", response_model=EngagementCreatedResponse)
async def create_engagement(req: CreateEngagementRequest, request: Request) -> EngagementCreatedResponse:
    st = request.app.state
    eng_id = req.engagement_id or _mint_slug(req.tenant_id)
    if not valid_engagement(eng_id):
        raise HTTPException(400, f"invalid engagement slug {eng_id!r} (fails Decepticon regex)")
    # kill switch (plan 08 §5) — refuse cleanly before doing any work.
    if getattr(st, "killswitch", None) is not None and st.killswitch.is_halted(req.tenant_id):
        raise HTTPException(409, f"kill switch active for tenant {req.tenant_id!r} — engagement refused")
    now = time.time()

    st.store.upsert_engagement(
        Engagement(engagement_id=eng_id, tenant_id=req.tenant_id, scope=req.scope, target=req.target,
                   roe_ref=req.roe_ref, enforcement_mode=req.enforcement_mode,
                   status=EngagementStatus.RUNNING, decepticon={"thread_id": eng_id}),
        mode=req.mode, ts=now,
    )

    loop_input = {
        "engagement_id": eng_id, "tenant_id": req.tenant_id, "mode": req.mode,
        "scope": req.scope, "enforcement_mode": req.enforcement_mode,
        "hitl_enabled": req.hitl_enabled,
        # The natural-language instruction is the ONLY target directive that reaches Decepticon's red
        # agents (no structured target field does), so an empty instruction = red with no task. When
        # the caller gives none, synthesize one from scope.in_scope so a structured scope still drives
        # the attack (name the in-scope hosts, e.g. "range-dvwa").
        "instruction": req.instruction or _default_instruction(req.scope),
        "version": 1,
    }
    # Run the loop; on ANY node failure, mark the engagement FAILED (never leave it stuck RUNNING)
    # and surface a clean 502 — don't leak a raw 500 or a permanent "active" row (plan 07 R-review).
    try:
        final = await st.graph.ainvoke(loop_input, {"configurable": {"thread_id": eng_id}})
    except Exception as e:
        st.store.save_evidence(st.deps.evidence.chain(eng_id))
        st.store.set_status(eng_id, "failed", ts=time.time())
        raise HTTPException(502, f"engagement loop failed: {e}") from e

    card = final.get("scorecard")
    if card:
        st.store.upsert_scorecard(card, ts=now)
    st.store.save_evidence(st.deps.evidence.chain(eng_id))
    st.store.set_status(eng_id, final.get("status", "completed"), ts=time.time())

    # observability (plan 09 §2)
    obs.record_engagement(req.mode, final.get("status", "completed"))
    obs.record_scorecard(card)
    obs.record_decisions(final.get("response_decisions"))
    obs.record_quarantined(final.get("quarantined"))

    return EngagementCreatedResponse(
        engagement_id=eng_id, status=final.get("status", "completed"),
        scorecard_id=(card or {}).get("scorecard_id"),
        detection_rate=(card or {}).get("detection_rate"),
    )


@router.get("/api/engagements")
async def list_engagements(request: Request, tenant_id: str | None = None,
                           status: str | None = None) -> list[dict]:
    return request.app.state.store.list_engagements(tenant_id=tenant_id, status=status)


@router.get("/api/engagements/{engagement_id}")
async def get_engagement(engagement_id: str, request: Request) -> dict:
    row = request.app.state.store.get_engagement(engagement_id)
    if not row:
        raise HTTPException(404, "engagement not found")
    return row


@router.get("/api/engagements/{engagement_id}/scorecard")
async def get_scorecard(engagement_id: str, request: Request, version: int | None = None) -> dict:
    card = request.app.state.store.get_scorecard(engagement_id, version=version)
    if not card:
        raise HTTPException(404, "scorecard not found")
    return card


@router.get("/api/engagements/{engagement_id}/evidence")
async def get_evidence(engagement_id: str, request: Request, verify: bool = False) -> dict:
    st = request.app.state
    if st.store.get_engagement(engagement_id) is None:
        raise HTTPException(404, "engagement not found")
    records = st.store.get_evidence(engagement_id)
    out: dict = {"engagement_id": engagement_id, "records": records, "count": len(records)}
    if verify:
        # verify the PERSISTED chain (reconstructed from the DB), so it holds across restarts and for
        # engagements not run in this process — not the volatile in-memory EvidenceStore.
        chain = [EvidenceRecord(
            engagement_id=engagement_id, tenant_id=tenant_of(engagement_id), seq=r["seq"], ts=r["ts"],
            actor=r["actor"], record_type=r["record_type"], ref=r.get("ref") or {},
            payload_hash=r["payload_hash"], prev_hash=r["prev_hash"], this_hash=r["this_hash"],
        ) for r in records]
        out["verified"] = verify_chain(chain)
    return out
