from __future__ import annotations

import logging
from typing import Any

from swarm.memory.repository import MemoryRepository
from swarm.memory.types import Artifact
from swarm.memory.vector_store import VectorStore

logger = logging.getLogger(__name__)

class GraphRAG:
    """Enhanced RAG that uses semantic links to provide better context."""

    def __init__(self, repository: MemoryRepository, vector_store: VectorStore):
        self.repo = repository
        self.vectors = vector_store

    async def retrieve_context(self, query: str, top_k: int = 3, max_hops: int = 1) -> str:
        """Retrieve context by combining vector search and graph traversal."""

        # 1. Initial vector search
        initial_matches = self.vectors.search(query, top_k=top_k)

        # 2. Collect initial refs and their linked neighbors
        visited_refs: set[str] = set()
        context_artifacts: list[Artifact] = []

        to_process = [m.record.id for m in initial_matches]

        # Simple BFS-like traversal for max_hops
        for _ in range(max_hops + 1):
            next_batch = []
            for ref in to_process:
                if ref in visited_refs:
                    continue

                artifact = await self.repo._port.get(ref)
                if not artifact:
                    continue

                visited_refs.add(ref)
                context_artifacts.append(artifact)

                # Find links in attributes
                links = artifact.attrs.get("related_refs", [])
                for link in links:
                    if link not in visited_refs:
                        next_batch.append(link)

            to_process = next_batch
            if not to_process:
                break

        # 3. Format context
        formatted_context = []
        for i, art in enumerate(context_artifacts):
            content = art.content if isinstance(art.content, str) else art.content.decode("utf-8", errors="ignore")
            title = art.attrs.get("title") or art.attrs.get("name") or f"Memory {i}"
            source = art.attrs.get("vfs_id") or art.attrs.get("_table") or "unknown"

            formatted_context.append(f"--- SOURCE: {title} ({source}) ---\n{content}\n")

        return "\n".join(formatted_context)

    async def query_with_graph(self, llm: Any, query: str, system_prompt: str | None = None) -> str:
        """Complete RAG cycle using the Graph-enhanced context."""
        context = await self.retrieve_context(query)

        full_prompt = f"Use the following context to answer the question: \n\n{context}\n\nQuestion: {query}"

        messages = [
            {"role": "system", "content": system_prompt or "You are a helpful assistant with a perfect memory."},
            {"role": "user", "content": full_prompt}
        ]

        return await llm.complete(messages)
