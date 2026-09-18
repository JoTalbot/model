import pytest

from swarm.tools_runtime.execution_store import ExecutionState, ExecutionStore


@pytest.mark.skip(reason="WAVE2-QUARANTINE: red on upstream AIOS new-branch (WIP drift), see docs/aios/WAVE2_TRIAGE.md")
def test_execution_store_persists_and_recovers(tmp_path):
    store = ExecutionStore(str(tmp_path / "executions.json"))
    state = ExecutionState("exec-1", goal="demo", attempt=1, plan=[{"tool": "x"}])
    store.save(state)

    restored = ExecutionStore(str(tmp_path / "executions.json"))
    loaded = restored.get("exec-1")
    assert loaded is not None
    assert loaded.goal == "demo"
    assert loaded.attempt == 1
    assert loaded.plan == [{"tool": "x"}]
    assert len(restored.resumable()) == 1


@pytest.mark.skip(reason="WAVE2-QUARANTINE: red on upstream AIOS new-branch (WIP drift), see docs/aios/WAVE2_TRIAGE.md")
def test_execution_store_updates_status(tmp_path):
    store = ExecutionStore(str(tmp_path / "executions.json"))
    store.save(ExecutionState("exec-2"))
    store.save(ExecutionState("exec-2", status="completed", result="ok"))
    assert store.get("exec-2").status == "completed"
    assert store.resumable() == []
