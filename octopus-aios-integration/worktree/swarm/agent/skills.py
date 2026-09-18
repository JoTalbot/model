from __future__ import annotations

import logging

import httpx

from swarm.memory.store import MemoryBlock

logger = logging.getLogger(__name__)


class WebParserSkill:
    """Skill that delegates to :class:`WebParserPipeline` when available.

    Falls back to the original single-URL fetch+LLM path when the pipeline
    is not wired (backwards-compatible).
    """

    def __init__(self, llm) -> None:
        self.llm = llm
        self._pipeline = None

    def _ensure_pipeline(self):
        if self._pipeline is None:
            from swarm.parser.pipeline import WebParserPipeline
            self._pipeline = WebParserPipeline(self.llm)
        return self._pipeline

    async def execute(self, url: str, instruction: str) -> str:
        """Legacy single-URL interface — delegates to the pipeline."""
        pipeline = self._ensure_pipeline()
        results = await pipeline.run(url, search=False, limit=1)
        if results and results[0].items:
            import json
            return json.dumps(
                [item.to_dict() for item in results[0].items],
                ensure_ascii=False,
                indent=2,
            )
        # Fallback: if pipeline returned nothing useful, try the original path
        if results and results[0].errors:
            logger.warning("Pipeline errors for %s: %s", url, results[0].errors)
        return await self._legacy_execute(url, instruction)

    async def _legacy_execute(self, url: str, instruction: str) -> str:
        """Original single-URL fetch+LLM (fallback)."""
        async with httpx.AsyncClient() as client:
            response = await client.get(url, follow_redirects=True)
            response.raise_for_status()
            html = response.text

        from selectolax.parser import HTMLParser
        tree = HTMLParser(html)
        text_content = tree.body.text(separator="\n", strip=True) if tree.body else html

        truncated = text_content[:4000]
        prompt = (
            f"I scraped the following text from {url}:\n\n"
            f"{truncated}\n\n"
            f"Instruction: {instruction}\n"
            f"Extract and structure the relevant information."
        )
        result = await self.llm.complete([{"role": "user", "content": prompt}])
        return result

    async def search_and_parse(self, query: str, *, limit: int = 3) -> str:
        """Search-based parsing — uses the pipeline in search mode."""
        pipeline = self._ensure_pipeline()
        results = await pipeline.run(query, search=True, limit=limit)
        lines: list[str] = []
        for r in results:
            lines.append(f"Source: {r.source_url}")
            if r.errors:
                lines.append(f"  Errors: {', '.join(r.errors)}")
            for item in r.items:
                parts = [f"  - {item.name}"]
                if item.price:
                    parts.append(f"price={item.price}")
                if item.currency:
                    parts.append(item.currency)
                if item.shop:
                    parts.append(f"shop={item.shop}")
                if item.in_stock is not None:
                    parts.append(f"stock={'yes' if item.in_stock else 'no'}")
                lines.append(" ".join(parts))
            if not r.items and not r.errors:
                lines.append("  (no items)")
        return "\n".join(lines) if lines else "[PARSE] No results"


class ChatSkill:
    def __init__(
        self,
        llm,
        memory,
        rpc_client,
        node_id: str,
        memory_port=None,
    ) -> None:
        self.llm = llm
        self.memory = memory
        self.memory_port = memory_port
        self.rpc_client = rpc_client
        self.node_id = node_id

    async def send_message(
        self,
        target_node: str,
        target_port: int,
        message: str,
        context: str = "",
    ) -> str:
        prompt = (
            f"Context: {context}\n"
            f"Message from peer: {message}\n"
            f"Compose a thoughtful response."
        )
        response = await self.llm.complete([{"role": "user", "content": prompt}])

        await self.rpc_client.call(
            target_node, target_port, "chat_message",
            {"from": self.node_id, "message": response},
        )

        if self.memory_port is not None:
            from swarm.memory.types import Artifact

            await self.memory_port.put(
                Artifact(
                    content=f"Me: {message}\nPeer: {response}".encode(),
                    tags=["dialog", target_node],
                    attrs={"store": "swarm", "block_type": "dialog"},
                )
            )
        else:
            block = MemoryBlock(
                owner_id=self.node_id,
                block_type="dialog",
                content=f"Me: {message}\nPeer: {response}".encode(),
                tags=["dialog", target_node],
            )
            await self.memory.store(block)

        return response


class MemoryDbSkill:
    """Skill wrapper to use MemoryRepository like a tiny DB."""

    def __init__(self, repository) -> None:
        self.repository = repository

    async def save_record(
        self,
        *,
        table: str,
        data: dict,
        tags: list[str] | None = None,
        attrs: dict | None = None,
    ) -> str:
        return await self.repository.save(
            data=data,
            table=table,
            tags=tags,
            attrs=attrs,
        )

    async def query_records(
        self,
        *,
        table: str | None = None,
        tags: list[str] | None = None,
        text: str | None = None,
        attrs: dict | None = None,
        where: str | None = None,
        order_by: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list:
        return await self.repository.query(
            table=table,
            tags=tags,
            text=text,
            attrs=attrs,
            where=where,
            order_by=order_by,
            offset=offset,
            limit=limit,
        )
