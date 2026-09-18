from __future__ import annotations

import logging

from swarm.chat.room import ChatMessage

logger = logging.getLogger(__name__)


class RoundRobinSelector:
    def __init__(self) -> None:
        self._index = 0

    def select(self, agents: list[str], messages: list[ChatMessage]) -> str:
        agent = agents[self._index % len(agents)]
        self._index += 1
        return agent


class LLMSelector:
    def __init__(self, llm) -> None:
        self.llm = llm
        self._fallback = RoundRobinSelector()

    async def select(self, agents: list[str], messages: list[ChatMessage]) -> str:
        recent = messages[-3:] if messages else []
        history_text = "\n".join(
            f"[{m.agent_name}]: {m.content[:100]}" for m in recent
        )

        prompt = (
            f"Agents available: {', '.join(agents)}\n"
            f"Recent conversation:\n{history_text}\n\n"
            f"Who should speak next? Return ONLY the agent name, nothing else."
        )

        try:
            response = await self.llm.complete([{"role": "user", "content": prompt}])
            chosen = response.strip().lower()

            for agent in agents:
                if agent.lower() == chosen:
                    return agent

            logger.warning("LLM selector returned invalid name '%s', falling back", chosen)
            return self._fallback.select(agents, messages)
        except Exception as exc:
            logger.warning("LLM selector failed: %s, falling back to round-robin", exc)
            return self._fallback.select(agents, messages)
