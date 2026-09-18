from __future__ import annotations

import logging
from dataclasses import dataclass, field

from swarm.chat.history import truncate_messages_for_chars
from swarm.chat.room import ChatMessage

logger = logging.getLogger(__name__)


@dataclass
class AgentParticipant:
    name: str
    role: str
    system_prompt: str
    llm: object
    model: str | None = None

    async def respond(
        self,
        messages: list[ChatMessage],
        *,
        max_context_chars: int | None = None,
        extra_system: str | None = None,
    ) -> str:
        prompt_msgs = messages
        if max_context_chars is not None:
            prompt_msgs = truncate_messages_for_chars(messages, max_context_chars)

        system_prompt = self.system_prompt
        if extra_system is not None:
            extra = extra_system.strip()
            if extra:
                system_prompt = f"{self.system_prompt}\n\n{extra}"

        prompt_messages = [{"role": "system", "content": system_prompt}]

        for msg in prompt_msgs:
            role = "assistant" if msg.agent_name == self.name else "user"
            prefix = f"[{msg.agent_name}] " if msg.agent_name != self.name else ""
            prompt_messages.append({"role": role, "content": f"{prefix}{msg.content}"})

        kwargs = {}
        if self.model:
            kwargs["model"] = self.model

        response = await self.llm.complete(prompt_messages, **kwargs)
        return response


@dataclass
class ParserParticipant(AgentParticipant):
    """AgentParticipant с автоматическим вызовом WebParserPipeline.

    Перед каждым ответом парсера, pipeline запускается на последнем
    пользовательском сообщении. Результаты инжектируются в промпт
    как дополнительный системный контекст.

    Если pipeline возвращает ошибки — LLM получает ``[PARSE] No usable
    results: ...`` чтобы не галлюцинировать цены.
    """

    pipeline: object | None = field(default=None, repr=False)

    async def respond(
        self,
        messages: list[ChatMessage],
        *,
        max_context_chars: int | None = None,
        extra_system: str | None = None,
    ) -> str:
        # Находим последнее пользовательское сообщение
        user_text = ""
        for msg in reversed(messages):
            if msg.agent_name == "user":
                user_text = msg.content
                break

        # Запускаем pipeline, если есть
        parse_context = ""
        if self.pipeline is not None and user_text:
            parse_context = await self._run_pipeline(user_text)

        # Собираем extra_system
        parts: list[str] = []
        if parse_context:
            parts.append(parse_context)
        if extra_system:
            parts.append(extra_system)

        combined_extra = "\n\n".join(parts) if parts else None

        return await super().respond(
            messages,
            max_context_chars=max_context_chars,
            extra_system=combined_extra,
        )

    async def _run_pipeline(self, user_text: str) -> str:
        """Запустить WebParserPipeline и вернуть форматированный контекст."""
        from swarm.parser.pipeline import _looks_like_url

        try:
            search = not _looks_like_url(user_text)
            results = await self.pipeline.run(
                user_text,
                search=search,
                limit=3,
            )
        except Exception as exc:
            logger.warning("Parser pipeline failed for chat: %s", exc)
            return f"[PARSE] Pipeline error: {exc}"

        lines: list[str] = []
        has_items = False

        for r in results:
            if r.items:
                has_items = True
                lines.append(f"Источник: {r.source_url}")
                for item in r.items:
                    parts = [f"  • {item.name}"]
                    if item.price:
                        parts.append(f"цена: {item.price}")
                    if item.currency:
                        parts.append(item.currency)
                    if item.shop:
                        parts.append(f"магазин: {item.shop}")
                    if item.in_stock is not None:
                        parts.append("в наличии" if item.in_stock else "нет в наличии")
                    lines.append(" — ".join(parts))
            elif r.errors:
                lines.append(f"Источник: {r.source_url} — ошибки: {', '.join(r.errors)}")

        if not has_items:
            all_errors = []
            for r in results:
                all_errors.extend(r.errors)
            return f"[PARSE] No usable results: {'; '.join(all_errors) or 'empty items'}"

        return "[PARSE] Данные с веба:\n" + "\n".join(lines)
