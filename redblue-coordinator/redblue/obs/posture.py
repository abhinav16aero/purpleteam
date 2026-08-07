"""Posture aggregate (plan 09 §1.4) — fold the latest scorecards into one org/tenant posture view.

Pure function → the same numbers feed both the in-console PostureScreen and the Grafana dashboard.
Detection-rate is instance-weighted (consistent with build_scorecard, post-review).
"""
from __future__ import annotations

import statistics
from typing import Any


def _pctile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    return s[min(len(s) - 1, int(round(q * (len(s) - 1))))]


def build_posture(scorecards: list[dict]) -> dict[str, Any]:
    total_attacked = total_detected = 0
    attacked_tech: set[str] = set()
    detected_tech: set[str] = set()
    mttds: list[float] = []
    gaps: list[dict] = []

    for sc in scorecards:
        for f in sc.get("per_finding", []) or []:
            total_attacked += 1
            if f.get("detected"):
                total_detected += 1
                m = f.get("mttd_seconds")
                if m is not None and m >= 0:
                    mttds.append(m)
        attacked_tech |= set(sc.get("attacked_techniques", []) or [])
        detected_tech |= set(sc.get("detected_techniques", []) or [])
        gaps.extend(sc.get("gaps", []) or [])

    return {
        "engagements": len(scorecards),
        "totals": {"attacked": total_attacked, "detected": total_detected},
        "detection_rate": (total_detected / total_attacked) if total_attacked else None,
        "attacked_techniques": sorted(attacked_tech),
        "detected_techniques": sorted(detected_tech),
        "attack_coverage": {"attacked": len(attacked_tech), "detected": len(detected_tech)},
        "mttd": {
            "mean": statistics.fmean(mttds) if mttds else None,
            "median": statistics.median(mttds) if mttds else None,
            "p90": _pctile(mttds, 0.9),
        },
        "gap_count": len(gaps),
        "top_gaps": gaps[:20],
    }
