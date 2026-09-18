from unittest.mock import AsyncMock

import pytest

from swarm.agent.core import Task
from swarm.agent.task_manager import TaskManager


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value='["Parse prices from site A", "Parse prices from site B", "Aggregate results"]')
    return llm


@pytest.fixture
def manager(mock_llm):
    return TaskManager(llm=mock_llm, node_id="coordinator-1")


@pytest.mark.asyncio
async def test_decompose_creates_subtasks(manager):
    task = Task(description="Parse prices from 2 sites and aggregate", creator_id="user")
    subtasks = await manager.decompose(task)
    assert len(subtasks) == 3
    assert all(isinstance(t, Task) for t in subtasks)


@pytest.mark.asyncio
async def test_decompose_sets_creator_to_coordinator(manager):
    task = Task(description="Do something complex", creator_id="user")
    subtasks = await manager.decompose(task)
    assert all(t.creator_id == "coordinator-1" for t in subtasks)


@pytest.mark.asyncio
async def test_decompose_handles_single_task(manager):
    manager.llm.complete = AsyncMock(return_value='["Just do this one thing"]')
    task = Task(description="Simple task", creator_id="user")
    subtasks = await manager.decompose(task)
    assert len(subtasks) == 1


@pytest.mark.asyncio
async def test_decompose_handles_invalid_json(manager):
    manager.llm.complete = AsyncMock(return_value="Not valid JSON at all")
    task = Task(description="Something", creator_id="user")
    subtasks = await manager.decompose(task)
    assert len(subtasks) == 1
    assert subtasks[0].description == task.description
