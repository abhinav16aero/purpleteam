"""Live dependency wiring — the real connectors behind the loop's ports (plan 07 §3).

`build_live_deps(settings)` constructs Deps backed by the actual engines. It is safe to *construct*
without engines running (clients connect lazily); it is *exercised* only against a live enclave —
P4-live is hardware-deferred (see memory). Unit tests inject fakes instead (tests/test_loop.py).
"""
from __future__ import annotations

from pathlib import Path

from ..config.settings import Settings
from ..config.tenants import TenantPolicyRegistry
from ..connectors import EventTail, RedDriver, VigilClient
from ..evidence.store import EvidenceStore
from ..governance import (
    AssetMap,
    InjectionShield,
    KillSwitch,
    PolicyEngine,
    default_response_planner,
)
from ..scoring import StaticCoverageOracle, events_to_attacks, findings_to_detections
from .ports import Deps


class _ConnectorRed:
    """RedRunner over the LangGraph :2024 driver. Drains the launch stream to a terminal red_run."""

    def __init__(self, driver: RedDriver) -> None:
        self._driver = driver

    async def launch(self, *, engagement, workspace, sandbox_url, tenant, instruction) -> dict:
        async for _chunk in self._driver.launch(
            engagement=engagement, workspace=workspace, sandbox_url=sandbox_url,
            tenant=tenant, instruction=instruction,
        ):
            pass  # live impl bridges chunks → evidence/scorecard; MVP just drains to completion
        return {"thread_id": engagement, "run_id": None, "status": "success",
                "started_at": None, "ended_at": None}


class _EventsAttackSource:
    """Attacked ground-truth from Decepticon's per-engagement events.jsonl (the red clock)."""

    def __init__(self, workspace_root: str = "/workspace") -> None:
        self._root = workspace_root

    def attacks(self, engagement: str, window: dict) -> list[dict]:
        path = Path(self._root) / engagement / "events.jsonl"
        events = list(EventTail(path).poll())
        return events_to_attacks(events)


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
    return Deps(
        red=_ConnectorRed(RedDriver(s.langgraph_url)),
        attack_source=_EventsAttackSource(),
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
