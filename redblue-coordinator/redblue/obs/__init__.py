"""redblue.obs — coordinator observability (plan 09 §2): Prometheus metrics + the posture aggregate."""
from .metrics import (
    record_decisions,
    record_engagement,
    record_quarantined,
    record_scorecard,
    render,
)

__all__ = [
    "record_decisions",
    "record_engagement",
    "record_quarantined",
    "record_scorecard",
    "render",
]
