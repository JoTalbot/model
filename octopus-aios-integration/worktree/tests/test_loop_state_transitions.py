import pytest

from swarm.tools_runtime.autonomous_loop import AutonomousExecutionLoop
from swarm.tools_runtime.execution_context import ExecutionContext
from swarm.tools_runtime.execution_store import ExecutionStore
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

    async def execute(self, *args):
        self.calls += 1
        if self.calls == 1:
            return [ToolResult("fail", "work", False, error="temporary")]
        return [ToolResult("ok", "work", True, value="done")]


@pytest.mark.asyncio
async def test_loop_routes_retry_through_state_machine(tmp_path):
    store = ExecutionStore(str(tmp_path / "executions.json"))
    planner = Planner()
    loop = AutonomousExecutionLoop(Executor(), planner, ReplanningPolicy(max_attempts=2), store=store)
    execution = ExecutionContext(agent_id="agent-1", goal="task")

    result = await loop.run("task", "agent-1", execution_context=execution)
    state = store.get(execution.execution_id)

    assert result.status == "completed"
    assert state.status == "completed"
    assert state.attempt == 1
    assert planner.calls == 2
