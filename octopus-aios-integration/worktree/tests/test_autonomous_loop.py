import pytest

from swarm.tools_runtime.autonomous_loop import AutonomousExecutionLoop
from swarm.tools_runtime.replanning import ReplanningPolicy
from swarm.tools_runtime.tool_protocol import ToolResult


class Planner:
    def __init__(self):
        self.calls = 0

    async def create_plan(self, goal):
        self.calls += 1
        return [{"tool": "work", "arguments": {"goal": goal}}]


class Executor:
    def __init__(self):
        self.calls = 0

    async def execute(self, agent, plan, context, execution):
        self.calls += 1
        if self.calls == 1:
            return [ToolResult("c1", "work", False, error="temporary")]
        return [ToolResult("c2", "work", True, value="done")]


@pytest.mark.asyncio
async def test_failed_tool_automatically_replans_and_reexecutes():
    planner = Planner()
    executor = Executor()
    loop = AutonomousExecutionLoop(executor, planner, ReplanningPolicy(max_attempts=2))

    result = await loop.run("demo", "agent-1")

    assert result.status == "completed"
    assert result.attempts == 2
    assert executor.calls == 2
    assert planner.calls == 2
