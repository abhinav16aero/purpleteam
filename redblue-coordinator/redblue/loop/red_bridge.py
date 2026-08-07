"""Bridge Decepticon's LangGraph run stream → a coordinator-local `events.jsonl` (plan 07 §3.1).

Decepticon's `EventLogMiddleware` writes the authoritative `events.jsonl` inside *its* container at
`{workspace_root}/engagements/{id}/events.jsonl`. When the coordinator shares that volume it can tail
the file directly; when it does not (host-run coordinator, or a remote LangGraph Platform), this
reconstructs an equivalent `events.jsonl` from the run stream the coordinator is already draining —
so the red-action timeline is captured regardless of volume topology, and `_ConnectorRed.launch`
returns real start/end timing instead of the old no-op drain.

HONESTY (plan 05 §5): Decepticon's *disk* `finding.created` payload is only `{"tool": <name>}` — the
MITRE technique + target live in the Neo4j KG and the telemetry sink, NOT events.jsonl. So this
captures whatever the stream carries: if Decepticon is configured to stream telemetry-shaped
`custom` frames (which DO carry mitre/target), `events_to_attacks` can extract techniques from them;
otherwise the events.jsonl records the red clock and technique attribution must come from the KG
attack source. We never synthesise a technique that the stream did not carry.
"""
from __future__ import annotations

from typing import Any


def _split_chunk(chunk: Any) -> tuple[str | None, Any]:
    """Normalise a langgraph_sdk stream item to `(event, data)` across SDK shapes.

    Multi-mode `runs.stream` yields `StreamPart(event, data)` objects; some transports surface plain
    `(event, data)` tuples or `{"event", "data"}` dicts. Anything else → `(None, chunk)`.
    """
    ev = getattr(chunk, "event", None)
    if ev is not None and hasattr(chunk, "data"):
        return str(ev), chunk.data
    if isinstance(chunk, tuple) and len(chunk) == 2:
        return (str(chunk[0]) if chunk[0] is not None else None), chunk[1]
    if isinstance(chunk, dict) and "event" in chunk:
        return (str(chunk["event"]) if chunk["event"] is not None else None), chunk.get("data", {})
    return None, chunk


def event_from_chunk(chunk: Any, now: float) -> dict | None:
    """Best-effort `events.jsonl` record `{ts,type,agent,payload}` from one stream chunk, or None.

    Captures only `custom`/event-log frames that already carry a dotted event-log `type`
    (`finding.created`, `tool.call`, `engagement.start`, …) — the middleware/telemetry-sink shape.
    State snapshots (`values`), node deltas (`updates`) and `metadata` are not red-action events and
    return None, so nothing is ever fabricated. `now` stamps frames that omit their own `ts`.
    """
    event, data = _split_chunk(chunk)
    if event not in (None, "custom", "events", "event", "event_log"):
        return None
    if not isinstance(data, dict):
        return None
    etype = data.get("type")
    if not isinstance(etype, str) or "." not in etype:
        return None
    ts = data.get("ts")
    payload = data.get("payload")
    rec: dict[str, Any] = {
        "ts": float(ts) if isinstance(ts, (int, float)) else float(now),
        "type": etype,
        "payload": payload if isinstance(payload, dict) else {},
    }
    agent = data.get("agent")
    if agent is not None:
        rec["agent"] = str(agent)
    return rec
