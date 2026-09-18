import pytest

from swarm.tools_runtime.execution_lease import ExecutionLeaseStore
from swarm.tools_runtime.execution_store import ExecutionState, ExecutionStore
from swarm.tools_runtime.runtime_orchestrator import RuntimeOrchestrator


class Planner:
    async def create_plan(self, goal):
        return [{"tool": "work", "arguments": {}}]


class Executor:
    async def execute(self, *args):
        raise RuntimeError("simulated recovery failure")


@pytest.mark.asyncio
async def test_shutdown_releases_owned_recovery_lease(tmp_path):
    store = ExecutionStore(str(tmp_path / "executions.json"))
    leases = ExecutionLeaseStore(str(tmp_path / "leases.json"), ttl_seconds=60)
    store.save(ExecutionState("e1", status="running", goal="recover", plan=[]))
    leases.acquire("e1", "node-a")

    runtime = RuntimeOrchestrator(Executor(), Planner(), owner_id="node-a", store=store, lease_store=leases)
    await runtime.shutdown()

    assert leases.acquire("e1", "node-b") is not None
    assert runtime.started is False
