from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from swarm.llm.router import LLMRouter
from swarm.memory.repository import MemoryRepository
from swarm.memory.vector_store import VectorStore

logger = logging.getLogger(__name__)

@dataclass
class SemanticEdge:
    target_ref: str
    relation_type: str
    explanation: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_ref": self.target_ref,
            "relation_type": self.relation_type,
            "explanation": self.explanation,
        }

LINK_EXPLAIN_PROMPT = """You are a semantic analysis engine. Analyze the relationship between two pieces of content.

Content A:
{content_a}

Content B:
{content_b}

Task:
1. Determine the relationship type (SIMILAR, CONTRADICTS, EVIDENCE, EXAMPLE, RELATED).
2. Write a short (1 sentence) explanation of why they are linked.

Return ONLY a JSON object:
{{"type": "RELATION_TYPE", "explanation": "Your explanation here"}}
"""

class MemoryLinker:
    """Agent that discovers semantic links between memory items and explains them using LLM."""

    def __init__(self, repository: MemoryRepository, vector_store: VectorStore, llm: LLMRouter | None = None):
        self.repo = repository
        self.vectors = vector_store
        self.llm = llm

    async def link_item(self, ref: str, threshold: float = 0.7) -> list[str]:
        """Find related items, create edges, and explain connections using LLM."""
        item = await self.repo._port.get(ref)
        if not item:
            return []

        # 1. Search for similar items in vector store
        content_a = item.content if isinstance(item.content, str) else item.content.decode("utf-8", errors="ignore")
        matches = self.vectors.search(content_a[:2000], top_k=5)

        links = []
        edges: list[SemanticEdge] = []
        
        current_edges = item.attrs.get("semantic_edges", [])
        linked_refs = {e["target_ref"] for e in current_edges}

        for match in matches:
            target_ref = match.record.id
            if target_ref == ref or target_ref in linked_refs:
                continue

            if match.score >= threshold:
                links.append(target_ref)
                
                # 2. Use LLM to explain the link if available
                explanation = "Direct semantic similarity (vector match)."
                relation_type = "RELATED"
                
                if self.llm:
                    try:
                        content_b = match.record.text
                        edge_data = await self._explain_link(content_a, content_b)
                        relation_type = edge_data.get("type", "RELATED")
                        explanation = edge_data.get("explanation", explanation)
                    except Exception as exc:
                        logger.warning("LLM link explanation failed for %s <-> %s: %s", ref, target_ref, exc)

                edge = SemanticEdge(target_ref=target_ref, relation_type=relation_type, explanation=explanation)
                edges.append(edge)
                logger.info("Semantic link discovered: %s --[%s]--> %s", ref, relation_type, target_ref)

        # 3. Update metadata with links and edges
        if edges:
            item.attrs["related_refs"] = list(set(item.attrs.get("related_refs", []) + links))
            item.attrs["semantic_edges"] = current_edges + [e.to_dict() for e in edges]
            
            # Save updated metadata back to repository
            try:
                # Use standard repository save (this might create a new version depending on implementation)
                data = json.loads(item.content) if item.mime == "application/json" else {"content": "raw"}
                await self.repo.save(
                    data=data,
                    table=item.attrs.get("_table", "linked"),
                    tags=list(item.tags),
                    attrs=item.attrs
                )
            except Exception as exc:
                logger.error("Failed to save linked item %s: %s", ref, exc)

        return links

    async def _explain_link(self, content_a: str, content_b: str) -> dict[str, str]:
        """Ask LLM to explain the relationship between two contents."""
        prompt = LINK_EXPLAIN_PROMPT.format(
            content_a=content_a[:1500],
            content_b=content_b[:1500]
        )
        
        raw = await self.llm.complete([{"role": "user", "content": prompt}])
        try:
            # Clean up potential markdown fences
            clean_raw = raw.strip()
            if clean_raw.startswith("```json"):
                clean_raw = clean_raw[7:].strip()
            if clean_raw.endswith("```"):
                clean_raw = clean_raw[:-3].strip()
                
            return json.loads(clean_raw)
        except (json.JSONDecodeError, ValueError):
            logger.warning("Failed to parse LLM response for link explanation: %s", raw)
            return {"type": "RELATED", "explanation": "Vector-based semantic connection."}
