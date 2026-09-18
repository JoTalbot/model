"""Retrieval-augmented generation helpers over the swarm vector store.

This module is intentionally LLM-agnostic.  It does the two parts of
RAG that depend on swarm memory -- ``retrieve`` and ``format_prompt`` --
and hands you a fully-rendered prompt that any LLM (OpenRouter,
llama.cpp, anthropic, …) can consume.  The actual generation step
lives in ``swarm/llm`` so a node can switch providers without touching
the retrieval pipeline.

Pipeline
~~~~~~~~

.. code-block:: text

    user_query
        |
        v
    [Retriever] -> top_k VectorMatch ----+
                                          \\
                                           v
                                      [build_prompt]
                                           |
                                           v
                                   "Context:\\n  [1] ...\\n  [2] ...\\n
                                    Question: <user_query>"

Components
~~~~~~~~~~

* :class:`Retriever` -- thin VectorStore wrapper with score / count caps.
* :class:`HybridRetriever` -- combine vector matches with tag-based
  recall from :class:`MemoryRepository`.
* :func:`build_prompt` / :class:`RagPromptBuilder` -- deterministic
  prompt rendering with citations.

Design choices
~~~~~~~~~~~~~~

* Citations are inline ``[N]`` markers; the renderer also emits a
  citation map at the end of the context, so even a non-RAG-aware
  model can attribute facts.
* Empty result is *not* an error -- the prompt still renders, just
  without context.  This avoids breaking flows that fall through to
  pure-LLM mode when memory has nothing relevant.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from swarm.memory.vector_store import VectorMatch, VectorStore

# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------


@dataclass
class RetrievedDoc:
    """One retrieved document with its score and provenance."""

    id: str
    text: str
    score: float
    source: str = "vector"
    metadata: dict = field(default_factory=dict)

    @classmethod
    def from_match(cls, match: VectorMatch, *, source: str = "vector") -> RetrievedDoc:
        rec = match.record
        return cls(
            id=rec.id,
            text=rec.text,
            score=match.score,
            source=source,
            metadata=dict(rec.metadata or {}),
        )


class Retriever:
    """Top-K cosine retrieval over a :class:`VectorStore`.

    Wraps :meth:`VectorStore.search` with extra knobs (min_score, max_chars)
    so the prompt never explodes if a doc happens to be huge.
    """

    def __init__(
        self,
        store: VectorStore,
        *,
        top_k: int = 5,
        min_score: float = 0.0,
        max_chars_per_doc: int | None = 800,
    ) -> None:
        self._store = store
        self._top_k = max(1, top_k)
        self._min_score = max(0.0, min_score)
        self._max_chars_per_doc = max_chars_per_doc

    def retrieve(
        self,
        query: str,
        *,
        top_k: int | None = None,
        min_score: float | None = None,
    ) -> list[RetrievedDoc]:
        if not query or not query.strip():
            return []
        k = top_k if top_k is not None else self._top_k
        threshold = min_score if min_score is not None else self._min_score
        matches = self._store.search(query, top_k=max(1, k))
        docs: list[RetrievedDoc] = []
        for m in matches:
            if m.score < threshold:
                continue
            doc = RetrievedDoc.from_match(m)
            if self._max_chars_per_doc and len(doc.text) > self._max_chars_per_doc:
                doc.text = doc.text[: self._max_chars_per_doc] + "…"
            docs.append(doc)
        return docs


# ---------------------------------------------------------------------------
# Hybrid retrieval (vector + tag-based via MemoryRepository)
# ---------------------------------------------------------------------------


class HybridRetriever:
    """Combine cosine vector search with tag-based recall from a repository.

    Vector matches are weighted by raw cosine; tag matches enter with a
    fixed positive score and are deduped against vector hits by ``id``.

    Useful for memory full of structured records (Obsidian wiki, chat
    logs, business records) where some queries are best answered by
    exact tag matches rather than fuzzy embedding similarity.
    """

    def __init__(
        self,
        vector_store: VectorStore,
        memory_repository,
        *,
        top_k: int = 5,
        tag_score: float = 0.5,
        max_chars_per_doc: int | None = 800,
    ) -> None:
        self._vec = Retriever(
            vector_store,
            top_k=top_k,
            max_chars_per_doc=max_chars_per_doc,
        )
        self._repo = memory_repository
        self._top_k = top_k
        self._tag_score = tag_score
        self._max_chars = max_chars_per_doc

    async def retrieve(
        self,
        query: str,
        *,
        tags: list[str] | None = None,
        top_k: int | None = None,
    ) -> list[RetrievedDoc]:
        k = top_k or self._top_k
        vec_docs = self._vec.retrieve(query, top_k=k)
        seen = {d.id for d in vec_docs}

        tag_docs: list[RetrievedDoc] = []
        if tags:
            try:
                rows = await self._repo.query(tags=tags, limit=k * 2)
            except Exception:
                rows = []
            for row in rows:
                if row.ref in seen:
                    continue
                text = str(row.data.get("text") or row.data)
                if self._max_chars and len(text) > self._max_chars:
                    text = text[: self._max_chars] + "…"
                tag_docs.append(RetrievedDoc(
                    id=row.ref,
                    text=text,
                    score=self._tag_score,
                    source="tag",
                    metadata={"tags": row.tags, "table": row.table},
                ))

        merged = vec_docs + tag_docs
        merged.sort(key=lambda d: d.score, reverse=True)
        return merged[:k]


# ---------------------------------------------------------------------------
# Prompt rendering
# ---------------------------------------------------------------------------


DEFAULT_SYSTEM = (
    "You answer using the provided context whenever possible. "
    "Cite the source ids as [N] inline. If the context is insufficient, "
    "say so explicitly."
)


def build_prompt(
    query: str,
    docs: Iterable[RetrievedDoc],
    *,
    system: str | None = None,
    include_metadata: bool = False,
) -> str:
    """Render a deterministic, citation-friendly prompt.

    Layout::

        <system>

        Context:
          [1] <doc1.text>   (source: <doc1.id>, score=0.42)
          [2] <doc2.text>   (...)

        Question: <query>

    When the doc list is empty, the prompt skips the ``Context`` block
    so the LLM falls back to its prior knowledge.
    """
    docs = list(docs)
    parts: list[str] = []
    if system or DEFAULT_SYSTEM:
        parts.append((system or DEFAULT_SYSTEM).strip())
        parts.append("")

    if docs:
        parts.append("Context:")
        for idx, doc in enumerate(docs, start=1):
            tail = f"(source: {doc.id}, score={doc.score:.3f}, via {doc.source})"
            if include_metadata and doc.metadata:
                tail = tail.rstrip(")") + f", meta={doc.metadata})"
            parts.append(f"  [{idx}] {doc.text.strip()}\n      {tail}")
        parts.append("")

    parts.append(f"Question: {query.strip()}")
    return "\n".join(parts)


class RagPromptBuilder:
    """Stateful builder for cases where the system prompt + retriever are reused."""

    def __init__(
        self,
        retriever,
        *,
        system: str | None = None,
        include_metadata: bool = False,
    ) -> None:
        self._retriever = retriever
        self._system = system
        self._include_metadata = include_metadata

    def render_sync(self, query: str, **kwargs) -> str:
        docs = self._retriever.retrieve(query, **kwargs)
        return build_prompt(
            query,
            docs,
            system=self._system,
            include_metadata=self._include_metadata,
        )

    async def render(self, query: str, **kwargs) -> str:
        result = self._retriever.retrieve(query, **kwargs)
        # HybridRetriever is async; plain Retriever is sync.
        if hasattr(result, "__await__"):
            docs = await result
        else:
            docs = result
        return build_prompt(
            query,
            docs,
            system=self._system,
            include_metadata=self._include_metadata,
        )


__all__ = [
    "DEFAULT_SYSTEM",
    "HybridRetriever",
    "RagPromptBuilder",
    "RetrievedDoc",
    "Retriever",
    "build_prompt",
]
