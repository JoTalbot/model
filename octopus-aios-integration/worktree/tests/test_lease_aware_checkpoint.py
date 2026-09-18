import pytest

from swarm.tools_runtime.execution_lease import ExecutionLeaseStore
from swarm.tools_runtime.execution_store import ExecutionState, ExecutionStore
from swarm.tools_runtime.lease_aware_checkpoint import LeaseAwareCheckpoint
from swarm.tools_runtime.recovery_checkpoint import RecoveryCheckpoint


class TestCheckpoint(RecoveryCheckpoint):
    pass


def test_stale_owner_cannot_checkpoint(tmp_path):
    store = ExecutionStore(str(tmp_path / "executions.json"))
    leases = ExecutionLeaseStore(str(tmp_path / "leases.json"), ttl_seconds=60)
    checkpoint = LeaseAwareCheckpoint(RecoveryCheckpoint(store), leases, "node-a")
    state = ExecutionState("e1", status="running")
    leases.acquire("e1", "node-b")
    with pytest.raises(RuntimeError, match="lease is not owned"):
        checkpoint.mark_running(state, 1, [{"tool": "work"}])


def test_current_owner_can_checkpoint(tmp_path):
    store = ExecutionStore(str(tmp_path / "executions.json"))
    leases = ExecutionLeaseStore(str(tmp_path / "leases.json"), ttl_seconds=60)
    checkpoint = LeaseAwareCheckpoint(RecoveryCheckpoint(store), leases, "node-a")
    state = ExecutionState("e1", status="running")
    leases.acquire("e1", "node-a")
    checkpoint.mark_running(state, 1, [{"tool": "work"}])
    assert store.get("e1").attempt == 1
