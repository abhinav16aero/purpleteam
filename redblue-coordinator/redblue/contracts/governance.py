"""Governance records — tiered-autonomy decision + hash-chained evidence (plan 05 §7).

Data shapes only; the policy engine (08) produces TieredAutonomyDecision, the WORM store (08)
produces the EvidenceRecord chain. `verify_chain` is the tamper check.
"""
from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

GENESIS_HASH = "0" * 64


class ActionType(str, Enum):
    """Vigil's 11 ActionType values (verbatim from approval_service.py:38-48)."""
    ISOLATE_HOST = "isolate_host"
    BLOCK_IP = "block_ip"
    BLOCK_DOMAIN = "block_domain"
    QUARANTINE_FILE = "quarantine_file"
    DISABLE_USER = "disable_user"
    EXECUTE_SPL_QUERY = "execute_spl_query"
    WORKFLOW_PHASE = "workflow_phase"
    WAF_BLOCK = "waf_block"
    GATEWAY_BLOCK = "gateway_block"
    ACCESS_REVOKE = "access_revoke"
    CUSTOM = "custom"


class Tier(str, Enum):
    """The tiered-autonomy model (redblue-strategic-moat)."""
    AUTO = "auto"
    HUMAN = "human"
    NEVER = "never"


class ActionStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"
    FAILED = "failed"
    BLOCKED = "blocked"


class TieredAutonomyDecision(BaseModel):
    decision_id: str
    ts: float
    engagement_id: str
    tenant_id: str
    actor: str                       # red | vigil | coordinator | human
    subject: dict[str, Any]          # {kind, action_type, target}
    tier: Tier
    inputs: dict[str, Any] = Field(default_factory=dict)   # confidence, tool_tier, roe_decision, boundaries
    outcome: str = "pending"         # allowed | pending | denied
    approval_action_id: str | None = None
    approver: str | None = None
    rationale: str | None = None
    evidence_ref: str | None = None


def payload_hash(payload: dict) -> str:
    """sha256 of the canonical (sorted-key, tight) JSON payload."""
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(blob.encode()).hexdigest()


def compute_this_hash(prev_hash: str, ph: str, seq: int, ts: float, record_type: str) -> str:
    # delimited preimage — variable-width seq/ts must not be ambiguous (e.g. seq=1,ts=12 vs seq=11,ts=2)
    return hashlib.sha256(f"{prev_hash}|{ph}|{seq}|{ts}|{record_type}".encode()).hexdigest()


class EvidenceRecord(BaseModel):
    """Append-only, tamper-evident chain (plan 05 §7.3). `this_hash` links to next `prev_hash`."""
    seq: int
    ts: float
    engagement_id: str
    tenant_id: str
    actor: str
    record_type: str                 # red_action|sensor_alert|blue_finding|detection|decision|response|scorecard|...
    ref: dict[str, Any] = Field(default_factory=dict)
    payload_hash: str
    prev_hash: str
    this_hash: str

    @classmethod
    def create(
        cls, *, seq: int, ts: float, engagement_id: str, tenant_id: str, actor: str,
        record_type: str, payload: dict, prev_hash: str, ref: dict | None = None,
    ) -> EvidenceRecord:
        ph = payload_hash(payload)
        return cls(
            seq=seq, ts=ts, engagement_id=engagement_id, tenant_id=tenant_id, actor=actor,
            record_type=record_type, ref=ref or {}, payload_hash=ph, prev_hash=prev_hash,
            this_hash=compute_this_hash(prev_hash, ph, seq, ts, record_type),
        )


def verify_chain(records: list[EvidenceRecord]) -> bool:
    """True iff the chain is unbroken and untampered (prev links + recomputed hashes)."""
    prev = GENESIS_HASH
    for r in records:
        if r.prev_hash != prev:
            return False
        if r.this_hash != compute_this_hash(r.prev_hash, r.payload_hash, r.seq, r.ts, r.record_type):
            return False
        prev = r.this_hash
    return True
