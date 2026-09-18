from swarm.tools_runtime.execution_lease import ExecutionLeaseStore


def test_owner_can_renew_active_lease(tmp_path):
    store = ExecutionLeaseStore(str(tmp_path / "leases.json"), ttl_seconds=60)
    first = store.acquire("e1", "node-a")
    renewed = store.renew("e1", "node-a")
    assert first is not None
    assert renewed is not None
    assert renewed.owner_id == "node-a"
    assert store.is_owner("e1", "node-a")


def test_non_owner_cannot_renew_lease(tmp_path):
    store = ExecutionLeaseStore(str(tmp_path / "leases.json"), ttl_seconds=60)
    store.acquire("e1", "node-a")
    assert store.renew("e1", "node-b") is None
    assert store.is_owner("e1", "node-a")
