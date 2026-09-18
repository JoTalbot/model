import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from swarm.tools_runtime.api_kit.app import create_app
from swarm.tools_runtime.api_kit.security import OperatorRole, SecurityContext
from swarm.tools_runtime.recovery_api import RecoveryOperatorService
from swarm.tools_runtime.recovery_queue import RecoveryQueue, RecoveryQueueItem


def context(role, correlation_id="corr-test"):
    return SecurityContext(actor="alice", role=role, correlation_id=correlation_id)


@pytest.mark.parametrize("role,mutation_status", [
    (OperatorRole.VIEWER, 403),
    (OperatorRole.OPERATOR, 200),
    (OperatorRole.ADMIN, 200),
])
def test_recovery_mutation_rbac(role, mutation_status, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # operator audit defaults to CWD-relative data/
    queue = RecoveryQueue(str(tmp_path / "queue.jsonl"))
    queue.enqueue(RecoveryQueueItem("e1", "manual_review", "operator action", 3, "corr-1"))
    service = RecoveryOperatorService(queue=queue)
    app = create_app(recovery_service=service, operator_validator=lambda request: context(role))
    response = TestClient(app).post("/recovery/resolve", json={"execution_id": "e1", "action": "manual_review", "reason": "approved"})
    assert response.status_code == mutation_status


def test_correlation_propagates_to_audit(tmp_path):
    queue = RecoveryQueue(str(tmp_path / "queue.jsonl"))
    queue.enqueue(RecoveryQueueItem("e2", "manual_review", "needs review", 3, "corr-77"))
    from swarm.tools_runtime.operator_audit import OperatorAuditLog
    service = RecoveryOperatorService(queue=queue, audit_log=OperatorAuditLog(str(tmp_path / "audit.jsonl")))
    app = create_app(recovery_service=service, operator_validator=lambda request: context(OperatorRole.OPERATOR, "corr-99"))
    response = TestClient(app).post("/recovery/resolve", json={"execution_id": "e2", "action": "manual_review"})
    assert response.status_code == 200
    event = service.audit_events()[-1]
    assert event["actor"] == "alice"
    assert event["correlation_id"] == "corr-99"
    assert event["outcome"] == "resolved"
