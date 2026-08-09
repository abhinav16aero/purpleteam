"""Tests for the KG-backed attack source — Decepticon Neo4j Finding rows → attack tuples (plan 07 §3.2).

The KG (not events.jsonl) is where Decepticon records the MITRE technique + target, so this is what
makes a live scorecard show non-zero `attacked`. The extractor is schema-defensive; these pin the
behaviours we rely on across Finding-node variation.
"""
from __future__ import annotations

from datetime import UTC, datetime

from redblue.loop.live import _KGAttackSource
from redblue.scoring import kg_attacks


def test_kg_attacks_reads_explicit_technique_host_and_ts():
    rows = [{
        "finding": {"key": "FIND-7", "engagement": "eng-x", "mitre_techniques": ["T1190"],
                    "target": "5.5.5.5", "ts": 1002.5, "label": "SQLi on webapp"},
        "hosts": ["10.20.0.9", "10.20.0.10"],
    }]
    assert kg_attacks(rows, default_ts=1000.0) == [
        # host is preferred over the `target` property for the entity
        {"technique": "T1190", "entity": "10.20.0.9", "ts": 1002.5, "red_action_id": "FIND-7"},
    ]


def test_kg_attacks_scans_embedded_ids_and_falls_back_to_default_ts():
    rows = [{
        "finding": {"key": "FIND-8", "engagement": "eng-x",
                    "label": "Exploit public app (T1190 / T1046)"},  # no technique key, no ts
        "hosts": ["host-3"],
    }]
    out = kg_attacks(rows, default_ts=1000.0)
    assert [(a["technique"], a["entity"], a["ts"]) for a in out] == [
        ("T1190", "host-3", 1000.0), ("T1046", "host-3", 1000.0),
    ]


def test_kg_attacks_entity_from_target_when_no_host():
    rows = [{"finding": {"key": "F", "mitre_techniques": ["T1046"], "target_ip": "5.5.5.5"}, "hosts": []}]
    assert kg_attacks(rows, default_ts=0.0)[0]["entity"] == "5.5.5.5"


def test_kg_attacks_skips_findings_without_a_technique():
    rows = [{"finding": {"key": "F9", "label": "weak TLS config"}, "hosts": ["h"]}]
    assert kg_attacks(rows, default_ts=0.0) == []


def test_kg_attacks_parses_neo4j_style_datetime():
    dt = datetime(2026, 8, 6, 12, 0, 0, tzinfo=UTC)
    rows = [{"finding": {"key": "F", "technique": "T1059", "created_at": dt}, "hosts": ["h"]}]
    assert kg_attacks(rows, default_ts=0.0)[0]["ts"] == dt.timestamp()


class _FakeKG:
    def __init__(self, rows, boom=False):
        self._rows = rows
        self._boom = boom

    def attack_events(self, engagement):
        if self._boom:
            raise RuntimeError("neo4j unreachable")
        return self._rows


def test_kg_attack_source_uses_window_start_as_default_ts():
    rows = [{"finding": {"key": "F", "mitre_techniques": ["T1190"]}, "hosts": ["10.0.0.1"]}]
    src = _KGAttackSource(_FakeKG(rows))
    attacks = src.attacks("eng-x", {"t_start": 1234.0})
    assert attacks == [{"technique": "T1190", "entity": "10.0.0.1", "ts": 1234.0, "red_action_id": "F"}]


def test_kg_attack_source_degrades_to_empty_on_read_failure():
    # a KG hiccup must not abort the engagement — the scorecard honestly shows 0 attacked
    assert _KGAttackSource(_FakeKG([], boom=True)).attacks("eng-x", {"t_start": 1.0}) == []


def test_attack_graph_nodes_edges_and_detection_coloring():
    from redblue.scoring import attack_graph
    rows = [
        {"finding": {"key": "F-nmap", "mitre_techniques": ["T1046"], "target": "10.20.0.9",
                     "tool": "nmap", "label": "nmap scan"}, "hosts": ["10.20.0.9"]},
        {"finding": {"key": "F-brute", "mitre_techniques": ["T1110"], "target": "10.20.0.9",
                     "tool": "hydra"}, "hosts": ["10.20.0.9"]},
    ]
    g = attack_graph(rows, detected_techniques=["T1046"])
    kind = {n["id"]: n["kind"] for n in g["nodes"]}
    assert kind["10.20.0.9"] == "host"
    assert kind["F-nmap"] == "finding" and kind["tech:T1046"] == "technique"
    fnode = {n["id"]: n for n in g["nodes"] if n["kind"] == "finding"}
    assert fnode["F-nmap"]["detected"] is True and fnode["F-brute"]["detected"] is False
    assert {"source": "10.20.0.9", "target": "F-nmap", "rel": "REACHES"} in g["edges"]
    assert {"source": "F-nmap", "target": "tech:T1046", "rel": "USES"} in g["edges"]


def test_kg_graph_builds_typed_nodes_and_edges():
    from redblue.scoring import kg_graph
    # RedKGReader.graph() row shape: nid/nl/nk + rt/mid
    rows = [
        {"nid": "h1", "nl": ["Host"], "nk": "10.20.0.9", "rt": "HAS_PORT", "mid": "p1"},
        {"nid": "p1", "nl": ["Port"], "nk": "80/tcp", "rt": "RUNS_SERVICE", "mid": "s1"},
        {"nid": "s1", "nl": ["Service"], "nk": "http", "rt": None, "mid": None},
        {"nid": "f1", "nl": ["Finding"], "nk": "sqlmap SQLi", "rt": "USES", "mid": "t1"},
        {"nid": "t1", "nl": ["Technique"], "nk": "T1190", "rt": None, "mid": None},
    ]
    g = kg_graph(rows, detected_techniques=["T1190"])
    kind = {n["id"]: n["kind"] for n in g["nodes"]}
    assert kind["h1"] == "host" and kind["p1"] == "port" and kind["s1"] == "service"
    assert kind["f1"] == "finding" and kind["t1"] == "technique"
    tnode = next(n for n in g["nodes"] if n["id"] == "t1")
    fnode = next(n for n in g["nodes"] if n["id"] == "f1")
    assert tnode["detected"] is True and fnode.get("detected") is True   # finding inherits from its technique
    assert {"source": "h1", "target": "p1", "rel": "HAS_PORT"} in g["edges"]
