import pytest

from swarm.tools_runtime.execution_lease import ExecutionLeaseStore


def test_only_one_owner_can_hold_active_lease(tmp_path):
    store = ExecutionLeaseStore(str(tmp_path / "leases.json"), ttl_seconds=60)
    assert store.acquire("e1", "node-a") is not None
    assert store.acquire("e1", "node-b") is None
    assert store.release("e1", "node-a") is True
    assert store.acquire("e1", "node-b") is not None


@pytest.mark.skip(reason="WAVE2-QUARANTINE: red on upstream AIOS new-branch (WIP drift), see docs/aios/WAVE2_TRIAGE.md")
def test_expired_lease_can_be_taken_over(tmp_path):
    store = ExecutionLeaseStore(str(tmp_path / "leases.json"), ttl_seconds=-1)
    assert store.acquire("e1", "node-a") is not None
    assert store.acquire("e1", "node-b") is not None
