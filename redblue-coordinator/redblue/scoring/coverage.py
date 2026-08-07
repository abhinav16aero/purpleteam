"""Sensor-coverage oracle (plan 07 §4.4) — the honesty layer.

Distinguishes a real blue MISS from SENSOR_BLIND (no telemetry ever covered that entity/technique).
MVP = a static map from the telemetry config (which Wazuh/Suricata/Falco rules exist, plan 04).
A missed attack on an uninstrumented pair is a *coverage* gap, not a detection failure.
"""
from __future__ import annotations

from collections.abc import Iterable

from ..contracts import MatchState


class StaticCoverageOracle:
    """`covers(entity, technique)` from static sets. Empty sets + default=True ⇒ 'everything covered'."""

    def __init__(
        self,
        covered_techniques: Iterable[str] = (),
        covered_entities: Iterable[str] = (),
        default: bool = True,
    ) -> None:
        self._techs = set(covered_techniques)
        self._ents = set(covered_entities)
        self._default = default

    def covers(self, entity: str, technique: str) -> bool:
        if not self._techs and not self._ents:
            return self._default
        tech_ok = (technique in self._techs) if self._techs else True
        ent_ok = (entity in self._ents) if self._ents else True
        return tech_ok and ent_ok


def apply_coverage(correlations: list[dict], oracle) -> list[dict]:
    """Re-label MISSED → SENSOR_BLIND where no sensor covers the (entity, technique) pair."""
    out: list[dict] = []
    for c in correlations:
        if c["state"] == MatchState.MISSED and not oracle.covers(c.get("entity", ""), c["technique"]):
            c = {**c, "state": MatchState.SENSOR_BLIND}
        out.append(c)
    return out
