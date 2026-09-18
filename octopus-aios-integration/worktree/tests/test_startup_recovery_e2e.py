import pytest

from swarm.tools_runtime.autonomous_loop import AutonomousExecutionLoop
from swarm.tools_runtime.execution_store import ExecutionState, ExecutionStore
from swarm.tools_runtime.recovery_manager import RecoveryManager
from swarm.tools_runtime.replanning import ReplanningPolicy
from swarm.tools_runtime.runtime_bootstrap import RuntimeBootstrap
from swarm.tools_runtime.tool_protocol import ToolResult


class Planner:
    def __init__(self):
        self.calls = 0

    async def create_plan(self, goal):
        self.calls += 1
        return [{"tool": "work", "arguments": {"goal": goal}}]


class Executor:
    async def execute(self, agent, plan, context, execution):
        return [ToolResult("recovered", "work", True, value="resumed")]


@pytest.mark.asyncio
async def test_startup_bootstrap_recovers_persisted_execution(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # stores default to CWD-relative data/
    store = ExecutionStore(str(tmp_path / "executions.json"))
    store.save(ExecutionState("exec-restart", status="running", goal="continue me", attempt=1,
                              plan=[{"tool": "work", "arguments": {"goal": "continue me"}}]))

    planner = Planner()
    loop = AutonomousExecutionLoop(Executor(), planner, ReplanningPolicy(max_attempts=2), store=store)
    manager = RecoveryManager(store)
    bootstrap = RuntimeBootstrap(store=store, recovery_manager=manager)

    recovered = await bootstrap.recover_pending(
        lambda state: loop.resume(state.execution_id, "agent-1")
    )

    assert recovered.discovered == 1
    assert recovered.recovered == 1
    assert recovered.failed == 0
    assert store.get("exec-restart").status == "completed"
    assert planner.calls == 0
