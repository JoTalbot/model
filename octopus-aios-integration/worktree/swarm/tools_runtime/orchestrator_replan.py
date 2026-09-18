"""Bounded autonomous replan loop for the vNext orchestrator."""

from .event_types import REPLAN_COMPLETED, REPLAN_REQUESTED
from .execution_context import ExecutionContext
from .execution_events import ExecutionEvent


class OrchestratorReplanner:
    def __init__(self, planner, policy, event_bus=None):
        self.planner = planner
        self.policy = policy
        self.event_bus = event_bus

    async def replan(self, goal: str, attempt: int, error, context: ExecutionContext):
        decision = self.policy.decide(attempt, error)
        await self._publish(REPLAN_REQUESTED, context, {"attempt": attempt, "retry": decision.retry})
        if not decision.retry:
            return decision, None
        revised_goal = f"{goal} [replan attempt {attempt + 1}]"
        plan = await self.planner.create_plan(revised_goal)
        await self._publish(REPLAN_COMPLETED, context, {"attempt": attempt + 1, "plan": plan})
        return decision, plan

    async def _publish(self, event_type, context, data):
        if self.event_bus:
            await self.event_bus.publish(event_type, ExecutionEvent(event_type, context, data))
