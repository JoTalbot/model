from swarm.tools_runtime.execution_audit import ExecutionAuditLog
from swarm.tools_runtime.execution_commit import ExecutionCommitCoordinator
from swarm.tools_runtime.execution_store import ExecutionState, ExecutionStore


def test_commit_persists_state_and_audit(tmp_path):
    store = ExecutionStore(str(tmp_path / "executions.json"))
    audit = ExecutionAuditLog(str(tmp_path / "audit.jsonl"))
    coordinator = ExecutionCommitCoordinator(store, audit, str(tmp_path / "commits.jsonl"))
    store.save(ExecutionState("e1", status="pending", correlation_id="corr-1"))
    coordinator.commit(store.get("e1"), "running", reason="worker-start")
    assert store.get("e1").status == "running"
    assert len(audit.events("e1")) == 1


def test_reconcile_repairs_interrupted_commit(tmp_path):
    store = ExecutionStore(str(tmp_path / "executions.json"))
    audit = ExecutionAuditLog(str(tmp_path / "audit.jsonl"))
    coordinator = ExecutionCommitCoordinator(store, audit, str(tmp_path / "commits.jsonl"))
    store.save(ExecutionState("e1", status="pending"))
    _commit = coordinator.commit
    from swarm.tools_runtime.execution_commit import ExecutionCommit
    coordinator._append_journal(ExecutionCommit("c1", "e1", "pending", "running", 0, reason="crash"))
    repaired = coordinator.reconcile()
    assert repaired == ["c1"]
    assert store.get("e1").status == "running"
    assert audit.events("e1")[0].event_id == "c1"
