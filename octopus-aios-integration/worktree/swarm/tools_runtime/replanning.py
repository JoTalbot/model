"""Failure-aware reflection and replanning for AIOS vNext."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ReplanDecision:
    retry: bool
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)


class ReplanningPolicy:
    """Converts execution failures into bounded replanning decisions."""

    def __init__(self, max_attempts: int = 2):
        self.max_attempts = max(1, max_attempts)

    def decide(self, attempt: int, error: BaseException | None = None) -> ReplanDecision:
        if attempt >= self.max_attempts:
            return ReplanDecision(False, "retry_budget_exhausted", {"attempt": attempt})
        return ReplanDecision(
            True,
            "execution_failure_requires_replan",
            {"attempt": attempt, "error": str(error) if error else None},
        )


class ReflectionReplanner:
    """Stores outcomes and asks a planner for a revised plan after failure."""

    def __init__(self, planner, memory=None, policy=None):
        self.planner = planner
        self.memory = memory
        self.policy = policy or ReplanningPolicy()

    async def replan(self, goal: str, attempt: int, error: BaseException | None = None):
        decision = self.policy.decide(attempt, error)
        if self.memory:
            self.memory.remember({"goal": goal, "attempt": attempt, "error": str(error) if error else None})
        if not decision.retry:
            return decision, None

        revised_goal = f"{goal} [replan attempt {attempt + 1}]"
        plan = await self.planner.create_plan(revised_goal)
        return decision, plan
