"""redblue.scoring — attacked-vs-detected (plan 07 §4).

Correlation itself lives in contracts.correlation (the schema-level join); this package adds the
coordinator-side honesty layer (coverage oracle) and the pure engine/sensor → tuple extractors.
"""
from .coverage import StaticCoverageOracle, apply_coverage
from .extract import events_to_attacks, findings_to_detections

__all__ = [
    "StaticCoverageOracle", "apply_coverage",
    "events_to_attacks", "findings_to_detections",
]
