import time
from unittest.mock import AsyncMock

import pytest

from swarm.chat.budget import LLMCallBudget
from swarm.chat.participant import AgentParticipant
from swarm.chat.room import ChatConfig, ChatMessage, ChatResult, ChatRoom
from swarm.chat.selector import RoundRobinSelector


def test_chat_message_creation():
    msg = ChatMessage(
        agent_name="parser",
        role="Парсер цен",
        content="Нашёл цены",
        round_num=1,
        timestamp=time.time(),
    )
    assert msg.agent_name == "parser"
    assert msg.round_num == 1
    assert msg.content == "Нашёл цены"


def test_chat_result_creation():
    msg = ChatMessage(
        agent_name="manager",
        role="Менеджер",
        content="Заказываем [DONE]",
        round_num=3,
        timestamp=time.time(),
    )
    result = ChatResult(
        messages=[msg],
        rounds_used=3,
        finished_naturally=True,
        summary="Заказываем [DONE]",
    )
    assert result.finished_naturally is True
    assert result.rounds_used == 3
    assert len(result.messages) == 1


@pytest.mark.asyncio
async def test_chat_room_runs_to_completion():
    mock_llm_a = AsyncMock()
    mock_llm_a.complete = AsyncMock(return_value="Нашёл цены: 3000₽")

    mock_llm_b = AsyncMock()
    mock_llm_b.complete = AsyncMock(return_value="Анализ готов. Рекомендую. [DONE]")

    participants = [
        AgentParticipant(name="parser", role="Парсер", system_prompt="Ищи цены", llm=mock_llm_a),
        AgentParticipant(name="analyst", role="Аналитик", system_prompt="Анализируй", llm=mock_llm_b),
    ]

    selector = RoundRobinSelector()
    config = ChatConfig(max_rounds=10, done_keyword="[DONE]")

    room = ChatRoom(participants=participants, selector=selector, config=config)
    result = await room.run("Найди цены на лобовое ВАЗ 2114")

    assert result.finished_naturally is True
    assert result.rounds_used == 2
    assert len(result.messages) == 3  # user + parser + analyst
    assert "[DONE]" in result.messages[-1].content


@pytest.mark.asyncio
async def test_chat_room_respects_max_rounds():
    mock_llm = AsyncMock()
    mock_llm.complete = AsyncMock(return_value="Продолжаю работать...")

    participants = [
        AgentParticipant(name="parser", role="Парсер", system_prompt="test", llm=mock_llm),
        AgentParticipant(name="analyst", role="Аналитик", system_prompt="test", llm=mock_llm),
    ]

    selector = RoundRobinSelector()
    config = ChatConfig(max_rounds=3, done_keyword="[DONE]")

    room = ChatRoom(participants=participants, selector=selector, config=config)
    result = await room.run("тест")

    assert result.finished_naturally is False
    assert result.rounds_used == 3


@pytest.mark.asyncio
async def test_chat_room_step_by_step():
    mock_llm = AsyncMock()
    mock_llm.complete = AsyncMock(return_value="Ответ агента [DONE]")

    participants = [
        AgentParticipant(name="parser", role="Парсер", system_prompt="test", llm=mock_llm),
    ]

    selector = RoundRobinSelector()
    config = ChatConfig(max_rounds=5, done_keyword="[DONE]")

    room = ChatRoom(participants=participants, selector=selector, config=config)
    room.start("Тестовая задача")

    msg = await room.step()
    assert msg is not None
    assert msg.agent_name == "parser"

    msg2 = await room.step()
    assert msg2 is None  # finished because [DONE]


def test_chat_config_extended_defaults():
    from swarm.chat.room import ChatConfig

    c = ChatConfig()
    assert c.selector_max_llm_calls == 15
    assert c.summary_every_n_agent_messages == 0
    assert c.final_summary is False


@pytest.mark.asyncio
async def test_chat_room_stops_when_budget_exhausted():
    mock_llm = AsyncMock()
    mock_llm.complete = AsyncMock(return_value="more")

    participants = [
        AgentParticipant(name="a", role="agent", system_prompt="s", llm=mock_llm),
    ]
    config = ChatConfig(
        max_rounds=10,
        done_keyword="[DONE]",
        max_llm_calls_per_session=2,
        selector_max_llm_calls=5,
    )
    room = ChatRoom(participants=participants, selector=RoundRobinSelector(), config=config)
    result = await room.run("goal")

    assert result.end_reason == "LLM call budget exhausted"
    assert result.rounds_used == 1
    assert len(result.messages) == 2


@pytest.mark.asyncio
async def test_chat_room_records_llm_error_message():
    mock_llm = AsyncMock()
    mock_llm.complete = AsyncMock(side_effect=RuntimeError("llm down"))

    participants = [
        AgentParticipant(name="a", role="agent", system_prompt="s", llm=mock_llm),
    ]
    budget = LLMCallBudget(max_per_session=20, selector_max=10)
    room = ChatRoom(
        participants=participants,
        selector=RoundRobinSelector(),
        config=ChatConfig(max_rounds=1, done_keyword="[DONE]"),
        budget=budget,
    )
    result = await room.run("goal")

    assert any("[ERROR]" in m.content and "llm down" in m.content for m in result.messages)
    assert result.rounds_used == 1


@pytest.mark.asyncio
async def test_rolling_summary_triggers_every_n_agent_messages():
    summary_llm = AsyncMock()
    summary_llm.complete = AsyncMock(return_value="- item one")

    agent_llm = AsyncMock()
    agent_llm.complete = AsyncMock(side_effect=["first", "second"])

    participants = [
        AgentParticipant(name="a", role="agent", system_prompt="sys", llm=agent_llm),
    ]
    config = ChatConfig(
        max_rounds=2,
        done_keyword="[DONE]",
        summary_every_n_agent_messages=2,
        max_llm_calls_per_session=30,
        selector_max_llm_calls=10,
    )
    room = ChatRoom(
        participants=participants,
        selector=RoundRobinSelector(),
        config=config,
        summary_llm=summary_llm,
    )
    await room.run("goal")

    assert summary_llm.complete.await_count == 1
    assert "item one" in room.rolling_summary


@pytest.mark.asyncio
async def test_lan_hints_only_on_first_agent_turn():
    agent_llm = AsyncMock()
    agent_llm.complete = AsyncMock(side_effect=["one", "two"])

    summary_llm = AsyncMock()
    summary_llm.complete = AsyncMock(return_value="")

    participants = [
        AgentParticipant(name="a", role="agent", system_prompt="BASE", llm=agent_llm),
    ]
    config = ChatConfig(
        max_rounds=2,
        done_keyword="[DONE]",
        lan_hints=True,
        max_llm_calls_per_session=30,
        selector_max_llm_calls=10,
        summary_every_n_agent_messages=1,
    )
    room = ChatRoom(
        participants=participants,
        selector=RoundRobinSelector(),
        config=config,
        summary_llm=summary_llm,
        lan_peers_lines=["kad=8000 host=192.168.1.5"],
    )
    await room.run("goal")

    calls = agent_llm.complete.await_args_list
    first_system = calls[0].args[0][0]["content"]
    assert "LAN peers" in first_system
    assert "192.168.1.5" in first_system

    second_system = calls[1].args[0][0]["content"]
    assert "LAN peers" not in second_system


@pytest.mark.asyncio
async def test_final_summary_sets_epilogue():
    agent_llm = AsyncMock()
    agent_llm.complete = AsyncMock(return_value="done [DONE]")

    summary_llm = AsyncMock()
    summary_llm.complete = AsyncMock(return_value="EPILOGUE_TEXT")

    participants = [
        AgentParticipant(name="a", role="agent", system_prompt="s", llm=agent_llm),
    ]
    config = ChatConfig(
        max_rounds=5,
        done_keyword="[DONE]",
        final_summary=True,
        max_llm_calls_per_session=30,
        selector_max_llm_calls=10,
    )
    room = ChatRoom(
        participants=participants,
        selector=RoundRobinSelector(),
        config=config,
        summary_llm=summary_llm,
    )
    result = await room.run("goal")

    assert result.epilogue == "EPILOGUE_TEXT"
    assert summary_llm.complete.await_count == 1
