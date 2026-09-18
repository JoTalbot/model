import pytest

from swarm.tools_runtime.autonomous_loop import AutonomousExecutionLoop
from swarm.tools_runtime.execution_store import ExecutionState, ExecutionStore
from swarm.tools_runtime.replanning import ReplanningPolicy
from swarm.tools_runtime.tool_protocol import ToolResult


class Planner:
    async def create_plan(self, goal):
        return [{"tool": "work", "arguments": {"goal": goal}}]


class Executor:
    async def execute(self, agent, plan, context, execution):
        return [ToolResult("call", "work", True, value="done")]


@pytest.mark.asyncio
async def test_loop_persists_completed_state(tmp_path):
    store = ExecutionStore(str(tmp_path / "executions.json"))
    loop = AutonomousExecutionLoop(Executor(), Planner(), ReplanningPolicy(max_attempts=2), store=store)
    result = await loop.run("demo", "agent-1")
    assert result.status == "completed"
    state = store.get(next(iter(store._read())))
    assert state.status == "completed"


@pytest.mark.asyncio
async def test_loop_can_resume_running_state(tmp_path):
    store = ExecutionStore(str(tmp_path / "executions.json"))
    store.save(ExecutionState("resume-1", status="running", goal="demo", attempt=0, plan=[{"tool": "work"}]))
    loop = AutonomousExecutionLoop(Executor(), Planner(), ReplanningPolicy(max_attempts=2), store=store)
    result = await loop.resume("resume-1", "agent-1")
    assert result.status == "completed"
    assert store.get("resume-1").status == "completed"
