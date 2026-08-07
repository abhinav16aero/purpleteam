"""Decepticon event stream — the blue-observable red timeline (plan 05 §5).

Mirrors `Decepticon/.../runtime/event_log.py` (`events.jsonl`, one EngagementEvent per line).
The coordinator tails this; `tool.call`/`finding.created` are the red-action timeline for MTTD.
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel


class EventType(str, Enum):
    """The 10 EventType values (verbatim from event_log.py:90-99)."""
    ENGAGEMENT_START = "engagement.start"
    ENGAGEMENT_END = "engagement.end"
    ENGAGEMENT_CHECKPOINT = "engagement.checkpoint"
    AGENT_TURN = "agent.turn"
    TOOL_CALL = "tool.call"
    TOOL_RESULT = "tool.result"
    LLM_CALL = "llm.call"
    LLM_RESPONSE = "llm.response"
    FINDING_CREATED = "finding.created"
    OPPLAN_UPDATE = "opplan.update"


class EngagementEvent(BaseModel):
    """One `events.jsonl` line. `type` kept as raw str for forward-compat (unknown types tolerated)."""
    ts: float                       # epoch seconds — the red-action clock for MTTD
    type: str
    agent: str | None = None     # emitting sub-agent; absent if unknown
    payload: dict[str, Any] = {}

    @property
    def is_finding(self) -> bool:
        return self.type == EventType.FINDING_CREATED.value

    @property
    def is_engagement_end(self) -> bool:
        return self.type == EventType.ENGAGEMENT_END.value
