from unittest.mock import AsyncMock

import pytest

from swarm.chat.participant import AgentParticipant
from swarm.chat.room import ChatConfig, ChatRoom
from swarm.chat.selector import LLMSelector, RoundRobinSelector


@pytest.mark.asyncio
async def test_full_chat_flow_with_three_agents():
    """Integration: three agents discuss a task and reach conclusion."""
    responses = iter([
        "Нашёл цены: ВАЗ 2114 лобовое — exist.ru 2800₽, bor-glass 2500₽",
        "Анализ: bor-glass дешевле на 12%. Рекомендую закупить там.",
        "Решение: заказываем 5 шт у bor-glass по 2500₽. Итого 12500₽. [DONE]",
    ])

    async def mock_complete(messages, **kwargs):
        return next(responses)

    mock_llm = AsyncMock()
    mock_llm.complete = mock_complete

    participants = [
        AgentParticipant(
            name="parser", role="Парсер цен",
            system_prompt="Ищи цены на автостёкла", llm=mock_llm,
        ),
        AgentParticipant(
            name="analyst", role="Аналитик рынка",
            system_prompt="Анализируй цены", llm=mock_llm,
        ),
        AgentParticipant(
            name="manager", role="Менеджер по закупкам",
            system_prompt="Принимай решения", llm=mock_llm,
        ),
    ]

    selector = RoundRobinSelector()
    config = ChatConfig(max_rounds=10, done_keyword="[DONE]")
    room = ChatRoom(participants=participants, selector=selector, config=config)

    result = await room.run("Найди цены на лобовое стекло ВАЗ 2114 и закажи")

    assert result.finished_naturally is True
    assert result.rounds_used == 3
    assert result.messages[1].agent_name == "parser"
    assert result.messages[2].agent_name == "analyst"
    assert result.messages[3].agent_name == "manager"
    assert "2500" in result.messages[1].content
    assert "[DONE]" in result.messages[3].content


@pytest.mark.asyncio
async def test_llm_selector_integration():
    """Integration: LLM selector picks the right agent."""
    call_count = {"n": 0}

    async def mock_complete(messages, **kwargs):
        call_count["n"] += 1
        if len(messages) == 1 and "who should speak" in messages[0]["content"].lower():
            return "analyst"
        return f"Response #{call_count['n']} [DONE]"

    mock_llm = AsyncMock()
    mock_llm.complete = mock_complete

    participants = [
        AgentParticipant(name="parser", role="Парсер", system_prompt="test", llm=mock_llm),
        AgentParticipant(name="analyst", role="Аналитик", system_prompt="test", llm=mock_llm),
    ]

    selector = LLMSelector(llm=mock_llm)
    config = ChatConfig(max_rounds=5, done_keyword="[DONE]")
    room = ChatRoom(participants=participants, selector=selector, config=config)

    result = await room.run("test task")

    assert result.messages[1].agent_name == "analyst"
    assert result.finished_naturally is True
