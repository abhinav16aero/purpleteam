"""Tests for redblue.contracts — the plan-05 canonical schemas. Pure; no engines needed."""
import pytest
from pydantic import ValidationError

from redblue.contracts import (
    EMBEDDING_DIM,
    FINDING_ID_RE,
    GENESIS_HASH,
    ActionType,
    CanonicalFinding,
    EdgeKind,
    EventType,
    EvidenceRecord,
    MatchState,
    NodeKind,
    build_scorecard,
    correlate,
    finding_from_decepticon,
    make_finding_id,
    normalize_entity_context,
    verify_chain,
)


def _fid() -> str:
    return make_finding_id("wazuh", "abc")


# ── finding_id ───────────────────────────────────────────────────────────────
def test_finding_id_is_sha256_16():
    fid = make_finding_id("decepticon", "eng:FIND-1", "2026-08-05T10:00:00Z")
    assert FINDING_ID_RE.match(fid)
    assert fid.startswith("f-20260805-") and len(fid.split("-")[-1]) == 16

def test_bad_finding_id_rejected():
    with pytest.raises(ValidationError):
        CanonicalFinding(finding_id="f-bad", data_source="wazuh", timestamp="2026-08-05T00:00:00Z")


# ── §1.4 mitre must be technique-IDs (tactic-names dropped) ───────────────────
def test_mitre_keeps_technique_ids_drops_tactic_names():
    f = CanonicalFinding(finding_id=_fid(), data_source="wazuh", timestamp="t",
                         mitre_predictions={"T1059.004": 0.9, "Command and Control": 1.0, "junk": 0.5})
    assert f.mitre_predictions == {"T1059.004": 0.9}


# ── §1.5 embedding pad/truncate, anomaly clamp ────────────────────────────────
def test_embedding_padded_and_truncated():
    assert len(CanonicalFinding(finding_id=_fid(), data_source="x", timestamp="t").embedding) == EMBEDDING_DIM
    assert len(CanonicalFinding(finding_id=_fid(), data_source="x", timestamp="t",
                                embedding=[1.0] * 1000).embedding) == EMBEDDING_DIM

def test_anomaly_score_clamped():
    assert CanonicalFinding(finding_id=_fid(), data_source="x", timestamp="t", anomaly_score=5.0).anomaly_score == 1.0


# ── §1.3 entity_context plural-list/alias → singular scalar ───────────────────
def test_entity_context_normalized():
    ec = normalize_entity_context({"src_ips": ["10.0.0.5", "10.0.0.6"], "dest_ip": "10.0.0.9", "srcport": 4444})
    assert ec["src_ip"] == "10.0.0.5" and ec["dst_ip"] == "10.0.0.9" and ec["src_port"] == 4444
    assert "src_ips" not in ec or ec.get("src_ip")  # canonical present


# ── §1.5 drift trap: extra top-level fields are FORBIDDEN ──────────────────────
def test_extra_field_forbidden():
    with pytest.raises(ValidationError):
        CanonicalFinding(finding_id=_fid(), data_source="x", timestamp="t", technique="T1190")


# ── §2 decepticon → finding ───────────────────────────────────────────────────
def test_finding_from_decepticon():
    f = finding_from_decepticon(engagement_id="eng-t01-20260805-ab", red_action_id="FIND-014",
                                technique_ids=["T1190"], target="10.20.0.9", tenant_id="t01", severity="high")
    assert f.data_source == "decepticon"
    assert f.external_id == "eng-t01-20260805-ab:FIND-014"       # the real dedup key
    assert f.cluster_id == "eng-t01-20260805-ab"
    assert f.mitre_predictions == {"T1190": 0.7}
    assert f.entity_context["dst_ip"] == "10.20.0.9"
    assert f.entity_context["red_source"] == "decepticon"
    assert FINDING_ID_RE.match(f.finding_id)


# ── enum fidelity vs the real engine code ─────────────────────────────────────
def test_enum_values():
    assert len(list(EventType)) == 10 and EventType.FINDING_CREATED.value == "finding.created"
    assert len(list(ActionType)) == 11 and ActionType.ISOLATE_HOST.value == "isolate_host"
    assert NodeKind.DETECTION_FIRED.value == "DetectionFired"
    assert {EdgeKind.DETECTED.value, EdgeKind.USES_RULE.value} == {"DETECTED", "USES_RULE"}


# ── §8 correlation join ───────────────────────────────────────────────────────
def test_correlate_detected_within_window():
    r = correlate(
        [{"technique": "T1190", "entity": "10.20.0.9", "ts": 1000.0, "red_action_id": "FIND-014"}],
        [{"technique": "T1190", "entities": ["10.20.0.9"], "ts": 1042.0, "finding_id": "f-x"}],
    )
    assert len(r) == 1 and r[0]["state"] == MatchState.DETECTED and r[0]["mttd_seconds"] == 42.0

def test_correlate_missed_outside_window():
    r = correlate(
        [{"technique": "T1190", "entity": "10.20.0.9", "ts": 1000.0}],
        [{"technique": "T1190", "entity": "10.20.0.9", "ts": 9000.0, "finding_id": "f-x"}],
    )
    assert r[0]["state"] == MatchState.MISSED


# ── §6 scorecard ──────────────────────────────────────────────────────────────
def test_build_scorecard():
    corr = correlate(
        [{"technique": "T1190", "entity": "h1", "ts": 1000.0}, {"technique": "T1046", "entity": "h1", "ts": 1000.0}],
        [{"technique": "T1190", "entity": "h1", "ts": 1050.0, "finding_id": "f-1"}],  # only T1190 detected
    )
    sc = build_scorecard(engagement_id="eng-t01-20260805-ab", tenant_id="t01", window={"start": 0}, correlations=corr)
    assert sc.detection_rate == 0.5
    assert sc.detected_techniques == ["T1190"] and "T1046" in sc.attacked_techniques
    assert sc.mttd["mean"] == 50.0
    assert any(g.technique_id == "T1046" for g in sc.gaps)


# ── §7.3 evidence hash-chain (WORM tamper-evidence) ───────────────────────────
def _chain(n=3):
    recs, prev = [], GENESIS_HASH
    for i in range(n):
        r = EvidenceRecord.create(seq=i, ts=1000.0 + i, engagement_id="e", tenant_id="t",
                                  actor="coordinator", record_type="decision", payload={"i": i}, prev_hash=prev)
        recs.append(r); prev = r.this_hash
    return recs

def test_evidence_chain_verifies():
    assert verify_chain(_chain()) is True

def test_evidence_chain_detects_tamper():
    recs = _chain()
    recs[1].payload_hash = "sha256:deadbeef"      # tamper
    assert verify_chain(recs) is False
