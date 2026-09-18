import asyncio

import pytest

from swarm.tools_runtime.execution_lease import ExecutionLeaseStore
from swarm.tools_runtime.execution_store import ExecutionState, ExecutionStore
from swarm.tools_runtime.runtime_bootstrap import RuntimeBootstrap


@pytest.mark.asyncio
async def test_second_runtime_recovers_after_first_process_dies(tmp_path):
    store = ExecutionStore(str(tmp_path / "executions.json"))
    leases = ExecutionLeaseStore(str(tmp_path / "leases.json"), ttl_seconds=1)
    store.save(ExecutionState("e-crash", status="running", goal="continue"))

    _first = RuntimeBootstrap(store=store, lease_store=leases, owner_id="runtime-a", heartbeat_interval=0.2)
    first_lease = leases.acquire("e-crash", "runtime-a")
    assert first_lease is not None

    # Simulate an abrupt process death: no release/finally path runs.
    await asyncio.sleep(1.1)

    second = RuntimeBootstrap(store=store, lease_store=leases, owner_id="runtime-b", heartbeat_interval=0.2)
    resumed = []

    async def resume(state):
        resumed.append(state.execution_id)
        state.status = "completed"
        store.save(state)

    report = await second.recover_pending(resume)

    assert report.discovered == 1
    assert report.recovered == 1
    assert resumed == ["e-crash"]
    assert store.get("e-crash").status == "completed"
