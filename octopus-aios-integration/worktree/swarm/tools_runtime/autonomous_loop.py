"""Bounded autonomous execution loop with restart-safe, validated persistence."""

from dataclasses import dataclass
from typing import Any

from .event_types import REPLAN_COMPLETED, REPLAN_REQUESTED
from .execution_context import ExecutionContext
from .execution_events import ExecutionEvent
from .execution_store import ExecutionState, ExecutionStore
from .recovery_checkpoint import RecoveryCheckpoint
from .replanning import ReplanningPolicy


@dataclass(frozen=True)
class LoopResult:
    status: str
    result: Any = None
    attempts: int = 0


class AutonomousExecutionLoop:
    def __init__(self, executor, planner, policy: ReplanningPolicy | None = None, event_bus=None, store: ExecutionStore | None = None, checkpoint: RecoveryCheckpoint | None = None):
        self.executor = executor
        self.planner = planner
        self.policy = policy or ReplanningPolicy()
        self.event_bus = event_bus
        self.store = store
        self.checkpoint = checkpoint or (RecoveryCheckpoint(store) if store else None)

    async def run(self, goal: str, agent: Any, context: dict | None = None, execution_context: ExecutionContext | None = None):
        context = dict(context or {})
        execution = execution_context or ExecutionContext(agent_id=str(getattr(agent, "id", None) or agent), goal=goal, metadata=context)
        plan = await self.planner.create_plan(goal)
        return await self._run_from_state(goal, agent, context, execution, plan, 0)

    async def resume(self, execution_id: str, agent: Any, context: dict | None = None):
        if not self.store:
            raise RuntimeError("execution store is required for resume")
        state = self.store.get(execution_id)
        if not state or state.status not in {"running", "retrying"}:
            raise ValueError(f"execution '{execution_id}' is not resumable")
        execution = ExecutionContext(execution_id=state.execution_id, agent_id=str(getattr(agent, "id", None) or agent), goal=state.goal, metadata=dict(context or {}))
        return await self._run_from_state(state.goal, agent, dict(context or {}), execution, state.plan, state.attempt)

    async def _run_from_state(self, goal, agent, context, execution, plan, start_attempt):
        state = self.store.get(execution.execution_id) if self.store else None
        if state is None:
            state = ExecutionState(execution.execution_id, status="pending", goal=goal, attempt=start_attempt, plan=plan)
            if self.store:
                self.store.save(state)
        elif state.status == "retrying" or state.status == "pending":
            self._transition(state, "running", attempt=start_attempt, plan=plan)
        elif state.status != "running":
            raise ValueError(f"execution '{state.execution_id}' cannot run from '{state.status}'")

        for attempt in range(start_attempt, self.policy.max_attempts):
            self._checkpoint_running(state, attempt, plan)
            results = await self.executor.execute(agent, plan, context, execution)
            failed = next((r for r in results if hasattr(r, "ok") and not r.ok), None)
            if failed is None:
                self._checkpoint_completed(state, results)
                return LoopResult("completed", results, attempt + 1)
            decision = self.policy.decide(attempt, RuntimeError(failed.error or "tool execution failed"))
            await self._publish(REPLAN_REQUESTED, execution, {"attempt": attempt, "error": failed.error})
            if not decision.retry:
                self._checkpoint_failed(state, failed.error)
                return LoopResult("failed", results, attempt + 1)
            self._transition(state, "retrying", attempt=attempt, error=failed.error)
            plan = await self.planner.create_plan(f"{goal} [replan attempt {attempt + 1}]")
            self._transition(state, "running", attempt=attempt + 1, plan=plan, error=None)
            await self._publish(REPLAN_COMPLETED, execution, {"attempt": attempt + 1, "plan": plan})
        self._checkpoint_failed(state, "maximum attempts exceeded")
        return LoopResult("failed", attempts=self.policy.max_attempts)

    def _transition(self, state, status, **updates):
        state.status = status
        for key, value in updates.items():
            setattr(state, key, value)
        if self.store:
            self.store.save(state)

    def _checkpoint_running(self, state, attempt, plan):
        state.attempt, state.plan = attempt, plan
        if self.checkpoint:
            self.checkpoint.mark_running(state, attempt, plan)
        elif self.store:
            self.store.save(state)

    def _checkpoint_completed(self, state, result):
        if self.checkpoint:
            self.checkpoint.mark_completed(state, result)
        elif self.store:
            state.status, state.result, state.error = "completed", result, None
            self.store.save(state)

    def _checkpoint_failed(self, state, error):
        if self.checkpoint:
            self.checkpoint.mark_failed(state, error)
        elif self.store:
            state.status, state.error = "failed", str(error)
            self.store.save(state)

    async def _publish(self, event_type, context, data):
        if self.event_bus:
            await self.event_bus.publish(event_type, ExecutionEvent(event_type, context, data))
