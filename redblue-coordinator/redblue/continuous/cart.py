"""CART — Continuous Automated Red Teaming: drift → replay plan (plan 07 §5).

The coordinator owns the drift receiver, debounce/rate-limit, and the dry-run→live gate (plan 07 §5.1);
the in-engine `ReplayRunner` (real record/replay) is the live slice on Decepticon's :2024. Here we
turn an infra `ChangeEvent` into a scoped `ReplayPlan` (delta objectives) and enforce the safety +
budget rules deterministically.
"""
from __future__ import annotations

import hashlib

from pydantic import BaseModel, Field

from ..contracts import TECHNIQUE_RE


class ChangeEvent(BaseModel):
    source: str                       # cloudtrail | k8s-audit | terraform | github | scheduled
    event_type: str
    resource_id: str
    resource_kind: str = "unknown"
    technique_tags: list[str] = Field(default_factory=list)   # ATT&CK technique-IDs re-exposed
    observed_at: float                # epoch seconds (the drift clock)
    raw: dict = Field(default_factory=dict)


class ReplayPlan(BaseModel):
    plan_id: str
    engagement_id: str
    delta_summary: str
    selected_objectives: list[str]
    dry_run: bool = True              # first replay of an engagement is ALWAYS dry-run (§2.6 CART default)


def tenant_of(engagement_id: str) -> str:
    """eng-<tenant>-<YYYYMMDD>-<short> → tenant. Handles hyphenated tenants (e.g. 'acme-corp',
    't-eval') by locating the 8-digit date token; '*' if unparseable."""
    parts = engagement_id.split("-")
    if len(parts) < 4 or parts[0] != "eng":
        return "*"
    for i in range(2, len(parts)):
        if len(parts[i]) == 8 and parts[i].isdigit():   # the YYYYMMDD date
            return "-".join(parts[1:i])
    return parts[1]


def _plan_id(engagement_id: str, ce: ChangeEvent) -> str:
    key = f"{engagement_id}:{ce.resource_id}:{ce.observed_at}"
    return "rp-" + hashlib.sha256(key.encode()).hexdigest()[:12]


def build_replay_plan(engagement_id: str, ce: ChangeEvent, first_replay: bool = True) -> ReplayPlan:
    techs = [t for t in ce.technique_tags if TECHNIQUE_RE.match(t)]
    objectives = ([f"replay {t} against {ce.resource_id}" for t in techs]
                  or [f"re-scan {ce.resource_id}"])
    return ReplayPlan(
        plan_id=_plan_id(engagement_id, ce), engagement_id=engagement_id,
        delta_summary=f"{ce.source}:{ce.event_type} on {ce.resource_id} → {len(techs)} technique(s)",
        selected_objectives=objectives, dry_run=first_replay,
    )


class Debouncer:
    """Collapse ChangeEvents on the same resource_id within a window (§5.3) — infra feeds are chatty."""

    def __init__(self, window_s: float = 300.0) -> None:
        self._window = window_s
        self._last: dict[str, float] = {}

    def should_process(self, resource_id: str, now: float) -> bool:
        last = self._last.get(resource_id)
        if last is not None and (now - last) < self._window:
            return False
        self._last[resource_id] = now
        return True


class ReplayBudget:
    """Cap replays/hour so a drift storm can't burn budget (§5.3). Sliding 1h window."""

    def __init__(self, max_per_hour: int = 6) -> None:
        self._max = max_per_hour
        self._events: list[float] = []

    def allow(self, now: float) -> bool:
        self._events = [t for t in self._events if now - t < 3600]
        if len(self._events) >= self._max:
            return False
        self._events.append(now)
        return True
