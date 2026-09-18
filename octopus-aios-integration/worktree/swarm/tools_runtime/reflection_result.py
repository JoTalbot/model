"""Bridge tool execution failures into bounded replanning."""

from dataclasses import dataclass
from typing import Any

from .replanning import ReflectionReplanner, ReplanDecision
from .tool_protocol import ToolResult


@dataclass(frozen=True)
class ReflectionOutcome:
    ok: bool
    decision: ReplanDecision | None = None
    plan: Any = None


class ToolReflectionBridge:
    """Turn failed ToolResults into a replanning decision."""

    def __init__(self, replanner: ReflectionReplanner):
        self.replanner = replanner

    async def evaluate(self, goal: str, attempt: int, result: ToolResult) -> ReflectionOutcome:
        if result.ok:
            return ReflectionOutcome(True)
        decision, plan = await self.replanner.replan(
            goal,
            attempt,
            RuntimeError(result.error or f"tool '{result.tool}' failed"),
        )
        return ReflectionOutcome(False, decision, plan)
