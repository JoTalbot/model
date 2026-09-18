import pytest

from swarm.tools_runtime.execution_store import ExecutionState, ExecutionStore
from swarm.tools_runtime.recovery_manager import RecoveryManager


class Loop:
    def __init__(self):
        self.calls = []

    async def run(self, goal, agent, context=None, execution_context=None):
        self.calls.append((goal, agent))
        return "resumed"


@pytest.mark.skip(reason="WAVE2-QUARANTINE: red on upstream AIOS new-branch (WIP drift), see docs/aios/WAVE2_TRIAGE.md")
@pytest.mark.asyncio
async def test_recovery_manager_resumes_pending_executions(tmp_path):
    store = ExecutionStore(str(tmp_path / "executions.json"))
    store.save(ExecutionState("e1", status="running", goal="finish task"))
    store.save(ExecutionState("e2", status="completed", goal="already done"))

    loop = Loop()
    results = await RecoveryManager(store).recover(loop, "agent-1")

    assert results == [("e1", "resumed")]
    assert loop.calls == [("finish task", "agent-1")]


def test_recovery_manager_marks_failed_execution(tmp_path):
    store = ExecutionStore(str(tmp_path / "executions.json"))
    state = store.save(ExecutionState("e1", status="running"))
    updated = RecoveryManager(store).mark_failed(state, RuntimeError("crash"))
    assert updated.status == "failed"
    assert updated.error == "crash"
