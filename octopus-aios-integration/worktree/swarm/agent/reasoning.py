from __future__ import annotations

from typing import Any


class ReasoningEngine:
    """Small LLM boundary used by agents and task executors."""

    def __init__(self, llm, graph_rag: Any = None) -> None:
        self.llm = llm
        self.graph_rag = graph_rag

    async def think(self, context: str, system_prompt: str | None = None, use_graph: bool = True) -> str:
        augmented_context = context
        if use_graph and self.graph_rag:
            # We treat the input 'context' as a query to pull related knowledge
            graph_context = await self.graph_rag.retrieve_context(context, top_k=3)
            if graph_context:
                augmented_context = f"Additional Knowledge from Memory:\n{graph_context}\n\nUser/Task Context:\n{context}"

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": augmented_context})
        return await self.llm.complete(messages)
