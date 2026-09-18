from unittest.mock import AsyncMock

import pytest

from swarm.agent.core import SwarmAgent, Task, TaskStatus


@pytest.fixture
def mock_deps():
    memory = AsyncMock()
    memory.store = AsyncMock(return_value="block-123")
    memory.retrieve = AsyncMock(return_value=None)
    memory.search = AsyncMock(return_value=[])
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value="LLM says hello")
    gossip = AsyncMock()
    gossip.inject = AsyncMock()
    rpc_client = AsyncMock()
    rpc_client.call = AsyncMock(return_value={"status": "ok"})
    return memory, llm, gossip, rpc_client


@pytest.fixture
def agent(mock_deps):
    memory, llm, gossip, rpc_client = mock_deps
    return SwarmAgent(
        node_id="agent-1",
        memory=memory,
        llm=llm,
        gossip=gossip,
        rpc_client=rpc_client,
    )


def test_agent_creation(agent):
    assert agent.node_id == "agent-1"
    assert agent.skills == {}


@pytest.mark.asyncio
async def test_agent_think(agent):
    result = await agent.think("What is 2+2?")
    assert result == "LLM says hello"
    agent.llm.complete.assert_called_once()


@pytest.mark.asyncio
async def test_agent_submit_task(agent):
    task = Task(description="Parse prices", creator_id="agent-1")
    await agent.submit_task(task)
    assert task.status == TaskStatus.PENDING
    agent.gossip.inject.assert_called_once()


@pytest.mark.asyncio
async def test_execute_task_uses_memory_port_when_set(mock_deps):
    memory, llm, gossip, rpc_client = mock_deps
    port = AsyncMock()
    port.put = AsyncMock(return_value="ref:swarm:abc")
    agent = SwarmAgent(
        node_id="agent-1",
        memory=memory,
        llm=llm,
        gossip=gossip,
        rpc_client=rpc_client,
        memory_port=port,
    )
    task = Task(description="Do X", creator_id="agent-1")
    await agent._execute_task(task)
    port.put.assert_awaited_once()
    memory.store.assert_not_called()


@pytest.mark.asyncio
async def test_execute_task_falls_back_to_memory_without_port(mock_deps):
    memory, llm, gossip, rpc_client = mock_deps
    agent = SwarmAgent(
        node_id="agent-1",
        memory=memory,
        llm=llm,
        gossip=gossip,
        rpc_client=rpc_client,
    )
    task = Task(description="Do Y", creator_id="agent-1")
    await agent._execute_task(task)
    memory.store.assert_awaited_once()
