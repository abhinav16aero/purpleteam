"""Node 3 — await_telemetry (plan 07 §2.3).

Bound the scoring window: red 'done' (terminal run status / engagement.end) + a settle hold so late
sensor detections land. The RedRunner returns terminal in the MVP; a live impl polls run status and
tails events.jsonl for engagement.end. The deadline is absolute wall-clock (restart-safe).
"""
from __future__ import annotations

from ..ports import Deps
from ..state import LoopState


def make_await_telemetry(deps: Deps):
    async def await_telemetry(state: LoopState) -> dict:
        now = deps.clock()
        window = dict(state.get("window", {}))
        t_end = state.get("red_run", {}).get("ended_at") or now
        window["t_end"] = t_end
        window["settle_deadline"] = t_end + deps.settle_seconds
        return {"window": window, "status": "awaiting_telemetry"}

    return await_telemetry
