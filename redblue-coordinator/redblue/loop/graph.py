"""build_graph() — wire the nodes + edges + checkpointer into the closed loop (plan 07 §2.1).

P4 is a linear on-demand loop:
    plan_engagement → trigger_red → await_telemetry → collect_detections → score
                    → decide_response → report_evidence → END
Continuous mode (watch_drift re-entry) and the governance interrupt at decide_response land in P7/P5;
the conditional routing in edges.py is ready for them.
"""
from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from .edges import route_after_report
from .nodes import (
    make_await_telemetry,
    make_collect_detections,
    make_decide_response,
    make_plan_engagement,
    make_report_evidence,
    make_score,
    make_trigger_red,
)
from .ports import Deps
from .state import LoopState


def build_graph(deps: Deps, checkpointer: Any | None = None):
    g = StateGraph(LoopState)
    g.add_node("plan_engagement", make_plan_engagement(deps))
    g.add_node("trigger_red", make_trigger_red(deps))
    g.add_node("await_telemetry", make_await_telemetry(deps))
    g.add_node("collect_detections", make_collect_detections(deps))
    g.add_node("score", make_score(deps))
    g.add_node("decide_response", make_decide_response(deps))
    g.add_node("report_evidence", make_report_evidence(deps))

    g.add_edge(START, "plan_engagement")
    g.add_edge("plan_engagement", "trigger_red")
    g.add_edge("trigger_red", "await_telemetry")
    g.add_edge("await_telemetry", "collect_detections")
    g.add_edge("collect_detections", "score")
    g.add_edge("score", "decide_response")
    g.add_edge("decide_response", "report_evidence")
    # Each loop iteration terminates. In P7, continuous re-entry is driven EXTERNALLY by the
    # ContinuousController (drift → gated replay → re-invoke), so both routes end the per-iteration
    # graph. The in-graph `watch_drift` node (an alternative representation) is the live slice.
    g.add_conditional_edges("report_evidence", route_after_report, {"continue": END, "done": END})

    # Human-in-the-loop over the ATTACK PLAN (§2.3) is applied PER-RUN, not baked into the graph:
    # create_engagement passes `interrupt_before=["trigger_red"]` at invoke time only when HITL is on
    # (holding the checkpointed run before red executes, resumed by POST …/plan/approve). Compiling
    # without a global interrupt keeps every other consumer — direct tests, continuous replays — inline.
    return g.compile(checkpointer=checkpointer)
