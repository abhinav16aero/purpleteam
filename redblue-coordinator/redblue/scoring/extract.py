"""Pure extractors: engine/sensor rows → the (technique, entity, ts) tuples the correlator joins on.

Kept pure + free of I/O so they unit-test without a live engine (the P4 build is not hardware-bound).
  * events_to_attacks   — Decepticon events.jsonl `finding.created` → attack ground-truth (the red clock)
  * findings_to_detections — Vigil canonical findings → detection instances (the blue clock)
Correlation keys per plan 05 §8: engagement (scoped upstream) + technique-ID + entity + timestamp window.
"""
from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from ..contracts import TECHNIQUE_RE, EngagementEvent, EventType


def _epoch(ts: Any) -> float:
    if isinstance(ts, (int, float)):
        return float(ts)
    if isinstance(ts, str) and ts:
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass
    return datetime.now(UTC).timestamp()


def _valid_techs(values: Iterable[Any]) -> list[str]:
    return [v for v in values if isinstance(v, str) and TECHNIQUE_RE.match(v)]


def events_to_attacks(events: Iterable[EngagementEvent]) -> list[dict]:
    """`finding.created` events → [{technique, entity, ts, red_action_id}] (one per technique×event)."""
    out: list[dict] = []
    for e in events:
        if e.type != EventType.FINDING_CREATED.value:
            continue
        p = e.payload or {}
        techs = _valid_techs(p.get("mitre_techniques") or p.get("techniques")
                             or ([p["technique"]] if p.get("technique") else []))
        target = (p.get("target") or p.get("target_ip") or p.get("affected_target")
                  or p.get("dst_ip") or "")
        rid = p.get("finding_id") or p.get("id")
        for t in techs:
            out.append({"technique": t, "entity": str(target), "ts": float(e.ts), "red_action_id": rid})
    return out


def findings_to_detections(findings: Iterable[dict], *, exclude_data_sources: Iterable[str] = ()) -> list[dict]:
    """Vigil findings → [{technique, entity, ts, finding_id}].

    `exclude_data_sources` drops red-origin findings (e.g. "decepticon") from the *detection*
    numerator so the score reflects sensor-driven detection, not our own ingest (plan 07 §3.2 honesty rule).
    """
    excluded = set(exclude_data_sources)
    out: list[dict] = []
    for f in findings:
        if f.get("data_source") in excluded:
            continue
        mp = f.get("mitre_predictions") or {}
        ec = f.get("entity_context") or {}
        entity = ec.get("dst_ip") or ec.get("src_ip") or ec.get("hostname") or ec.get("affected_target") or ""
        ts = _epoch(f.get("timestamp"))
        fid = f.get("finding_id")
        text = f.get("description") or ""                  # untrusted text — scanned by the shield (§6)
        for t in _valid_techs(mp.keys()):
            out.append({"technique": t, "entity": str(entity), "ts": ts, "finding_id": fid,
                        "text": text, "evidence_refs": [fid] if fid else []})
    return out
