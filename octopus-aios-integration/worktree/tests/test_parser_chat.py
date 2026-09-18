"""Тесты для ParserParticipant — интеграция парсера с чатом."""

from unittest.mock import AsyncMock

import pytest

from swarm.chat.participant import ParserParticipant
from swarm.chat.room import ChatMessage
from swarm.parser.models import ParsedItem, ParseResult


def _make_messages(user_text: str = "найди цены на лобовое стекло lada granta") -> list[ChatMessage]:
    return [
        ChatMessage(agent_name="user", role="user", content=user_text, round_num=0),
    ]


def _mock_pipeline(results: list[ParseResult]):
    pipeline = AsyncMock()
    pipeline.run = AsyncMock(return_value=results)
    return pipeline


class TestParserParticipant:
    @pytest.mark.asyncio
    async def test_injects_parse_results_into_prompt(self):
        """Результаты парсера вставляются в extra_system перед LLM."""
        llm = AsyncMock()
        llm.complete = AsyncMock(return_value="Нашёл стекло за 5000 руб")

        results = [
            ParseResult(
                source_url="https://shop.example.com",
                items=[
                    ParsedItem(name="Лобовое Granta", price="5000", currency="RUB", shop="GlassShop"),
                ],
            )
        ]
        pipeline = _mock_pipeline(results)

        participant = ParserParticipant(
            name="parser",
            role="парсер",
            system_prompt="Ты парсер цен.",
            llm=llm,
            pipeline=pipeline,
        )

        messages = _make_messages("цены на лобовое стекло lada granta")
        response = await participant.respond(messages)

        assert response == "Нашёл стекло за 5000 руб"

        # Проверяем, что LLM получил промпт с [PARSE] данными
        call_args = llm.complete.call_args[0][0]
        system_msg = call_args[0]["content"]
        assert "[PARSE]" in system_msg
        assert "Лобовое Granta" in system_msg
        assert "5000" in system_msg
        assert "GlassShop" in system_msg

        # Pipeline вызван в search-режиме (нет URL в тексте)
        pipeline.run.assert_called_once()
        call_kwargs = pipeline.run.call_args
        assert call_kwargs[1]["search"] is True

    @pytest.mark.asyncio
    async def test_url_mode_when_url_in_message(self):
        """Если в сообщении есть URL, pipeline запускается в URL-режиме."""
        llm = AsyncMock()
        llm.complete = AsyncMock(return_value="Результат")

        results = [ParseResult(source_url="https://shop.com", items=[])]
        pipeline = _mock_pipeline(results)

        participant = ParserParticipant(
            name="parser",
            role="парсер",
            system_prompt="Ты парсер.",
            llm=llm,
            pipeline=pipeline,
        )

        messages = _make_messages("https://shop.com/catalog")
        await participant.respond(messages)

        call_kwargs = pipeline.run.call_args
        assert call_kwargs[1]["search"] is False

    @pytest.mark.asyncio
    async def test_no_items_injects_warning(self):
        """Когда парсер не нашёл товаров — LLM получает предупреждение."""
        llm = AsyncMock()
        llm.complete = AsyncMock(return_value="К сожалению, ничего не найдено")

        results = [
            ParseResult(
                source_url="https://empty.com",
                items=[],
                errors=["timeout"],
            )
        ]
        pipeline = _mock_pipeline(results)

        participant = ParserParticipant(
            name="parser",
            role="парсер",
            system_prompt="Ты парсер.",
            llm=llm,
            pipeline=pipeline,
        )

        messages = _make_messages("стекло bmw x5 цена")
        await participant.respond(messages)

        system_msg = llm.complete.call_args[0][0][0]["content"]
        assert "[PARSE] No usable results" in system_msg
        assert "timeout" in system_msg

    @pytest.mark.asyncio
    async def test_pipeline_exception_does_not_crash(self):
        """Если pipeline крашится, парсер всё равно отвечает."""
        llm = AsyncMock()
        llm.complete = AsyncMock(return_value="Ответ без парсера")

        pipeline = AsyncMock()
        pipeline.run = AsyncMock(side_effect=RuntimeError("network down"))

        participant = ParserParticipant(
            name="parser",
            role="парсер",
            system_prompt="Ты парсер.",
            llm=llm,
            pipeline=pipeline,
        )

        messages = _make_messages("запрос")
        response = await participant.respond(messages)

        assert response == "Ответ без парсера"
        system_msg = llm.complete.call_args[0][0][0]["content"]
        assert "[PARSE] Pipeline error" in system_msg

    @pytest.mark.asyncio
    async def test_no_pipeline_behaves_like_normal(self):
        """Без pipeline ParserParticipant работает как обычный AgentParticipant."""
        llm = AsyncMock()
        llm.complete = AsyncMock(return_value="Обычный ответ")

        participant = ParserParticipant(
            name="parser",
            role="парсер",
            system_prompt="Ты парсер.",
            llm=llm,
            pipeline=None,
        )

        messages = _make_messages("привет")
        response = await participant.respond(messages)

        assert response == "Обычный ответ"
        system_msg = llm.complete.call_args[0][0][0]["content"]
        assert "[PARSE]" not in system_msg

    @pytest.mark.asyncio
    async def test_extra_system_combined_with_parse(self):
        """extra_system от ChatRoom и результаты парсера объединяются."""
        llm = AsyncMock()
        llm.complete = AsyncMock(return_value="ok")

        results = [
            ParseResult(
                source_url="https://shop.com",
                items=[ParsedItem(name="Glass", price="100")],
            )
        ]
        pipeline = _mock_pipeline(results)

        participant = ParserParticipant(
            name="parser",
            role="парсер",
            system_prompt="Ты парсер.",
            llm=llm,
            pipeline=pipeline,
        )

        messages = _make_messages("запрос")
        await participant.respond(
            messages,
            extra_system="Rolling context: предыдущий разговор...",
        )

        system_msg = llm.complete.call_args[0][0][0]["content"]
        assert "[PARSE]" in system_msg
        assert "Rolling context" in system_msg

    @pytest.mark.asyncio
    async def test_multiple_sources(self):
        """Несколько источников — все попадают в промпт."""
        llm = AsyncMock()
        llm.complete = AsyncMock(return_value="анализ цен")

        results = [
            ParseResult(
                source_url="https://shop1.com",
                items=[ParsedItem(name="A", price="100", currency="RUB")],
            ),
            ParseResult(
                source_url="https://shop2.com",
                items=[ParsedItem(name="B", price="200", currency="RUB")],
            ),
        ]
        pipeline = _mock_pipeline(results)

        participant = ParserParticipant(
            name="parser",
            role="парсер",
            system_prompt="Ты парсер.",
            llm=llm,
            pipeline=pipeline,
        )

        messages = _make_messages("цены на стекло")
        await participant.respond(messages)

        system_msg = llm.complete.call_args[0][0][0]["content"]
        assert "shop1.com" in system_msg
        assert "shop2.com" in system_msg
        assert "A" in system_msg
        assert "B" in system_msg

    @pytest.mark.asyncio
    async def test_no_user_message_skips_pipeline(self):
        """Если нет пользовательского сообщения — pipeline не запускается."""
        llm = AsyncMock()
        llm.complete = AsyncMock(return_value="ответ")

        pipeline = _mock_pipeline([])

        participant = ParserParticipant(
            name="parser",
            role="парсер",
            system_prompt="Ты парсер.",
            llm=llm,
            pipeline=pipeline,
        )

        # Только сообщения от агентов, нет user
        messages = [
            ChatMessage(agent_name="analyst", role="analyst", content="предложение", round_num=1),
        ]
        await participant.respond(messages)

        pipeline.run.assert_not_called()
