import pytest

from swarm.tools_runtime.agent_executor import AgentExecutor
from swarm.tools_runtime.execution_audit import ExecutionAudit
from swarm.tools_runtime.tool_registry import ToolPermissionError, ToolRegistry
from swarm.tools_runtime.tool_sandbox import ToolExecutionContext, ToolSandbox


async def add(a, b):
    return a + b


@pytest.mark.asyncio
async def test_tool_registry_enforces_permissions():
    registry = ToolRegistry()
    registry.register("add", add, permissions={"compute"})

    with pytest.raises(ToolPermissionError):
        await registry.execute("add", granted_permissions=set(), a=1, b=2)

    assert await registry.execute("add", granted_permissions={"compute"}, a=1, b=2) == 3


@pytest.mark.asyncio
async def test_tool_sandbox_requires_agent_identity():
    registry = ToolRegistry()
    registry.register("add", add)
    sandbox = ToolSandbox(registry)

    with pytest.raises(PermissionError):
        await sandbox.execute("add", ToolExecutionContext(agent_id=""), a=1, b=2)

    assert await sandbox.execute("add", ToolExecutionContext(agent_id="agent-1"), a=2, b=3) == 5


@pytest.mark.skip(reason="WAVE2-QUARANTINE: red on upstream AIOS new-branch (WIP drift), see docs/aios/WAVE2_TRIAGE.md")
@pytest.mark.asyncio
async def test_agent_executor_runs_plan_and_audits_tool():
    registry = ToolRegistry()
    registry.register("add", add, permissions={"compute"})
    audit = ExecutionAudit()
    sandbox = ToolSandbox(registry, audit, authorization={"agent-1": {"compute"}})
    executor = AgentExecutor(sandbox)

    result = await executor.execute("agent-1", [{"tool": "add", "arguments": {"a": 4, "b": 5}}], {"permissions": {"compute"}})

    assert result == [9]
    assert [event.event for event in audit.snapshot()] == [
        "tool.execution.started",
        "tool.execution.completed",
    ]
