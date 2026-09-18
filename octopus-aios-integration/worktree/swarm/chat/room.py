from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from swarm.chat.participant import AgentParticipant

from swarm.chat.budget import BudgetExceeded, LLMCallBudget


@dataclass
class ChatMessage:
    agent_name: str
    role: str
    content: str
    round_num: int
    timestamp: float = field(default_factory=time.time)


@dataclass
class ChatResult:
    messages: list[ChatMessage]
    rounds_used: int
    finished_naturally: bool
    summary: str
    end_reason: str = ""
    epilogue: str = ""


@dataclass
class ChatConfig:
    max_rounds: int = 15
    done_keyword: str = "[DONE]"
    max_llm_calls_per_session: int = 30
    selector_max_llm_calls: int = 15
    max_context_chars: int = 12000
    retry_failed_round: bool = False
    summary_every_n_agent_messages: int = 0
    summary_model: str | None = None
    final_summary: bool = False
    lan_hints: bool = False


class ChatRoom:
    def __init__(
        self,
        participants: list[AgentParticipant],
        selector,
        config: ChatConfig,
        budget: LLMCallBudget | None = None,
        summary_llm: object | None = None,
        lan_peers_lines: list[str] | None = None,
    ) -> None:
        self.participants = {p.name: p for p in participants}
        self.selector = selector
        self.config = config
        self._budget = budget or LLMCallBudget(
            config.max_llm_calls_per_session,
            config.selector_max_llm_calls,
        )
        self.summary_llm = summary_llm
        self._lan_peers_lines = list(lan_peers_lines or [])
        self._lan_sent = False
        self.messages: list[ChatMessage] = []
        self._round = 0
        self._finished = False
        self._end_reason = ""
        self.rolling_summary = ""
        self._agent_messages_since_summary = 0
        self._epilogue = ""

    def _compose_extra_system(self) -> str:
        parts: list[str] = []
        if self.config.lan_hints and not self._lan_sent and self._lan_peers_lines:
            block = "\n".join(self._lan_peers_lines[:10])
            parts.append(f"LAN peers (discovery):\n{block}")
            self._lan_sent = True
        if self.rolling_summary:
            parts.append(f"Rolling context:\n{self.rolling_summary}")
        return "\n\n".join(parts)

    def start(self, goal: str) -> None:
        self.messages = [
            ChatMessage(
                agent_name="user",
                role="user",
                content=goal,
                round_num=0,
            )
        ]
        self._round = 0
        self._finished = False
        self._end_reason = ""
        self._lan_sent = False
        self.rolling_summary = ""
        self._agent_messages_since_summary = 0
        self._epilogue = ""

    async def step(self) -> ChatMessage | None:
        if self._finished or self._round >= self.config.max_rounds:
            return None

        try:
            self._budget.consume_selector()
        except BudgetExceeded:
            self._finished = True
            self._end_reason = "LLM call budget exhausted"
            return None

        agent_names = list(self.participants.keys())
        select_result = self.selector.select(agent_names, self.messages)

        if asyncio.iscoroutine(select_result):
            chosen_name = await select_result
        else:
            chosen_name = select_result

        participant = self.participants[chosen_name]

        try:
            self._budget.consume_agent()
        except BudgetExceeded:
            self._finished = True
            self._end_reason = "LLM call budget exhausted"
            return None

        extra = self._compose_extra_system()
        try:
            response = await participant.respond(
                self.messages,
                max_context_chars=self.config.max_context_chars,
                extra_system=extra or None,
            )
        except Exception as exc:
            response = f"[ERROR] {exc}"

        self._round += 1
        msg = ChatMessage(
            agent_name=chosen_name,
            role=participant.role,
            content=response,
            round_num=self._round,
        )
        self.messages.append(msg)

        if self.config.done_keyword in response:
            self._finished = True

        self._agent_messages_since_summary += 1
        n = self.config.summary_every_n_agent_messages
        if (
            n > 0
            and self._agent_messages_since_summary >= n
            and self.summary_llm is not None
        ):
            await self._run_rolling_summary()
            self._agent_messages_since_summary = 0

        return msg

    async def _run_rolling_summary(self) -> None:
        if self.summary_llm is None:
            return
        try:
            self._budget.consume_summary()
        except BudgetExceeded:
            return
        lines: list[str] = []
        for m in self.messages[-40:]:
            lines.append(f"- [{m.agent_name}] {m.content[:800]}")
        body = "\n".join(lines)
        prompt_messages = [
            {
                "role": "system",
                "content": (
                    "Summarize the discussion so far as a short bullet list. "
                    "Focus on facts and decisions the agents should remember."
                ),
            },
            {"role": "user", "content": body},
        ]
        try:
            model = self.config.summary_model
            out = await self.summary_llm.complete(prompt_messages, model=model)
            self.rolling_summary = (out or "").strip()
        except Exception:
            pass

    async def _finalize_epilogue(self) -> None:
        self._epilogue = ""
        if not self.config.final_summary or self.summary_llm is None:
            return
        try:
            self._budget.consume_summary()
        except BudgetExceeded:
            return
        lines = [f"[{m.agent_name}] {m.content}" for m in self.messages]
        prompt_messages = [
            {
                "role": "system",
                "content": (
                    "Write a concise closing summary of the whole conversation "
                    "for the user."
                ),
            },
            {"role": "user", "content": "\n".join(lines)},
        ]
        try:
            model = self.config.summary_model
            text = await self.summary_llm.complete(prompt_messages, model=model)
            self._epilogue = (text or "").strip()
        except Exception:
            self._epilogue = ""

    def _build_result(self) -> ChatResult:
        return ChatResult(
            messages=self.messages,
            rounds_used=self._round,
            finished_naturally=self._finished,
            summary=self.messages[-1].content if self.messages else "",
            end_reason=self._end_reason,
            epilogue=self._epilogue,
        )

    async def run(self, goal: str) -> ChatResult:
        self.start(goal)

        while not self._finished and self._round < self.config.max_rounds:
            msg = await self.step()
            if msg is None:
                break

        await self.finalize()
        return self._build_result()

    async def finalize(self) -> None:
        """Run post-loop work (e.g. final summary). Call after the last ``step`` when not using ``run``."""
        await self._finalize_epilogue()
