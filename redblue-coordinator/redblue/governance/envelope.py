"""The engine-agnostic action envelope + policy decision (plan 08 §1.1).

Every state-changing action (blue containment, red action, coordinator response) is normalized to an
ActionEnvelope and passed through PolicyEngine.evaluate() → PolicyDecision BEFORE dispatch. Tier is a
pure function of (kind, boundary, reversibility); confidence/risk can only RAISE it, never lower it.
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from ..contracts import Tier


class Decision(str, Enum):
    AUTO = "auto"
    HUMAN_APPROVAL = "human_approval"
    NEVER_AUTO_HUMAN = "never_auto_human"
    DENY = "deny"


class Boundary(str, Enum):
    NONE = "none"
    TENANT = "tenant"                # crosses into another / unknown tenant
    CONTROL_PLANE = "control_plane"


# reason codes (plan 08 §1.1)
TENANT_BOUNDARY = "TENANT_BOUNDARY"
CONTROL_PLANE = "CONTROL_PLANE"
LOW_CONFIDENCE = "LOW_CONFIDENCE"
HIGH_ENGINE_RISK = "HIGH_ENGINE_RISK"
HIGH_IMPACT = "HIGH_IMPACT"
MUTATING_QUERY = "MUTATING_QUERY"
NOT_TIME_BOXED = "NOT_TIME_BOXED"
TENANT_OVERRIDE = "TENANT_OVERRIDE"
FORCE_MANUAL = "FORCE_MANUAL"
LOW_BLAST = "LOW_BLAST"
POLICY_ERROR = "POLICY_ERROR"
ROE_REFUSED = "ROE_REFUSED"


class ActionEnvelope(BaseModel):
    action_id: str
    tenant_id: str
    engagement_id: str
    origin: str                                  # "vigil" | "decepticon" | "coordinator"
    kind: str                                    # ActionType value OR red action class
    target: dict[str, Any] = Field(default_factory=dict)   # {raw, resolved_asset_id?, ...}
    confidence: float | None = None           # Vigil summed-evidence score
    engine_risk: str | None = None            # Decepticon Decision.risk: low|medium|high
    reversible: bool = False
    ttl_seconds: int | None = None            # time-boxed AUTO (auto-expiry)
    query: str | None = None                  # for execute_spl_query mutating-check
    roe_decision: str | None = None           # "allow" | "refuse" (red)
    evidence_refs: list[str] = Field(default_factory=list)
    requested_by: str = "coordinator"


class PolicyDecision(BaseModel):
    action_id: str
    decision: Decision
    tier: Tier
    reason_code: str
    boundary: Boundary = Boundary.NONE
    required_approvers: int = 1
    expiry_at: float | None = None
    rationale: str | None = None
