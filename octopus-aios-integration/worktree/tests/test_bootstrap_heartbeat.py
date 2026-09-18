import asyncio

import pytest

from swarm.tools_runtime.execution_lease import ExecutionLeaseStore
from swarm.tools_runtime.execution_store import ExecutionState, ExecutionStore
from swarm.tools_runtime.runtime_bootstrap import RuntimeBootstrap


@pytest.mark.asyncio
async def test_recovery_renews_lease_while_resume_runs(tmp_path):
    store = ExecutionStore(str(tmp_path / "executions.json"))
    leases = ExecutionLeaseStore(str(tmp_path / "leases.json"), ttl_seconds=1)
    store.save(ExecutionState("e1", status="running"))
    bootstrap = RuntimeBootstrap(store, lease_store=leases, owner_id="node-a", heartbeat_interval=0.1)

    async def resume(state):
        await asyncio.sleep(0.35)
        assert leases.is_owner("e1", "node-a")

    report = await bootstrap.recover_pending(resume)
    assert report.recovered == 1
    assert leases.is_owner("e1", "node-b") is False


@pytest.mark.asyncio
async def test_heartbeat_is_cancelled_after_recovery(tmp_path):
    store = ExecutionStore(str(tmp_path / "executions.json"))
    leases = ExecutionLeaseStore(str(tmp_path / "leases.json"), ttl_seconds=1)
    store.save(ExecutionState("e1", status="running"))
    bootstrap = RuntimeBootstrap(store, lease_store=leases, owner_id="node-a", heartbeat_interval=0.05)

    async def resume(state):
        return None

    await bootstrap.recover_pending(resume)
    assert not leases.is_owner("e1", "node-a")
