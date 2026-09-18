import time
from unittest.mock import AsyncMock

import pytest

from swarm.chat.participant import AgentParticipant
from swarm.chat.room import ChatMessage


@pytest.mark.asyncio
async def test_participant_respond():
    mock_llm = AsyncMock()
    mock_llm.complete = AsyncMock(return_value="Цена лобового: 3000₽")

    participant = AgentParticipant(
        name="parser",
        role="Парсер цен",
        system_prompt="Ты — парсер. Ищи цены.",
        llm=mock_llm,
    )

    messages = [
        ChatMessage(
            agent_name="user",
            role="user",
            content="Найди цены на лобовое ВАЗ 2114",
            round_num=0,
            timestamp=time.time(),
        )
    ]

    result = await participant.respond(messages)
    assert result == "Цена лобового: 3000₽"

    call_args = mock_llm.complete.call_args[0][0]
    assert call_args[0]["role"] == "system"
    assert "парсер" in call_args[0]["content"].lower()
    assert call_args[-1]["role"] == "user"


@pytest.mark.asyncio
async def test_participant_uses_specified_model():
    mock_llm = AsyncMock()
    mock_llm.complete = AsyncMock(return_value="ok")

    participant = AgentParticipant(
        name="analyst",
        role="Аналитик",
        system_prompt="Ты — аналитик.",
        llm=mock_llm,
        model="anthropic/claude-sonnet-4-20250514",
    )

    messages = [
        ChatMessage(agent_name="user", role="user", content="test", round_num=0, timestamp=0)
    ]
    await participant.respond(messages)

    call_kwargs = mock_llm.complete.call_args[1]
    assert call_kwargs.get("model") == "anthropic/claude-sonnet-4-20250514"
