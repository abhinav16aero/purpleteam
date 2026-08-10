"""LoopState — the LangGraph channel schema (plan 07 §2.2).

Append channels (evidence_refs, errors) use operator.add so parallel/retried nodes merge instead
of clobber; scalar channels are last-write-wins.
"""
from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, TypedDict


class LoopState(TypedDict, total=False):
    # identity / config
    engagement_id: str            # eng-<tenant>-<YYYYMMDD>-<short> (00 §7; matches DECEPTICON regex)
    tenant_id: str
    mode: Literal["on_demand", "continuous"]
    scope: dict[str, Any]
    budget: dict[str, Any]
    enforcement_mode: str         # roe.py EnforcementMode: audit|warn|enforce (safety gate, §2.3)
    hitl_enabled: bool
    instruction: str
    workspace_path: str
    version: int
    plan: dict[str, Any]          # the editable attack plan a human reviews before red runs (HITL, §2.3)

    # red side
    red_run: dict[str, Any]       # {thread_id, run_id, status, started_at, ended_at}
    red_objectives: list[str]
    events_path: str

    # telemetry window
    window: dict[str, Any]        # {t_start, t_end, settle_deadline} (epoch seconds)

    # blue side
    attacks: list[dict]           # ground truth: [{technique, entity, ts, red_action_id}]
    detections: list[dict]        # sensor-origin, shield-passed + verified: [{technique, entity, ts, finding_id}]
    quarantined: list[dict]       # detections dropped by the injection shield / verification gate (§6/§7)
    injection_flags: list[dict]   # weak-signal flags (kept, but surfaced) (§6.4)

    # results
    scorecard: dict[str, Any]
    coverage_gaps: list[dict]     # SENSOR_BLIND (technique, entity) — reported separately (§4.4)
    pending_actions: list[dict]   # human/never-auto actions awaiting approval (plan 08 §2)
    response_decisions: list[dict]  # PolicyEngine verdict per proposed action (auto/human/never)

    # control
    status: str
    errors: Annotated[list[dict], operator.add]
    evidence_refs: Annotated[list[str], operator.add]
