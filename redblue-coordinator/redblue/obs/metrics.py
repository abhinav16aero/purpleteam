"""Coordinator observability — Prometheus metrics (plan 09 §2). Scraped on :8902 / exposed at /metrics.

The SLIs the RedBlue posture dashboard renders: detection-rate, MTTD/MTTR, autonomy-actions-by-tier,
and the sovereignty guardrail `redblue_external_egress_bytes_total` (must stay 0). A dedicated
CollectorRegistry keeps metrics test-isolated (not the global default registry).
"""
from __future__ import annotations

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

REGISTRY = CollectorRegistry()

engagements_total = Counter(
    "redblue_engagements_total", "Engagements run", ["mode", "status"], registry=REGISTRY)
engagement_active = Gauge(
    "redblue_engagement_active", "Engagements currently running", registry=REGISTRY)
attacks_total = Counter(
    "redblue_attacks_total", "Attack instances (red ground truth)", registry=REGISTRY)
detected_total = Counter(
    "redblue_detected_total", "Detected attack instances (blue)", registry=REGISTRY)
mttd_seconds = Histogram(
    "redblue_mttd_seconds", "Mean time to detect (per detected instance)",
    buckets=(1, 5, 15, 30, 60, 120, 300, 900, 3600), registry=REGISTRY)
actions_total = Counter(
    "redblue_actions_total", "Response actions by tiered-autonomy tier", ["tier"], registry=REGISTRY)
quarantined_total = Counter(
    "redblue_quarantined_total", "Detections quarantined by shield/verification", ["reason"], registry=REGISTRY)
external_egress_bytes_total = Counter(
    "redblue_external_egress_bytes_total",
    "Bytes to non-allowlisted external hosts — the sovereignty SLI, MUST stay 0", registry=REGISTRY)


def record_engagement(mode: str, status: str) -> None:
    engagements_total.labels(mode=mode or "on_demand", status=status or "completed").inc()


def record_scorecard(sc: dict | None) -> None:
    if not sc:
        return
    pf = sc.get("per_finding", []) or []
    attacks_total.inc(len(pf))
    for f in pf:
        if f.get("detected"):
            detected_total.inc()
        m = f.get("mttd_seconds")
        if m is not None and m >= 0:
            mttd_seconds.observe(m)


def record_decisions(decisions: list[dict] | None) -> None:
    for d in decisions or []:
        actions_total.labels(tier=str(d.get("tier", "unknown"))).inc()


def record_quarantined(quarantined: list[dict] | None) -> None:
    for q in quarantined or []:
        quarantined_total.labels(reason=str(q.get("reason", "unknown"))).inc()


def render() -> tuple[bytes, str]:
    """(payload, content_type) for the /metrics endpoint."""
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
