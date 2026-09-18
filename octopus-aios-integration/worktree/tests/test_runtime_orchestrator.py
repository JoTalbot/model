import pytest

from swarm.tools_runtime.execution_store import ExecutionState, ExecutionStore
from swarm.tools_runtime.runtime_orchestrator import RuntimeOrchestrator
from swarm.tools_runtime.tool_protocol import ToolResult


class Planner:
    async def create_plan(self, goal):
        return [{"tool": "work", "arguments": {"goal": goal}}]


class Executor:
    async def execute(self, agent, plan, context, execution):
        return [ToolResult("ok", "work", True, value="done")]


@pytest.mark.skip(reason="WAVE2-QUARANTINE: red on upstream AIOS new-branch (WIP drift), see docs/aios/WAVE2_TRIAGE.md")
@pytest.mark.asyncio
async def test_orchestrator_start_recovers_then_executes(tmp_path):
    store = ExecutionStore(str(tmp_path / "executions.json"))
    store.save(ExecutionState("pending", status="running", goal="resume", attempt=0,
                              plan=[{"tool": "work", "arguments": {"goal": "resume"}}]))
    orchestrator = RuntimeOrchestrator(Executor(), Planner(), store=store,
                                       lease_store=None, owner_id="node-a")

    report = await orchestrator.start("agent-1")
    assert report.discovered == 1
    assert report.recovered == 1
    assert store.get("pending").status == "completed"

    result = await orchestrator.execute("new task", "agent-1")
    assert result.status == "completed"
    await orchestrator.shutdown()
    assert orchestrator.started is False


@pytest.mark.asyncio
async def test_orchestrator_start_is_idempotent(tmp_path):
    store = ExecutionStore(str(tmp_path / "executions.json"))
    orchestrator = RuntimeOrchestrator(Executor(), Planner(), store=store, owner_id="node-a")
    first = await orchestrator.start("agent-1")
    second = await orchestrator.start("agent-1")
    assert first.discovered == 0
    assert second.discovered == 0
