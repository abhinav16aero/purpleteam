"""API request/response schemas (plan 07 §6.1)."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class CreateEngagementRequest(BaseModel):
    tenant_id: str
    engagement_id: str | None = None                 # generated if omitted (00 §7 slug)
    mode: Literal["on_demand", "continuous"] = "on_demand"
    scope: dict[str, Any] = Field(default_factory=dict)
    target: dict[str, Any] = Field(default_factory=dict)
    instruction: str | None = None
    enforcement_mode: str = "enforce"
    hitl_enabled: bool = True
    roe_ref: str | None = None


class EngagementCreatedResponse(BaseModel):
    engagement_id: str
    status: str
    scorecard_id: str | None = None
    detection_rate: float | None = None
