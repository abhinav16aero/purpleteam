"""Dependency seam for the loop (plan 07 §1.3 / §3).

Nodes never import a connector directly — they read from an injected `Deps`. That keeps the loop
fully unit-testable with in-memory fakes (P4 acceptance runs with no live engine, plan 07 §7.3) and
lets `live.build_live_deps()` wire the real connectors for a live enclave.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from ..evidence.store import EvidenceStore


@runtime_checkable
class RedRunner(Protocol):
    async def launch(self, *, engagement: str, workspace: str, sandbox_url: str,
                     tenant: str, instruction: str) -> dict:
        """Start a scoped Decepticon engagement; return a terminal red_run dict."""
        ...


@runtime_checkable
class AttackSource(Protocol):
    def attacks(self, engagement: str, window: dict) -> list[dict]:
        """Attacked ground-truth in the window: [{technique, entity, ts, red_action_id}]."""
        ...


@runtime_checkable
class DetectionSource(Protocol):
    def detections(self, engagement: str, window: dict) -> list[dict]:
        """Sensor-origin blue detections in the window: [{technique, entity, ts, finding_id}]."""
        ...


@runtime_checkable
class CoverageOracle(Protocol):
    def covers(self, entity: str, technique: str) -> bool: ...


@dataclass
class Deps:
    red: RedRunner
    attack_source: AttackSource
    detection_source: DetectionSource
    coverage: CoverageOracle
    evidence: EvidenceStore
    clock: Callable[[], float] = time.time
    settle_seconds: float = 120.0
    # governance (plan 08) — optional: absent ⇒ decide_response stays P4 report-only.
    policy_engine: Any | None = None          # governance.PolicyEngine
    killswitch: Any | None = None             # governance.KillSwitch
    response_planner: Callable[[dict], list] | None = None  # scorecard → [ActionEnvelope]
    # AI-native defense (plan 08 §6/§7) — optional: absent ⇒ no shield/verification (P4/P5 behavior).
    shield: Any | None = None                 # governance.InjectionShield — scans detection text
    verify_detections: bool = False           # gate: drop detections with no dereferenceable evidence
    evidence_resolver: Callable[[str], bool] | None = None  # finding_id → exists? (§7 dereference)
