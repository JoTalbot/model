import time
from unittest.mock import AsyncMock

import pytest

from swarm.chat.participant import AgentParticipant
from swarm.chat.room import ChatMessage


@pytest.mark.asyncio
async def test_respond_truncates_when_max_context_chars_set():
    mock_llm = AsyncMock()
    mock_llm.complete = AsyncMock(return_value="ok")

    participant = AgentParticipant(
        name="parser",
        role="Парсер",
        system_prompt="SYS",
        llm=mock_llm,
    )

    messages = [
        ChatMessage(
            agent_name="user",
            role="user",
            content="x" * 10,
            round_num=i,
            timestamp=time.time(),
        )
        for i in range(15)
    ]

    await participant.respond(messages, max_context_chars=30)

    sent = mock_llm.complete.call_args[0][0]
    assert sent[0]["role"] == "system"
    assert len(sent) - 1 < len(messages)


@pytest.mark.asyncio
async def test_respond_appends_extra_system():
    mock_llm = AsyncMock()
    mock_llm.complete = AsyncMock(return_value="ok")

    participant = AgentParticipant(
        name="parser",
        role="Парсер",
        system_prompt="Base instructions here.",
        llm=mock_llm,
    )

    messages = [
        ChatMessage(agent_name="user", role="user", content="hi", round_num=0, timestamp=0)
    ]

    extra = "LAN peers: parser @ 192.168.1.5"
    await participant.respond(messages, extra_system=extra)

    sent = mock_llm.complete.call_args[0][0]
    system_content = sent[0]["content"]
    assert "Base instructions here." in system_content
    assert extra in system_content
