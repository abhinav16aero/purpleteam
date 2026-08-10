"""Pure extractors: engine/sensor rows → the (technique, entity, ts) tuples the correlator joins on.

Kept pure + free of I/O so they unit-test without a live engine (the P4 build is not hardware-bound).
  * events_to_attacks   — Decepticon events.jsonl `finding.created` → attack ground-truth (the red clock)
  * findings_to_detections — Vigil canonical findings → detection instances (the blue clock)
Correlation keys per plan 05 §8: engagement (scoped upstream) + technique-ID + entity + timestamp window.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from ..contracts import TECHNIQUE_RE, EngagementEvent, EventType

# non-anchored scan (TECHNIQUE_RE is `^…$`) so we can pull an embedded "T1190" out of a KG label/key.
_TECH_SCAN = re.compile(r"T\d{4}(?:\.\d{3})?")


def _epoch(ts: Any) -> float:
    if isinstance(ts, bool):                       # bool is an int subclass — never a timestamp
        return datetime.now(UTC).timestamp()
    if isinstance(ts, (int, float)):
        return float(ts)
    if isinstance(ts, str) and ts:
        try:
            return datetime.fromisoformat(ts).timestamp()   # py3.11+ parses a trailing 'Z'
        except ValueError:
            pass
    if hasattr(ts, "to_native"):                   # neo4j.time.DateTime → native datetime
        try:
            return ts.to_native().timestamp()
        except (ValueError, TypeError, AttributeError):
            pass
    if hasattr(ts, "timestamp") and callable(ts.timestamp):  # datetime and friends
        try:
            return float(ts.timestamp())
        except (ValueError, TypeError, OSError):
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


_TECH_KEYS = ("mitre_techniques", "techniques", "technique", "mitre", "mitre_attack",
              "attack_technique", "attack_techniques", "ttp", "ttps")
_TARGET_KEYS = ("target", "target_ip", "affected_target", "dst_ip", "host", "hostname", "ip", "asset")
_TS_KEYS = ("ts", "timestamp", "created_at", "createdAt", "first_seen", "firstSeen",
            "detected_at", "observed_at", "time", "when")
_ID_KEYS = ("finding_id", "key", "id", "uuid", "name")


def _first_str(props: dict, keys: tuple[str, ...]) -> str | None:
    for k in keys:
        v = props.get(k)
        if isinstance(v, str) and v:
            return v
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return str(v)
    return None


def _techniques_from_props(props: dict) -> list[str]:
    """Every canonical MITRE technique ID reachable in a Finding's properties (schema-defensive)."""
    found: list[str] = []
    for k in _TECH_KEYS:                            # 1) prioritized technique-bearing keys
        v = props.get(k)
        for item in (v if isinstance(v, (list, tuple)) else [v]):
            if isinstance(item, str):
                found += _TECH_SCAN.findall(item)
    if not found:                                  # 2) fallback: any string value (label/key/name)
        for v in props.values():
            if isinstance(v, str):
                found += _TECH_SCAN.findall(v)
    seen: set[str] = set()
    out: list[str] = []
    for t in found:
        if TECHNIQUE_RE.match(t) and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _ts_from_props(props: dict, default_ts: float) -> float:
    for k in _TS_KEYS:
        if props.get(k) is not None:
            return _epoch(props[k])
    return float(default_ts)


def kg_attacks(rows: Iterable[dict], *, default_ts: float) -> list[dict]:
    """Decepticon KG Finding rows (`{finding: properties(f), hosts: [...]}`) → attack tuples.

    The KG — not events.jsonl — is where Decepticon records the MITRE technique + target (the disk
    `finding.created` payload is only `{"tool": ...}`, plan 05 §5). Schema-defensive so it survives
    Finding-node variation: technique from whichever property carries it, entity from a reachable
    Host (preferred) or a target field, timestamp from a time-ish property — falling back to
    `default_ts` (the engagement-window start) so MTTD stays computable when nodes carry no time.
    Returns `[{technique, entity, ts, red_action_id}]`, one row per technique × finding.
    """
    out: list[dict] = []
    for row in rows:
        props = row.get("finding") if isinstance(row, dict) else None
        if not isinstance(props, dict):
            continue
        techs = _techniques_from_props(props)
        if not techs:
            continue
        hosts = [h for h in (row.get("hosts") or []) if isinstance(h, str) and h]
        entity = (hosts[0] if hosts else _first_str(props, _TARGET_KEYS)) or ""
        ts = _ts_from_props(props, default_ts)
        rid = _first_str(props, _ID_KEYS)
        for t in techs:
            out.append({"technique": t, "entity": str(entity), "ts": ts, "red_action_id": rid})
    return out


def attack_graph(rows: Iterable[dict], *, detected_techniques: Iterable[str] = ()) -> dict:
    """Decepticon KG Finding rows → a force-graph `{nodes, edges}` for the console.

    Nodes: `host` (what red reached), `finding` (colored by whether any of its techniques was
    detected), `technique` (MITRE T-id). Edges: host→finding (REACHES), finding→technique (USES).
    Same schema-defensive extraction as `kg_attacks`; `detected_techniques` (from the scorecard)
    drives the detected/missed coloring so the graph reads as a purple-team picture.
    """
    det = {t for t in detected_techniques if isinstance(t, str)}
    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    def add(node_id: str, kind: str, **extra: object) -> None:
        if node_id not in nodes:
            nodes[node_id] = {"id": node_id, "kind": kind, **extra}

    for row in rows:
        props = row.get("finding") if isinstance(row, dict) else None
        if not isinstance(props, dict):
            continue
        techs = _techniques_from_props(props)
        fid = _first_str(props, _ID_KEYS) or f"finding-{len(nodes)}"
        label = props.get("label") or props.get("name") or fid
        f_detected = any(t in det for t in techs)
        add(fid, "finding", label=str(label)[:90], tool=props.get("tool"),
            severity=props.get("severity"), techniques=techs, detected=f_detected)
        hosts = [h for h in (row.get("hosts") or []) if isinstance(h, str) and h]
        if not hosts:
            tgt = _first_str(props, _TARGET_KEYS)
            hosts = [tgt] if tgt else []
        for h in hosts:
            add(h, "host", label=h)
            edges.append({"source": h, "target": fid, "rel": "REACHES"})
        for t in techs:
            add(f"tech:{t}", "technique", label=t, detected=(t in det))
            edges.append({"source": fid, "target": f"tech:{t}", "rel": "USES"})
    return {"nodes": list(nodes.values()), "edges": edges}


def kg_graph(rows: Iterable[dict], *, detected_techniques: Iterable[str] = ()) -> dict:
    """Full engagement-scoped KG rows (`RedKGReader.graph`) → an interactive `{nodes, edges}` graph.

    Each node's `kind` is its first Neo4j label lowercased (host/port/service/finding/technique/…), so
    the console can color it by type like the recon graph. Technique nodes are flagged detected/missed
    from the scorecard; a finding is flagged detected if it USES a detected technique. Deduped.
    """
    det = {t for t in detected_techniques if isinstance(t, str)}
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    seen: set[tuple] = set()

    def add(nid: object, labels: object, key: object) -> str | None:
        if not isinstance(nid, str):
            return None
        if nid not in nodes:
            labs = labels if isinstance(labels, list) else []
            kind = str(labs[0]).lower() if labs else "node"
            label = str(key if key is not None else nid)[:48]
            node = {"id": nid, "kind": kind, "label": label}
            if kind in ("technique", "mitre"):
                node["detected"] = any(t in det for t in _TECH_SCAN.findall(label))
            nodes[nid] = node
        return nid

    for r in rows:
        if not isinstance(r, dict):
            continue
        a = add(r.get("nid"), r.get("nl"), r.get("nk"))
        rt, mid = r.get("rt"), r.get("mid")
        # neighborhood-expansion rows (RedKGReader.neighbors) also carry the far node's labels/key
        # in `ml`/`mk` so the subgraph is self-contained; the full-graph query omits them (every node
        # is already an `n` row there) so this stays a no-op for it.
        if isinstance(mid, str) and r.get("ml") is not None:
            add(mid, r.get("ml"), r.get("mk"))
        if a and isinstance(rt, str) and isinstance(mid, str):
            key = (a, mid, rt)
            if key not in seen:
                seen.add(key)
                edges.append({"source": a, "target": mid, "rel": rt})
    # a finding inherits "detected" from any technique it points at
    det_tech = {n["id"] for n in nodes.values() if n["kind"] in ("technique", "mitre") and n.get("detected")}
    for e in edges:
        src = nodes.get(e["source"])
        if src and src["kind"] == "finding" and e["target"] in det_tech:
            src["detected"] = True
    return {"nodes": list(nodes.values()), "edges": edges}


def findings_to_detections(findings: Iterable[dict], *, exclude_data_sources: Iterable[str] = ()) -> list[dict]:
    """Vigil findings → [{technique, entity, ts, finding_id}].

    `exclude_data_sources` drops red-origin findings (e.g. "decepticon") from the *detection*
    numerator so the score reflects sensor-driven detection, not our own ingest (plan 07 §3.2 honesty rule).
    """
    excluded = set(exclude_data_sources)
    out: list[dict] = []
    for f in findings:
        # Vigil serves a mixed finding population (SCA/CIS, native, coordinator-ingested); some rows
        # carry mitre_predictions/entity_context as non-dicts (int/str/list) or aren't dicts at all.
        # Be defensive so one odd finding can't crash the whole engagement (real bug: 'int'.get).
        if not isinstance(f, dict) or f.get("data_source") in excluded:
            continue
        mp = f.get("mitre_predictions")
        mp = mp if isinstance(mp, dict) else {}
        ec = f.get("entity_context")
        ec = ec if isinstance(ec, dict) else {}
        entity = ec.get("dst_ip") or ec.get("src_ip") or ec.get("hostname") or ec.get("affected_target") or ""
        ts = _epoch(f.get("timestamp"))
        fid = f.get("finding_id")
        text = f.get("description") or ""                  # untrusted text — scanned by the shield (§6)
        for t in _valid_techs(mp.keys()):
            out.append({"technique": t, "entity": str(entity), "ts": ts, "finding_id": fid,
                        "text": text, "evidence_refs": [fid] if fid else []})
    return out
