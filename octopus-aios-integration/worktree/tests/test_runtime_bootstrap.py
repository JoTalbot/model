import pytest

from swarm.tools_runtime.execution_store import ExecutionState, ExecutionStore
from swarm.tools_runtime.runtime_bootstrap import RuntimeBootstrap


@pytest.mark.asyncio
async def test_bootstrap_recovers_all_pending_executions(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # stores default to CWD-relative data/
    store = ExecutionStore(str(tmp_path / "executions.json"))
    store.save(ExecutionState("e1", status="running", goal="one"))
    store.save(ExecutionState("e2", status="running", goal="two"))
    store.save(ExecutionState("e3", status="completed", goal="done"))

    recovered = []

    async def resume(state):
        recovered.append(state.execution_id)

    report = await RuntimeBootstrap(store=store).recover_pending(resume)

    assert report.discovered == 2
    assert report.attempted == 2
    assert report.recovered == 2
    assert report.failed == 0
    assert recovered == ["e1", "e2"]


@pytest.mark.asyncio
async def test_bootstrap_isolates_recovery_failures(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # stores default to CWD-relative data/
    store = ExecutionStore(str(tmp_path / "executions.json"))
    store.save(ExecutionState("ok", status="running"))
    store.save(ExecutionState("bad", status="running"))

    async def resume(state):
        if state.execution_id == "bad":
            raise RuntimeError("cannot restore")

    report = await RuntimeBootstrap(store=store).recover_pending(resume)
    assert report.recovered == 1
    assert report.failed == 1
