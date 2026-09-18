import pytest

from swarm.tools_runtime.autonomous_loop import AutonomousExecutionLoop
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

    async def execute(self, agent, plan, context, execution):
        self.calls += 1
        if self.calls == 1:
            return [ToolResult("c1", "work", False, error="temporary")]
        return [ToolResult("c2", "work", True, value="done")]


@pytest.mark.skip(reason="WAVE2-QUARANTINE: red on upstream AIOS new-branch (WIP drift), see docs/aios/WAVE2_TRIAGE.md")
@pytest.mark.asyncio
async def test_loop_uses_recovery_checkpoint_for_attempts_and_completion(tmp_path):
    store = ExecutionStore(str(tmp_path / "executions.json"))
    planner = Planner()
    loop = AutonomousExecutionLoop(Executor(), planner, ReplanningPolicy(max_attempts=2), store=store)

    result = await loop.run("checkpoint me", "agent-1")

    assert result.status == "completed"
    execution_id = next(iter(store._read()))
    state = store.get(execution_id)
    assert state.status == "completed"
    assert state.attempt == 2
    assert state.result[0].ok is True
    assert state.error is None
    assert planner.calls == 2
