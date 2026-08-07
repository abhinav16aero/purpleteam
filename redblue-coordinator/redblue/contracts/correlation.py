"""Correlation — red action ↔ blue detection join (plan 05 §8).

The coordinator reconstructs the join from data carried inside findings (Vigil has no
engagement/technique columns). A blue finding DETECTS a red action iff: same engagement,
technique matches, target entity matches, within the time window. `sensor_blind` (no sensor
covers the entity/technique) is decided by the coverage oracle in scoring/07 — here we produce
detected/missed on the join.
"""
from __future__ import annotations

from enum import Enum

CORRELATION_WINDOW_S = 900          # ±15 min default


class MatchState(str, Enum):
    DETECTED = "detected"
    MISSED = "missed"
    SENSOR_BLIND = "sensor_blind"   # set by the coverage oracle (07), not here
    FALSE_POSITIVE = "false_positive"


def _techs(d: dict) -> set[str]:
    if d.get("techniques"):
        return set(d["techniques"])
    return {d["technique"]} if d.get("technique") else set()


def _ents(d: dict) -> set[str]:
    if d.get("entities"):
        return set(str(e) for e in d["entities"])
    return {str(d["entity"])} if d.get("entity") else set()


def correlate(
    attacks: list[dict], detections: list[dict], window: float = CORRELATION_WINDOW_S
) -> list[dict]:
    """One match record per attack instance.

    attacks:    [{technique, entity, ts, red_action_id?}]  (ground truth: KG/events.jsonl)
    detections: [{technique|techniques, entity|entities, ts, finding_id?}]  (sensor-origin blue findings)
    """
    results: list[dict] = []
    for a in attacks:
        a_tech, a_ent, a_ts = a["technique"], str(a["entity"]), a["ts"]
        best: dict | None = None
        for d in detections:
            # ONE-SIDED window: a detection must occur AT or AFTER the attack (it cannot causally
            # detect a later attack). Guarantees mttd_seconds >= 0. Pick the earliest match.
            delta = d["ts"] - a_ts
            if a_tech in _techs(d) and a_ent in _ents(d) and 0 <= delta <= window:
                if best is None or delta < (best["ts"] - a_ts):
                    best = d
        if best is not None:
            results.append({
                "technique": a_tech, "entity": a_ent, "state": MatchState.DETECTED,
                "red_ts": a_ts, "blue_ts": best["ts"], "mttd_seconds": best["ts"] - a_ts,
                "finding_id": best.get("finding_id"), "red_action_id": a.get("red_action_id"),
            })
        else:
            results.append({
                "technique": a_tech, "entity": a_ent, "state": MatchState.MISSED,
                "red_ts": a_ts, "red_action_id": a.get("red_action_id"),
            })
    return results
