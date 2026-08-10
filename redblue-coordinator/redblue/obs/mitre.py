"""ATT&CK roll-up (prompt §21) — fold every engagement's per-technique scores into one org/tenant view.

Pure function (mirrors obs.posture.build_posture) so the same numbers can feed the console's MITRE
matrix and any dashboard. Instance-weighted, consistent with build_scorecard: detection_rate is
detected/attacked summed across engagements, and MTTD is a detected-count-weighted mean of each
engagement's per-technique MTTD (the only mttd granularity a stored scorecard carries).
"""
from __future__ import annotations

from typing import Any


def build_mitre_rollup(scorecards: list[dict]) -> dict[str, Any]:
    techs: dict[str, dict] = {}
    for sc in scorecards:
        for t in sc.get("per_technique", []) or []:
            tid = t.get("technique_id")
            if not tid:
                continue
            agg = techs.setdefault(tid, {
                "technique_id": tid, "attacked": 0, "detected": 0, "missed": 0,
                "engagements": 0, "_mttd_sum": 0.0, "_mttd_w": 0,
            })
            a, d, m = int(t.get("attacked") or 0), int(t.get("detected") or 0), int(t.get("missed") or 0)
            agg["attacked"] += a
            agg["detected"] += d
            agg["missed"] += m
            agg["engagements"] += 1
            mt = t.get("mttd_seconds")
            if mt is not None and d > 0:
                agg["_mttd_sum"] += float(mt) * d
                agg["_mttd_w"] += d

    techniques: list[dict] = []
    for tid in sorted(techs):
        agg = techs[tid]
        techniques.append({
            "technique_id": tid,
            "attacked": agg["attacked"],
            "detected": agg["detected"],
            "missed": agg["missed"],
            "detection_rate": (agg["detected"] / agg["attacked"]) if agg["attacked"] else None,
            "mttd_seconds": (agg["_mttd_sum"] / agg["_mttd_w"]) if agg["_mttd_w"] else None,
            "engagements": agg["engagements"],
        })

    total_attacked = sum(t["attacked"] for t in techniques)
    total_detected = sum(t["detected"] for t in techniques)
    return {
        "scorecards": len(scorecards),
        "technique_count": len(techniques),
        "totals": {"attacked": total_attacked, "detected": total_detected},
        "detection_rate": (total_detected / total_attacked) if total_attacked else None,
        "techniques": techniques,
    }
