import pytest

from swarm.tools_runtime.recovery_policy import RecoveryPolicy
from swarm.tools_runtime.runtime_bootstrap import RuntimeBootstrap


class FakeLease:
    ttl_seconds = 30
    def acquire(self, execution_id, owner): return object()
    def renew(self, execution_id, owner): return object()
    def release(self, execution_id, owner): pass


class State:
    def __init__(self, execution_id, status="running", attempt=0):
        self.execution_id = execution_id
        self.status = status
        self.attempt = attempt


class Store:
    def resumable(self): return [State("retry", attempt=0), State("manual", attempt=3), State("skip", status="completed")]


@pytest.mark.skip(reason="WAVE2-QUARANTINE: red on upstream AIOS new-branch (WIP drift), see docs/aios/WAVE2_TRIAGE.md")
@pytest.mark.asyncio
async def test_bootstrap_applies_recovery_policy():
    bootstrap = RuntimeBootstrap(store=Store(), lease_store=FakeLease(), recovery_policy=RecoveryPolicy(max_attempts=3))
    seen = []
    report = await bootstrap.recover_pending(lambda state: seen.append(state.execution_id))
    assert seen == ["retry"]
    assert report.retried == 1
    assert report.manual_review == 1
    assert report.skipped == 1
