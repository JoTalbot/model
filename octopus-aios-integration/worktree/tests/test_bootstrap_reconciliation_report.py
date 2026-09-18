import pytest

from swarm.tools_runtime.execution_audit import ExecutionAuditLog
from swarm.tools_runtime.execution_commit import (
    ExecutionCommit,
    ExecutionCommitCoordinator,
)
from swarm.tools_runtime.execution_lease import ExecutionLeaseStore
from swarm.tools_runtime.execution_store import ExecutionState, ExecutionStore
from swarm.tools_runtime.runtime_bootstrap import RuntimeBootstrap


@pytest.mark.asyncio
async def test_bootstrap_reports_reconciled_commit(tmp_path):
    store = ExecutionStore(str(tmp_path / "executions.json"))
    audit = ExecutionAuditLog(str(tmp_path / "audit.jsonl"))
    leases = ExecutionLeaseStore(str(tmp_path / "leases.json"), ttl_seconds=60)
    store.save(ExecutionState("e1", status="running", goal="recover"))
    coordinator = ExecutionCommitCoordinator(store, audit, str(tmp_path / "commits.jsonl"))
    coordinator._append_journal(ExecutionCommit("c1", "e1", "running", "completed", 0, checkpoint="done"))
    bootstrap = RuntimeBootstrap(store=store, lease_store=leases, commit_coordinator=coordinator)

    report = await bootstrap.recover_pending(lambda state: pytest.fail("reconciled execution should not be resumed"))

    assert report.reconciled == 1
    assert report.reconciliation_failed == 0
    assert report.discovered == 0
    assert store.get("e1").status == "completed"
