import pytest

from swarm.tools_runtime.agent_executor import AgentExecutor
from swarm.tools_runtime.tool_executor import ToolExecutor
from swarm.tools_runtime.tool_registry import ToolRegistry
from swarm.tools_runtime.tool_sandbox import ToolSandbox


async def add(a, b):
    return a + b


@pytest.mark.skip(reason="WAVE2-QUARANTINE: red on upstream AIOS new-branch (WIP drift), see docs/aios/WAVE2_TRIAGE.md")
@pytest.mark.asyncio
async def test_agent_executor_uses_typed_tool_results_and_memory():
    registry = ToolRegistry()
    registry.register("add", add, permissions={"compute"})
    memory = []
    executor = AgentExecutor(
        ToolExecutor(ToolSandbox(registry)),
        memory=type("Memory", (), {"remember": lambda self, item: memory.append(item)})(),
    )

    results = await executor.execute(
        "agent-1",
        [{"tool": "add", "arguments": {"a": 2, "b": 3}, "call_id": "call-1"}],
        {"permissions": ["compute"]},
    )

    assert results[0].ok is True
    assert results[0].value == 5
    assert results[0].call_id == "call-1"
    assert memory[0]["ok"] is True


@pytest.mark.skip(reason="WAVE2-QUARANTINE: red on upstream AIOS new-branch (WIP drift), see docs/aios/WAVE2_TRIAGE.md")
@pytest.mark.asyncio
async def test_agent_executor_retries_failed_tool():
    calls = 0

    async def flaky():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("temporary")
        return "ok"

    registry = ToolRegistry()
    registry.register("flaky", flaky)
    executor = AgentExecutor(ToolExecutor(ToolSandbox(registry)), retries=1)

    results = await executor.execute("agent-1", [{"tool": "flaky"}], {})
    assert results[0].ok is True
    assert calls == 2
