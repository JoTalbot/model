import pytest

from swarm.tools_runtime.execution_store import ExecutionStore
from swarm.tools_runtime.runtime_orchestrator import RuntimeOrchestrator


class Planner:
    async def create_plan(self, goal):
        return []


class Executor:
    async def execute(self, *args):
        return []


class FailingBootstrap:
    async def recover_with_loop(self, *args, **kwargs):
        raise RuntimeError("recovery failed")


@pytest.mark.asyncio
async def test_start_failure_does_not_leave_orchestrator_started(tmp_path):
    store = ExecutionStore(str(tmp_path / "executions.json"))
    runtime = RuntimeOrchestrator(Executor(), Planner(), store=store)
    runtime.bootstrap = FailingBootstrap()

    with pytest.raises(RuntimeError, match="recovery failed"):
        await runtime.start("agent-1")

    assert runtime.started is False
