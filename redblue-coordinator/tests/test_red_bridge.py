"""Tests for the Decepticon run-stream → events.jsonl bridge (plan 07 §3.1).

Covers the pure `event_from_chunk` extractor across the langgraph_sdk stream shapes, and the
`_ConnectorRed.launch` capture round-trip: fake stream → events.jsonl (at the path the attack source
reads) → `events_to_attacks`, plus real start/end timing.
"""
from __future__ import annotations

from redblue.connectors import EventTail
from redblue.loop.live import _ConnectorRed
from redblue.loop.red_bridge import event_from_chunk
from redblue.scoring import events_to_attacks


class _StreamPart:
    """Mimics langgraph_sdk's StreamPart(event, data)."""

    def __init__(self, event, data):
        self.event = event
        self.data = data


def test_event_from_chunk_captures_custom_event_log_frames():
    # telemetry-shaped finding.created (carries mitre/target) → captured with payload intact
    rec = event_from_chunk(_StreamPart("custom", {
        "ts": 1000.0, "type": "finding.created", "agent": "exploit",
        "payload": {"mitre_techniques": ["T1190"], "target": "10.20.0.9", "finding_id": "FIND-1"},
    }), now=999.0)
    assert rec == {
        "ts": 1000.0, "type": "finding.created", "agent": "exploit",
        "payload": {"mitre_techniques": ["T1190"], "target": "10.20.0.9", "finding_id": "FIND-1"},
    }


def test_event_from_chunk_accepts_tuple_and_dict_shapes():
    from_tuple = event_from_chunk(("custom", {"type": "tool.call", "payload": {"tool": "nmap"}}), now=5.0)
    assert from_tuple["type"] == "tool.call"
    from_dict = event_from_chunk({"event": "custom", "data": {"type": "engagement.start", "payload": {}}}, now=5.0)
    assert from_dict["type"] == "engagement.start"


def test_event_from_chunk_stamps_now_when_ts_missing():
    rec = event_from_chunk(_StreamPart("custom", {"type": "tool.call", "payload": {}}), now=42.0)
    assert rec["ts"] == 42.0


def test_event_from_chunk_ignores_non_event_frames():
    assert event_from_chunk(_StreamPart("values", {"messages": []}), now=1.0) is None
    assert event_from_chunk(_StreamPart("updates", {"recon": {}}), now=1.0) is None
    assert event_from_chunk(_StreamPart("metadata", {"run_id": "x"}), now=1.0) is None
    # a dotless "type" is not an event-log event
    assert event_from_chunk(_StreamPart("custom", {"type": "hello", "payload": {}}), now=1.0) is None
    # non-dict custom data
    assert event_from_chunk(_StreamPart("custom", "raw text"), now=1.0) is None


class _FakeDriver:
    """RedDriver stand-in: `launch` is an async generator of stream chunks."""

    def __init__(self, chunks):
        self._chunks = chunks

    async def launch(self, **_kw):
        for c in self._chunks:
            yield c


async def test_connector_red_captures_stream_to_events_jsonl(tmp_path):
    chunks = [
        _StreamPart("custom", {"ts": 1000.0, "type": "engagement.start", "payload": {}}),
        _StreamPart("custom", {"ts": 1001.0, "type": "tool.call", "agent": "recon",
                               "payload": {"tool": "nmap"}}),
        _StreamPart("values", {"messages": ["…state snapshot…"]}),  # not an event → skipped
        _StreamPart("custom", {"ts": 1002.0, "type": "finding.created", "agent": "exploit",
                               "payload": {"mitre_techniques": ["T1190"], "target": "10.20.0.9",
                                           "finding_id": "FIND-1"}}),
    ]
    ticks = iter([100.0] + [200.0] * 10)  # start=100.0, then per-chunk + end stamps
    red = _ConnectorRed(_FakeDriver(chunks), clock=lambda: next(ticks))
    ws = tmp_path / "eng-x"
    run = await red.launch(engagement="eng-x", workspace=str(ws), sandbox_url="http://sandbox:9999",
                           tenant="acme", instruction="go")

    # real timing + capture count (3 event-log frames; the `values` snapshot is not an event)
    assert run["started_at"] == 100.0
    assert run["ended_at"] == 200.0
    assert run["events_captured"] == 3
    assert run["status"] == "success"

    # events.jsonl written exactly where _EventsAttackSource reads it ({workspace}/events.jsonl)
    ep = ws / "events.jsonl"
    assert ep.exists()
    events = list(EventTail(ep).poll())
    assert [e.type for e in events] == ["engagement.start", "tool.call", "finding.created"]

    # a rich finding.created frame → a real attack tuple (technique-level, the KG-free happy path)
    attacks = events_to_attacks(events)
    assert attacks == [
        {"technique": "T1190", "entity": "10.20.0.9", "ts": 1002.0, "red_action_id": "FIND-1"},
    ]
