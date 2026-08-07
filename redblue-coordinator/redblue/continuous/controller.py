"""ContinuousController — the coordinator side of CART continuous mode (plan 07 §5.1).

Receives a drift ChangeEvent, debounces + rate-limits, builds a ReplayPlan, and enforces the
dry-run→human-approval→live gate (§2.6). On a live replay it invokes the injected `run(plan)` callback
(which re-runs the coordinator loop for a new scorecard version). All drift + replays are evidence-logged.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable

from ..evidence.store import EvidenceStore
from .cart import ChangeEvent, Debouncer, ReplayBudget, ReplayPlan, build_replay_plan, tenant_of

RunFn = Callable[[ReplayPlan], Awaitable[dict]]


class ContinuousController:
    def __init__(self, evidence: EvidenceStore | None = None, debounce_s: float = 300.0,
                 max_replays_per_hour: int = 6) -> None:
        self._debouncer = Debouncer(debounce_s)
        self._budget = ReplayBudget(max_replays_per_hour)
        self._evidence = evidence
        self._seen: set[str] = set()                 # engagements that have replayed ≥ once
        self._pending: dict[str, ReplayPlan] = {}    # plan_id → plan awaiting human approval

    def _log(self, engagement_id: str, record_type: str, payload: dict, ts: float) -> None:
        if self._evidence is not None:
            self._evidence.append(engagement_id=engagement_id, tenant_id=tenant_of(engagement_id),
                                  actor="coordinator", record_type=record_type, payload=payload, ts=ts)

    async def on_drift(self, engagement_id: str, ce: ChangeEvent, run: RunFn) -> dict:
        now = ce.observed_at
        if not self._debouncer.should_process(ce.resource_id, now):
            return {"status": "debounced", "resource_id": ce.resource_id}

        first = engagement_id not in self._seen
        plan = build_replay_plan(engagement_id, ce, first_replay=first)
        self._log(engagement_id, "drift", {**ce.model_dump(), "plan_id": plan.plan_id,
                                           "dry_run": plan.dry_run}, now)
        if plan.dry_run:                              # first replay ⇒ human-gated (CART safety default)
            self._pending[plan.plan_id] = plan       # NB: dry-runs do NOT consume replay budget
            return {"status": "needs_approval", "plan": plan.model_dump()}

        # already-seen engagement → live-eligible, but a LIVE replay consumes the hourly budget
        if not self._budget.allow(now):
            self._log(engagement_id, "budget.exceeded", {"resource_id": ce.resource_id}, now)
            return {"status": "over_budget"}
        result = await self._replay(engagement_id, plan, run, now)
        return {"status": "replayed", "plan": plan.model_dump(), "result": result}

    async def approve(self, plan_id: str, run: RunFn, now: float = 0.0) -> dict:
        plan = self._pending.pop(plan_id, None)
        if plan is None:
            return {"status": "not_found"}
        if not self._budget.allow(now):              # an approved LIVE replay consumes budget too
            self._log(plan.engagement_id, "budget.exceeded", {"plan_id": plan_id}, now)
            return {"status": "over_budget"}
        plan = plan.model_copy(update={"dry_run": False})
        result = await self._replay(plan.engagement_id, plan, run, now)
        return {"status": "replayed", "plan": plan.model_dump(), "result": result}

    async def _replay(self, engagement_id: str, plan: ReplayPlan, run: RunFn, now: float) -> dict:
        self._seen.add(engagement_id)
        self._log(engagement_id, "replay.live", {"plan_id": plan.plan_id,
                                                 "objectives": plan.selected_objectives}, now)
        return await run(plan)
