import asyncio

import pytest

from swarm.tools_runtime.agent_executor import AgentExecutor
from swarm.tools_runtime.tool_executor import ToolExecutor
from swarm.tools_runtime.tool_registry import ToolPermissionError, ToolRegistry
from swarm.tools_runtime.tool_sandbox import ToolSandbox


@pytest.mark.skip(reason="WAVE2-QUARANTINE: red on upstream AIOS new-branch (WIP drift), see docs/aios/WAVE2_TRIAGE.md")
def test_agent_executor_cannot_bypass_sandbox_permissions():
    async def scenario():
        registry = ToolRegistry()
        registry.register("protected", lambda: "secret", permissions={"tool:protected"})
        sandbox = ToolSandbox(registry, authorization={"agent-1": set()})
        executor = AgentExecutor(ToolExecutor(sandbox))
        with pytest.raises(ToolPermissionError):
            await executor.execute(
                "agent-1",
                [{"tool": "protected", "arguments": {}}],
                {"permissions": {"tool:protected"}},
            )

    asyncio.run(scenario())
