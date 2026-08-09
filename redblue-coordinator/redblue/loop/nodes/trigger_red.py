"""Node 2 — trigger_red (plan 07 §2.3 / §3.1).

Drive Decepticon via the injected RedRunner. Idempotency anchor = engagement_id (the LangGraph
thread_id); a retry reuses the thread rather than forking (multitask=interrupt).
"""
from __future__ import annotations

from ..ports import Deps
from ..state import LoopState


def make_trigger_red(deps: Deps):
    async def trigger_red(state: LoopState) -> dict:
        eng, tenant = state["engagement_id"], state["tenant_id"]
        workspace = state.get("workspace_path", f"/workspace/{eng}")
        sandbox_url = state.get("scope", {}).get("sandbox_url", "http://sandbox:9999")
        if state.get("simulate"):
            # Skip the live red engine — score whatever attacks/detections are already seeded in the
            # KG/Vigil. Used to test the end-to-end route without waiting on (slow, CPU-bound) red.
            now = deps.clock()
            red_run = {"thread_id": eng, "run_id": None, "status": "simulated",
                       "started_at": now, "ended_at": now, "events_captured": 0}
        else:
            red_run = await deps.red.launch(
                engagement=eng, workspace=workspace, sandbox_url=sandbox_url, tenant=tenant,
                instruction=state.get("instruction", "Run the scoped engagement per the OPPLAN."),
            )
        rec = deps.evidence.append(
            engagement_id=eng, tenant_id=tenant, actor="red",
            record_type="red.launched", payload=red_run, ts=deps.clock(),
            ref={"thread_id": red_run.get("thread_id"), "run_id": red_run.get("run_id")},
        )
        return {"red_run": red_run, "events_path": f"{workspace}/events.jsonl",
                "evidence_refs": [rec.this_hash]}

    return trigger_red
