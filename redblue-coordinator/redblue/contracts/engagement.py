"""Coordinator schemas — Engagement + Scorecard (plan 05 §6). NEW; implemented by 07.

`build_scorecard` computes detection-rate / MTTD / per-technique from the correlation output (§8),
using ground-truth denominators (never red's self-report).
"""
from __future__ import annotations

import statistics
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from .correlation import MatchState


class EngagementStatus(str, Enum):
    SCHEDULED = "scheduled"
    RUNNING = "running"
    AWAITING_TELEMETRY = "awaiting_telemetry"
    SCORING = "scoring"
    COMPLETED = "completed"
    ABORTED = "aborted"
    FAILED = "failed"


class Engagement(BaseModel):
    engagement_id: str               # ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ (Decepticon regex)
    tenant_id: str
    name: str | None = None
    engagement_type: str = "external"
    roe_ref: str | None = None
    enforcement_mode: str = "enforce"          # roe.py EnforcementMode: audit|warn|enforce
    scope: dict[str, Any] = Field(default_factory=dict)
    target: dict[str, Any] = Field(default_factory=dict)
    status: EngagementStatus = EngagementStatus.SCHEDULED
    decepticon: dict[str, Any] = Field(default_factory=dict)   # {thread_id, run_id, assistant, workspace_path}
    created_at: str | None = None
    updated_at: str | None = None


class TechniqueScore(BaseModel):
    technique_id: str
    attacked: int = 0
    detected: int = 0
    missed: int = 0
    detection_rate: float | None = None
    mttd_seconds: float | None = None


class GapItem(BaseModel):
    technique_id: str
    entity: str | None = None
    first_attack_ts: float | None = None
    suggested_control: str | None = None


class PerFindingScore(BaseModel):
    technique: str
    entity: str | None = None
    red_action_id: str | None = None
    red_action_ts: float | None = None
    blue_finding_id: str | None = None
    blue_detect_ts: float | None = None
    detected: bool = False
    mttd_seconds: float | None = None


class Scorecard(BaseModel):
    scorecard_id: str
    engagement_id: str
    tenant_id: str
    version: int = 1
    window: dict[str, Any] = Field(default_factory=dict)
    attacked_techniques: list[str] = Field(default_factory=list)
    detected_techniques: list[str] = Field(default_factory=list)
    gaps: list[GapItem] = Field(default_factory=list)
    detection_rate: float | None = None
    mttd: dict[str, float | None] = Field(default_factory=dict)   # {mean, median, p90}
    per_technique: list[TechniqueScore] = Field(default_factory=list)
    per_finding: list[PerFindingScore] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


def _pctile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    k = min(len(s) - 1, int(round(q * (len(s) - 1))))
    return s[k]


def build_scorecard(
    *, engagement_id: str, tenant_id: str, window: dict, correlations: list[dict], version: int = 1
) -> Scorecard:
    """Fold `correlate()` output (plan 05 §8) into a Scorecard. `correlations` = list of match dicts."""
    per_tech: dict[str, TechniqueScore] = {}
    per_tech_mttds: dict[str, list[float]] = {}
    per_finding: list[PerFindingScore] = []
    mttds: list[float] = []
    attacked: set[str] = set()
    detected: set[str] = set()
    gap_keys: set[tuple[str, str | None]] = set()
    gaps: list[GapItem] = []
    total_attacked_inst = 0
    total_detected_inst = 0

    for c in correlations:
        tid = c["technique"]
        attacked.add(tid)
        total_attacked_inst += 1
        ts = per_tech.setdefault(tid, TechniqueScore(technique_id=tid))
        ts.attacked += 1
        is_det = c["state"] == MatchState.DETECTED
        if is_det:
            ts.detected += 1
            total_detected_inst += 1
            detected.add(tid)
            if c.get("mttd_seconds") is not None:
                mttds.append(c["mttd_seconds"])
                per_tech_mttds.setdefault(tid, []).append(c["mttd_seconds"])
        else:
            ts.missed += 1
            key = (tid, c.get("entity"))            # dedup identical (technique, entity) misses
            if key not in gap_keys:
                gap_keys.add(key)
                gaps.append(GapItem(technique_id=tid, entity=c.get("entity"),
                                    first_attack_ts=c.get("red_ts")))
        per_finding.append(PerFindingScore(
            technique=tid, entity=c.get("entity"), red_action_id=c.get("red_action_id"),
            red_action_ts=c.get("red_ts"), blue_finding_id=c.get("finding_id"),
            blue_detect_ts=c.get("blue_ts"), detected=is_det, mttd_seconds=c.get("mttd_seconds"),
        ))

    for tid, ts in per_tech.items():
        denom = ts.detected + ts.missed
        ts.detection_rate = (ts.detected / denom) if denom else None
        tm = per_tech_mttds.get(tid)
        ts.mttd_seconds = statistics.fmean(tm) if tm else None

    return Scorecard(
        scorecard_id=f"sc-{engagement_id}-v{version}",
        engagement_id=engagement_id, tenant_id=tenant_id, version=version, window=window,
        attacked_techniques=sorted(attacked), detected_techniques=sorted(detected), gaps=gaps,
        # per-INSTANCE detection rate (consistent with per_technique rates), NOT per-technique-presence
        detection_rate=(total_detected_inst / total_attacked_inst) if total_attacked_inst else None,
        mttd={
            "mean": (statistics.fmean(mttds) if mttds else None),
            "median": (statistics.median(mttds) if mttds else None),
            "p90": _pctile(mttds, 0.9),
        },
        per_technique=sorted(per_tech.values(), key=lambda t: t.technique_id),
        per_finding=per_finding,
    )
