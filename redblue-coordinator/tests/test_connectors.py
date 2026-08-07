"""Tests for redblue.connectors (plan 06). Pure/offline — live engine calls deferred."""
import json

import pytest

from redblue.connectors import (
    EventTail,
    ScopeError,
    finding_ingest_payload,
    require_scoped,
    valid_engagement,
)
from redblue.contracts import finding_from_decepticon


# ── event_tail: offset-checkpointed, torn-line-tolerant (plan 06 §3.4) ────────
def test_event_tail_yields_and_holds_torn_line(tmp_path):
    p = tmp_path / "events.jsonl"
    p.write_text(
        json.dumps({"ts": 1.0, "type": "tool.call", "agent": "recon", "payload": {}}) + "\n"
        + json.dumps({"ts": 2.0, "type": "finding.created", "payload": {"id": "FIND-1"}}) + "\n"
        + '{"ts":3.0,"type":"tool.result"'            # torn final line (no newline)
    )
    t = EventTail(str(p))
    evs = list(t.poll())
    assert [e.type for e in evs] == ["tool.call", "finding.created"] and evs[1].is_finding
    off = t.offset
    # complete the torn line + append one more
    with p.open("a") as fh:
        fh.write(',"payload":{}}\n' + json.dumps({"ts": 4.0, "type": "engagement.end", "payload": {}}) + "\n")
    evs2 = list(t.poll())
    assert [e.type for e in evs2] == ["tool.result", "engagement.end"]
    assert evs2[-1].is_engagement_end and t.offset > off


def test_event_tail_skips_malformed(tmp_path):
    p = tmp_path / "e.jsonl"
    p.write_text("not json\n" + json.dumps({"ts": 1.0, "type": "agent.turn", "payload": {}}) + "\n")
    evs = list(EventTail(str(p)).poll())
    assert len(evs) == 1 and evs[0].type == "agent.turn"


# ── kg_reader: every read must be engagement-scoped (tenant isolation, §2.2) ──
def test_require_scoped_ok_and_raises():
    require_scoped("MATCH (n) WHERE n.engagement=$engagement RETURN n")   # ok
    with pytest.raises(ScopeError):
        require_scoped("MATCH (n) RETURN n")                              # unscoped → raise


# ── red_driver: engagement slug must satisfy Decepticon's regex (§4.1) ────────
def test_valid_engagement():
    assert valid_engagement("eng-t01-20260805-ab12")
    assert not valid_engagement("-bad")           # cannot start with '-'
    assert not valid_engagement("has space")
    assert not valid_engagement("x" * 130)        # too long


# ── vigil push payload shaping (§3.2) — the exact ingest-string body ──────────
def test_finding_ingest_payload():
    f = finding_from_decepticon(engagement_id="eng-t01-20260805-ab", red_action_id="FIND-1",
                                technique_ids=["T1190"], target="10.0.0.9")
    body = finding_ingest_payload(f)
    assert body["format"] == "json" and body["data_type"] == "finding"
    parsed = json.loads(body["data"])
    assert parsed["data_source"] == "decepticon"
    assert parsed["external_id"] == "eng-t01-20260805-ab:FIND-1"        # the real dedup key
    assert parsed["mitre_predictions"] == {"T1190": 0.7}
    assert parsed["entity_context"]["dst_ip"] == "10.0.0.9"
