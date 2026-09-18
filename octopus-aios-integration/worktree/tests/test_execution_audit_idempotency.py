from swarm.tools_runtime.execution_audit import ExecutionAuditEvent, ExecutionAuditLog
from swarm.tools_runtime.execution_store import ExecutionState, ExecutionStore


def test_duplicate_audit_event_is_idempotent(tmp_path):
    log = ExecutionAuditLog(str(tmp_path / "audit.jsonl"))
    event = ExecutionAuditEvent("e1", "running", "completed", attempt=1, timestamp="2026-08-26T00:00:00+00:00")
    first = log.append(event)
    second = log.append(event)
    assert first.event_id == second.event_id
    assert len(log.events("e1")) == 1


def test_correlation_id_survives_store_and_audit(tmp_path):
    log = ExecutionAuditLog(str(tmp_path / "audit.jsonl"))
    store = ExecutionStore(str(tmp_path / "executions.json"), audit_log=log)
    store.save(ExecutionState("e1", correlation_id="corr-1"))
    store.transition("e1", "running")
    event = log.events("e1")[0]
    assert event.correlation_id == "corr-1"
