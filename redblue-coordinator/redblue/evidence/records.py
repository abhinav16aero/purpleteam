"""Evidence record kinds (plan 07 §2.3 / §6.2). The record MODEL + hashing live in contracts.governance."""
from __future__ import annotations

from ..contracts import EvidenceRecord  # re-export for callers

# The record_type vocabulary the loop emits (plan 05 §7.3 / 07 nodes).
ENGAGEMENT_PLANNED = "engagement.planned"
RED_LAUNCHED = "red.launched"
TELEMETRY_COLLECTED = "telemetry.collected"
SCORECARD_PRODUCED = "scorecard.produced"
ENGAGEMENT_COMPLETED = "engagement.completed"
NODE_FAILED = "node.failed"
DECISION = "decision"
RESPONSE = "response"

__all__ = [
    "DECISION",
    "ENGAGEMENT_COMPLETED",
    "ENGAGEMENT_PLANNED",
    "NODE_FAILED",
    "RED_LAUNCHED",
    "RESPONSE",
    "SCORECARD_PRODUCED",
    "TELEMETRY_COLLECTED",
    "EvidenceRecord",
]
