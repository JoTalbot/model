import time
from unittest.mock import AsyncMock

import pytest

from swarm.chat.room import ChatMessage
from swarm.chat.selector import LLMSelector, RoundRobinSelector


def test_round_robin_cycles():
    selector = RoundRobinSelector()
    agents = ["parser", "analyst", "manager"]
    msgs = []

    assert selector.select(agents, msgs) == "parser"
    assert selector.select(agents, msgs) == "analyst"
    assert selector.select(agents, msgs) == "manager"
    assert selector.select(agents, msgs) == "parser"


@pytest.mark.asyncio
async def test_llm_selector_valid_response():
    mock_llm = AsyncMock()
    mock_llm.complete = AsyncMock(return_value="analyst")

    selector = LLMSelector(llm=mock_llm)
    agents = ["parser", "analyst", "manager"]
    messages = [
        ChatMessage(agent_name="parser", role="Парсер", content="Нашёл данные", round_num=1, timestamp=time.time())
    ]

    result = await selector.select(agents, messages)
    assert result == "analyst"


@pytest.mark.asyncio
async def test_llm_selector_invalid_response_falls_back():
    mock_llm = AsyncMock()
    mock_llm.complete = AsyncMock(return_value="unknown_agent_xyz")

    selector = LLMSelector(llm=mock_llm)
    agents = ["parser", "analyst", "manager"]
    messages = [
        ChatMessage(agent_name="parser", role="Парсер", content="test", round_num=1, timestamp=time.time())
    ]

    result = await selector.select(agents, messages)
    assert result in agents


@pytest.mark.asyncio
async def test_llm_selector_excludes_last_speaker():
    mock_llm = AsyncMock()
    mock_llm.complete = AsyncMock(return_value="analyst")

    selector = LLMSelector(llm=mock_llm)
    agents = ["parser", "analyst", "manager"]
    messages = [
        ChatMessage(agent_name="analyst", role="Аналитик", content="already spoke", round_num=1, timestamp=time.time())
    ]

    result = await selector.select(agents, messages)
    assert result == "analyst"
