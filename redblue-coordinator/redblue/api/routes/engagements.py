"""Engagement control + read (plan 07 §6.1).

P4 runs the loop INLINE within the create request (deterministic MVP); P7 moves to a background
task + SSE stream. On completion the scorecard + evidence chain are persisted to the store.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from ... import obs
from ...connectors import valid_engagement
from ...continuous import tenant_of
from ...contracts import Engagement, EngagementStatus, EvidenceRecord, verify_chain
from ..schemas import (
    CreateEngagementRequest,
    EngagementCreatedResponse,
    PlanPatchRequest,
    PlanRejectRequest,
)

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
        "simulate": req.simulate,                    # skip the live red run; score pre-seeded data
        "version": 1,
    }
    config = {"configurable": {"thread_id": eng_id}}
    # A live, human-gated run holds for plan review before red executes; simulate or hitl-off runs
    # straight through. The interrupt is applied per-run (only here), so no other graph consumer pauses.
    hitl = req.hitl_enabled and not req.simulate

    # On ANY node failure mark FAILED (never leave a stuck RUNNING row) and surface a clean 502.
    try:
        if hitl:
            final = await st.graph.ainvoke(loop_input, config, interrupt_before=["trigger_red"])
        else:
            final = await st.graph.ainvoke(loop_input, config)
    except Exception as e:
        st.store.save_evidence(st.deps.evidence.chain(eng_id))
        st.store.set_status(eng_id, "failed", ts=time.time())
        raise HTTPException(502, f"engagement loop failed: {e}") from e

    if hitl:
        # Paused before trigger_red — red does NOT run until POST …/plan/approve.
        st.store.save_evidence(st.deps.evidence.chain(eng_id))
        st.store.set_status(eng_id, "awaiting_plan_approval", ts=time.time())
        obs.record_engagement(req.mode, "awaiting_plan_approval")
        return EngagementCreatedResponse(engagement_id=eng_id, status="awaiting_plan_approval",
                                         plan=final.get("plan"))
    return _finalize(st, req.mode, eng_id, final)


def _finalize(st, mode: str, eng_id: str, final: dict) -> EngagementCreatedResponse:
    """Persist scorecard + evidence + status and record observability once the loop reaches END."""
    card = final.get("scorecard")
    if card:
        st.store.upsert_scorecard(card, ts=time.time())
    st.store.save_evidence(st.deps.evidence.chain(eng_id))
    st.store.set_status(eng_id, final.get("status", "completed"), ts=time.time())
    obs.record_engagement(mode, final.get("status", "completed"))
    obs.record_scorecard(card)
    obs.record_decisions(final.get("response_decisions"))
    obs.record_quarantined(final.get("quarantined"))
    return EngagementCreatedResponse(
        engagement_id=eng_id, status=final.get("status", "completed"),
        scorecard_id=(card or {}).get("scorecard_id"),
        detection_rate=(card or {}).get("detection_rate"),
    )


async def _plan_snapshot(st, engagement_id: str):
    """The checkpointed loop state (for the plan) + whether the engagement is awaiting plan approval.
    `awaiting` is driven by the stored status so approve/reject are idempotent (the paused graph
    checkpoint alone would still read as 'before trigger_red' after a reject)."""
    row = st.store.get_engagement(engagement_id)
    snap = await st.graph.aget_state({"configurable": {"thread_id": engagement_id}})
    values = (snap.values if snap else None) or {}
    awaiting = bool(row and row.get("status") == "awaiting_plan_approval")
    return row, values, awaiting


@router.get("/api/engagements/{engagement_id}/plan")
async def get_plan(engagement_id: str, request: Request) -> dict:
    """The attack plan a human is reviewing (HITL). `awaiting_approval` is true only while the run is
    paused before red executes."""
    st = request.app.state
    if st.store.get_engagement(engagement_id) is None:
        raise HTTPException(404, "engagement not found")
    _snap, values, awaiting = await _plan_snapshot(st, engagement_id)
    plan = values.get("plan")
    if not plan:
        raise HTTPException(404, "no plan recorded for this engagement")
    return {"engagement_id": engagement_id, "plan": plan, "awaiting_approval": awaiting}


@router.patch("/api/engagements/{engagement_id}/plan")
async def edit_plan(engagement_id: str, req: PlanPatchRequest, request: Request) -> dict:
    """Edit a paused plan before approving. `instruction` is what red actually runs, so edits to it (and
    to in_scope) are pushed into the checkpointed state the resumed run reads."""
    st = request.app.state
    config = {"configurable": {"thread_id": engagement_id}}
    _snap, values, awaiting = await _plan_snapshot(st, engagement_id)
    if not awaiting:
        raise HTTPException(409, "engagement is not awaiting plan approval")
    plan = dict(values.get("plan") or {})
    scope = dict(values.get("scope") or {})
    upd: dict = {}
    if req.instruction is not None:
        plan["instruction"] = req.instruction
        upd["instruction"] = req.instruction
    if req.objective is not None:
        plan["objective"] = req.objective
    if req.in_scope is not None:
        plan["in_scope"] = req.in_scope
        scope["in_scope"] = req.in_scope
        upd["scope"] = scope
    plan["status"] = "edited"
    plan["edited_by"] = "operator"
    upd["plan"] = plan
    st.deps.evidence.append(engagement_id=engagement_id, tenant_id=tenant_of(engagement_id),
                            actor="operator", record_type="plan.edited", ts=time.time(),
                            payload={"plan": plan})
    await st.graph.aupdate_state(config, upd)
    st.store.save_evidence(st.deps.evidence.chain(engagement_id))
    return {"engagement_id": engagement_id, "plan": plan}


@router.post("/api/engagements/{engagement_id}/plan/approve", response_model=EngagementCreatedResponse)
async def approve_plan(engagement_id: str, request: Request) -> EngagementCreatedResponse:
    """Approve the reviewed plan → resume the checkpointed run: red fires, telemetry settles, score."""
    st = request.app.state
    config = {"configurable": {"thread_id": engagement_id}}
    _row, values, awaiting = await _plan_snapshot(st, engagement_id)
    if not awaiting:
        raise HTTPException(409, "engagement is not awaiting plan approval")
    st.deps.evidence.append(engagement_id=engagement_id, tenant_id=tenant_of(engagement_id),
                            actor="operator", record_type="plan.approved", ts=time.time(),
                            payload={"plan": values.get("plan")})
    st.store.set_status(engagement_id, "running", ts=time.time())
    try:
        final = await st.graph.ainvoke(None, config)
    except Exception as e:
        st.store.save_evidence(st.deps.evidence.chain(engagement_id))
        st.store.set_status(engagement_id, "failed", ts=time.time())
        raise HTTPException(502, f"engagement loop failed: {e}") from e
    mode = (st.store.get_engagement(engagement_id) or {}).get("mode", "on_demand")
    return _finalize(st, mode, engagement_id, final)


@router.post("/api/engagements/{engagement_id}/plan/reject")
async def reject_plan(engagement_id: str, req: PlanRejectRequest, request: Request) -> dict:
    """Reject the plan → the run is cancelled (red never executes); recorded to the evidence chain."""
    st = request.app.state
    _snap, _values, awaiting = await _plan_snapshot(st, engagement_id)
    if not awaiting:
        raise HTTPException(409, "engagement is not awaiting plan approval")
    st.deps.evidence.append(engagement_id=engagement_id, tenant_id=tenant_of(engagement_id),
                            actor="operator", record_type="plan.rejected", ts=time.time(),
                            payload={"reason": req.reason})
    st.store.save_evidence(st.deps.evidence.chain(engagement_id))
    st.store.set_status(engagement_id, "rejected", ts=time.time())
    return {"engagement_id": engagement_id, "status": "rejected"}


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


@router.get("/api/engagements/{engagement_id}/evidence/bundle")
async def export_evidence_bundle(engagement_id: str, request: Request) -> JSONResponse:
    """Downloadable, self-verifying evidence bundle (plan 08 §5 / prompt §25): the full hash-chained
    records + the chain-verification result + a SHA-256 digest over the canonical records ("digest-
    sealed"). If `REDBLUE_EVIDENCE_SIGNING_KEY` is configured the digest is also HMAC-SHA256 signed
    (`signed: true`); otherwise the bundle is honestly marked unsigned but still tamper-evident via the
    digest + chain. Returned as a file attachment so the console can offer a real download."""
    st = request.app.state
    if st.store.get_engagement(engagement_id) is None:
        raise HTTPException(404, "engagement not found")
    records = st.store.get_evidence(engagement_id)
    tenant = tenant_of(engagement_id)
    chain = [EvidenceRecord(
        engagement_id=engagement_id, tenant_id=tenant, seq=r["seq"], ts=r["ts"], actor=r["actor"],
        record_type=r["record_type"], ref=r.get("ref") or {}, payload_hash=r["payload_hash"],
        prev_hash=r["prev_hash"], this_hash=r["this_hash"]) for r in records]
    verified = verify_chain(chain)

    canonical = json.dumps(records, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    key = os.getenv("REDBLUE_EVIDENCE_SIGNING_KEY")
    signature = hmac.new(key.encode(), digest.encode(), hashlib.sha256).hexdigest() if key else None

    bundle = {
        "bundle_version": 1,
        "engagement_id": engagement_id,
        "tenant_id": tenant,
        "exported_at": time.time(),
        "count": len(records),
        "verified": verified,
        "chain_head": records[-1]["this_hash"] if records else None,
        "digest_algo": "sha256",
        "bundle_digest": digest,
        "signed": bool(key),
        "signature_algo": "hmac-sha256" if key else None,
        "signature": signature,
        "records": records,
    }
    return JSONResponse(bundle, headers={
        "Content-Disposition": f'attachment; filename="evidence-{engagement_id}.json"'})
