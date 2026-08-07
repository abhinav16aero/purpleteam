"""Conditional routing (plan 07 §2.4).

P4 wires a linear on-demand loop that ENDs after report_evidence. The branch functions for P5
(respond vs report) and P7 (continuous vs done) are defined here ready to wire when watch_drift and
the governance gate land — kept out of the compiled edge map until their target nodes exist.
"""
from __future__ import annotations

from .state import LoopState


def route_after_score(state: LoopState) -> str:
    # P5: "respond" when the scorecard has actionable gaps/live threats; P4 is report-only.
    return "report"


def route_after_decide(state: LoopState) -> str:
    # "await_human" once decide_response can interrupt() (P5); P4 always proceeds to report.
    return "report"


def route_after_report(state: LoopState) -> str:
    # P7: "continue" → watch_drift for mode==continuous. P4: on_demand → done.
    return "continue" if state.get("mode") == "continuous" else "done"
