"""Live dependency wiring — the real connectors behind the loop's ports (plan 07 §3).

`build_live_deps(settings)` constructs Deps backed by the actual engines. It is safe to *construct*
without engines running (clients connect lazily); it is *exercised* only against a live enclave —
P4-live is hardware-deferred (see memory). Unit tests inject fakes instead (tests/test_loop.py).
"""
from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path

from ..config.settings import Settings
from ..config.tenants import TenantPolicyRegistry
from ..connectors import EventTail, RedDriver, RedKGReader, VigilClient
from ..evidence.store import EvidenceStore
from ..governance import (
    AssetMap,
    InjectionShield,
    KillSwitch,
    PolicyEngine,
    default_response_planner,
)
from ..scoring import StaticCoverageOracle, events_to_attacks, findings_to_detections, kg_attacks
from .ports import Deps
from .red_bridge import event_from_chunk


class _ConnectorRed:
    """RedRunner over the LangGraph :2024 driver.

    Drains the run stream to completion AND bridges it to a coordinator-local `events.jsonl` at the
    path `_EventsAttackSource` reads (`{workspace}/events.jsonl`), so the red-action timeline is
    captured even when Decepticon's own events volume is not shared (red_bridge). Returns real
    start/end timing for the scoring window instead of the previous no-op drain.
    """

    def __init__(self, driver: RedDriver, clock: Callable[[], float] = time.time) -> None:
        self._driver = driver
        self._clock = clock

    async def launch(self, *, engagement, workspace, sandbox_url, tenant, instruction) -> dict:
        events_path = Path(workspace) / "events.jsonl"
        start = self._clock()
        captured = 0
        error: str | None = None
        # A red-run/stream failure (Decepticon LLM unconfigured, stream error) OR an unwritable
        # workspace must NOT abort the engagement: capture it and return a terminal 'failed' red_run
        # so the loop still scores (attacked: 0) and the engagement COMPLETES instead of 502ing.
        # mkdir + open are INSIDE the try so a workspace-IO failure also degrades gracefully.
        try:
            events_path.parent.mkdir(parents=True, exist_ok=True)
            # truncate-per-launch so a re-run of the same engagement can't double-count captured events
            with events_path.open("w", encoding="utf-8") as fh:
                async for chunk in self._driver.launch(
                    engagement=engagement, workspace=workspace, sandbox_url=sandbox_url,
                    tenant=tenant, instruction=instruction,
                ):
                    rec = event_from_chunk(chunk, self._clock())
                    if rec is not None:
                        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                        fh.flush()
                        captured += 1
        except Exception as e:  # noqa: BLE001 — red-run/stream/IO failure must not abort the engagement
            error = f"{type(e).__name__}: {e}"
        red_run = {"thread_id": engagement, "run_id": None,
                   "status": "failed" if error else "success",
                   "started_at": start, "ended_at": self._clock(), "events_captured": captured}
        if error:
            red_run["error"] = error
        return red_run


class _EventsAttackSource:
    """Attacked ground-truth from Decepticon's per-engagement events.jsonl (the red clock)."""

    def __init__(self, workspace_root: str = "/workspace") -> None:
        self._root = workspace_root

    def attacks(self, engagement: str, window: dict) -> list[dict]:
        path = Path(self._root) / engagement / "events.jsonl"
        events = list(EventTail(path).poll())
        return events_to_attacks(events)


class _KGAttackSource:
    """Attack ground-truth from Decepticon's Neo4j KG — the real home of technique+target (§3.2).

    Decepticon's disk `events.jsonl` carries only `{"tool": ...}` for a finding; the MITRE technique
    and target live in the KG (plan 05 §5), so this is the source that makes a live scorecard show
    non-zero `attacked`. `default_ts` = the engagement-window start, used for MTTD when Finding nodes
    carry no timestamp of their own. A read failure degrades to `[]` (never raises into the loop) —
    a KG hiccup must not abort scoring; the scorecard then honestly reports 0 attacked.
    """

    def __init__(self, reader: RedKGReader) -> None:
        self._reader = reader

    def attacks(self, engagement: str, window: dict) -> list[dict]:
        try:
            rows = self._reader.attack_events(engagement)
        except Exception:  # noqa: BLE001 — transient KG/driver errors must not abort the engagement
            return []
        t0 = (window or {}).get("t_start") or 0.0
        return kg_attacks(rows, default_ts=float(t0))


class _VigilDetectionSource:
    """Sensor-origin blue detections from Vigil findings (excludes red-origin ingest, §3.2)."""

    def __init__(self, client: VigilClient) -> None:
        self._client = client

    def detections(self, engagement: str, window: dict) -> list[dict]:
        # Sensor findings (wazuh/suricata/falco) do NOT carry an engagement tag — they are correlated
        # by technique+entity+time (plan 05 §8), so we must NOT pre-filter by engagement (that was a
        # bug that zeroed the detection numerator). Pull recent sensor-origin findings and bound to
        # the scoring window; correlate() enforces the technique+entity match.
        findings = self._client.list_findings(limit=500)
        dets = findings_to_detections(findings, exclude_data_sources=["decepticon"])
        t0 = (window or {}).get("t_start")
        t1 = (window or {}).get("settle_deadline") or (window or {}).get("t_end")
        if t0 is not None and t1 is not None:
            dets = [d for d in dets if t0 <= d["ts"] <= t1]
        return dets


def build_live_deps(settings: Settings | None = None) -> Deps:
    from ..config.settings import get_settings
    s = settings or get_settings()
    evidence = EvidenceStore()
    # Governance ON by default in the live wiring (plan 08). AssetMap ships with the control-plane
    # inventory; per-tenant assets are seeded from the CMDB/target range (04) at deploy — until then
    # unknown targets fail closed to NEVER (safe-by-default). Tenants default force_manual=True.
    policy_engine = PolicyEngine(asset_map=AssetMap(), tenant_policies=TenantPolicyRegistry())
    killswitch = KillSwitch(evidence=evidence)
    # AI-native defense ON by default (plan 08 §6): the sovereign heuristic scanner. Point at the real
    # vigil-llm service by passing VigilLlmHttpScanner(s.vigil_llm_url) once it's deployed (§6.2).
    shield = InjectionShield()
    # Attack ground-truth: prefer the Neo4j KG (where Decepticon records technique+target) when a
    # password is configured; otherwise fall back to the events.jsonl capture (red clock only —
    # techniques need the KG, plan 05 §5).
    if s.decepticon_neo4j_password:
        attack_source = _KGAttackSource(RedKGReader(
            s.decepticon_neo4j_uri, s.decepticon_neo4j_user,
            s.decepticon_neo4j_password, s.decepticon_neo4j_database))
    else:
        attack_source = _EventsAttackSource()
    return Deps(
        red=_ConnectorRed(RedDriver(s.langgraph_url)),
        attack_source=attack_source,
        detection_source=_VigilDetectionSource(VigilClient(s.vigil_url, s.vigil_token or None)),
        coverage=StaticCoverageOracle(default=True),
        evidence=evidence,
        settle_seconds=s.telemetry_settle_s,
        policy_engine=policy_engine,
        killswitch=killswitch,
        response_planner=default_response_planner,
        shield=shield,
        verify_detections=True,
    )
