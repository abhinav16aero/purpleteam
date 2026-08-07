"""Pure extractor units (plan 07 §3.2/§3.3) — engine/sensor rows → correlator tuples."""
from __future__ import annotations

from datetime import UTC, datetime

from redblue.contracts import EngagementEvent
from redblue.scoring import events_to_attacks, findings_to_detections


def test_events_to_attacks_from_finding_created():
    events = [
        EngagementEvent(ts=1000.0, type="engagement.start", payload={}),
        EngagementEvent(ts=1001.0, type="finding.created", agent="recon",
                        payload={"finding_id": "FIND-001", "mitre_techniques": ["T1046", "bogus"],
                                 "target": "10.0.0.5"}),
        EngagementEvent(ts=1002.0, type="tool.call", payload={"tool": "nmap"}),
    ]
    attacks = events_to_attacks(events)
    assert attacks == [{"technique": "T1046", "entity": "10.0.0.5", "ts": 1001.0, "red_action_id": "FIND-001"}]


def test_findings_to_detections_maps_and_excludes_red_origin():
    findings = [
        {"finding_id": "f-20260805-1111111111111111", "data_source": "suricata",
         "timestamp": "2026-08-05T00:16:50+00:00",
         "mitre_predictions": {"T1046": 0.9, "TA0001": 0.5},   # tactic dropped by TECHNIQUE_RE
         "entity_context": {"dst_ip": "10.0.0.5"}},
        {"finding_id": "f-20260805-2222222222222222", "data_source": "decepticon",
         "timestamp": "2026-08-05T00:16:00+00:00",
         "mitre_predictions": {"T1190": 0.7}, "entity_context": {"dst_ip": "10.0.0.9"}},
    ]
    dets = findings_to_detections(findings, exclude_data_sources=["decepticon"])
    assert len(dets) == 1
    assert dets[0]["technique"] == "T1046" and dets[0]["entity"] == "10.0.0.5"
    assert dets[0]["finding_id"] == "f-20260805-1111111111111111"
    expected = datetime(2026, 8, 5, 0, 16, 50, tzinfo=UTC).timestamp()
    assert abs(dets[0]["ts"] - expected) < 1.0               # ISO parsed to epoch
