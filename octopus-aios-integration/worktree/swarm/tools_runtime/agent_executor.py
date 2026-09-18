"""Execution adapter between scheduler tasks, agents and typed tool protocol."""

import asyncio
from typing import Any

from .event_bus import EventBus
from .event_types import EXECUTION_COMPLETED, EXECUTION_FAILED, EXECUTION_STARTED
from .execution_context import ExecutionContext
from .execution_events import ExecutionEvent
from .tool_executor import ToolExecutor
from .tool_protocol import ToolCall, ToolResult
from .tool_sandbox import ToolExecutionContext


class AgentExecutor:
    """Execute an agent plan through the typed, policy-aware tool boundary."""

    def __init__(self, tool_executor: ToolExecutor, memory: Any | None = None, retries: int = 0, event_bus: EventBus | None = None):
        self.tool_executor = tool_executor
        self.memory = memory
        self.retries = max(0, retries)
        self.event_bus = event_bus

    async def execute(self, agent: Any, plan: Any, context: dict | None = None, execution_context: ExecutionContext | None = None) -> Any:
        context = dict(context or {})
        agent_id = str(getattr(agent, "id", None) or agent)
        ctx = execution_context or ExecutionContext(agent_id=agent_id, goal=str(context.get("goal", "")), metadata=context)
        await self._publish(EXECUTION_STARTED, ctx, {"agent_id": agent_id})
        try:
            permissions = frozenset(context.get("permissions", ()))
            results = []
            for index, step in enumerate(plan or ()):
                if not isinstance(step, dict):
                    results.append(step)
                    continue
                tool = step.get("tool") or step.get("action")
                if not tool:
                    results.append(step)
                    continue
                call = ToolCall(tool=tool, arguments=dict(step.get("arguments") or step.get("kwargs") or {}), call_id=str(step.get("call_id") or f"{agent_id}:{index}"), timeout=step.get("timeout"))
                result = await self._execute_with_retry(call, agent_id, permissions, ctx)
                results.append(result)
                if self.memory and hasattr(self.memory, "remember"):
                    self.memory.remember({"execution_id": ctx.execution_id, "agent_id": agent_id, "tool": tool, "call_id": call.call_id, "ok": result.ok, "result": result.value, "error": result.error})
            await self._publish(EXECUTION_COMPLETED, ctx, {"agent_id": agent_id, "result_count": len(results)})
            return results
        except Exception as exc:
            await self._publish(EXECUTION_FAILED, ctx, {"agent_id": agent_id, "error": str(exc)})
            raise

    async def _execute_with_retry(self, call: ToolCall, agent_id: str, permissions: frozenset[str], ctx: ExecutionContext) -> ToolResult:
        tool_context = ToolExecutionContext(agent_id=agent_id, permissions=permissions)
        result = await self.tool_executor.execute(call, tool_context, execution_context=ctx)
        attempts = 0
        while result.retryable and not result.ok and attempts < self.retries:
            attempts += 1
            await asyncio.sleep(min(0.25 * (2 ** (attempts - 1)), 2.0))
            result = await self.tool_executor.execute(call, tool_context, execution_context=ctx)
        return result

    async def _publish(self, event_type: str, ctx: ExecutionContext, data: dict):
        if self.event_bus:
            await self.event_bus.publish(event_type, ExecutionEvent(event_type, ctx, data))
