import pytest

from swarm.tools_runtime.recovery_policy import RecoveryPolicy
from swarm.tools_runtime.recovery_queue import RecoveryQueue
from swarm.tools_runtime.runtime_bootstrap import RuntimeBootstrap


class Lease:
    ttl_seconds = 30
    def acquire(self, execution_id, owner): return object()
    def renew(self, execution_id, owner): return object()
    def release(self, execution_id, owner): pass


class State:
    def __init__(self, execution_id, status="running", attempt=0, correlation_id=None):
        self.execution_id = execution_id
        self.status = status
        self.attempt = attempt
        self.correlation_id = correlation_id


class Store:
    def resumable(self): return [State("manual", attempt=3, correlation_id="corr-9")]


@pytest.mark.asyncio
async def test_manual_review_is_persisted(tmp_path):
    queue = RecoveryQueue(str(tmp_path / "queue.jsonl"))
    bootstrap = RuntimeBootstrap(store=Store(), lease_store=Lease(), recovery_policy=RecoveryPolicy(max_attempts=3), recovery_queue=queue)
    report = await bootstrap.recover_pending(lambda state: None)
    items = queue.items(action="manual_review", unresolved_only=True)
    assert report.manual_review == 1
    assert len(items) == 1
    assert items[0].correlation_id == "corr-9"
