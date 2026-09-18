import pytest

from swarm.tools_runtime.execution_lease import ExecutionLeaseStore
from swarm.tools_runtime.execution_store import ExecutionState, ExecutionStore
from swarm.tools_runtime.runtime_bootstrap import RuntimeBootstrap


@pytest.mark.asyncio
async def test_bootstrap_skips_execution_owned_by_another_runtime(tmp_path):
    store = ExecutionStore(str(tmp_path / "executions.json"))
    leases = ExecutionLeaseStore(str(tmp_path / "leases.json"), ttl_seconds=60)
    store.save(ExecutionState("e1", status="running"))
    assert leases.acquire("e1", "other-runtime") is not None

    resumed = []
    async def resume(state):
        resumed.append(state.execution_id)

    report = await RuntimeBootstrap(store, lease_store=leases, owner_id="this-runtime").recover_pending(resume)
    assert report.skipped == 1
    assert report.recovered == 0
    assert resumed == []


@pytest.mark.asyncio
async def test_bootstrap_releases_lease_after_recovery(tmp_path):
    store = ExecutionStore(str(tmp_path / "executions.json"))
    leases = ExecutionLeaseStore(str(tmp_path / "leases.json"), ttl_seconds=60)
    store.save(ExecutionState("e1", status="running"))

    async def resume(state):
        return None

    report = await RuntimeBootstrap(store, lease_store=leases, owner_id="runtime-a").recover_pending(resume)
    assert report.recovered == 1
    assert leases.acquire("e1", "runtime-b") is not None
