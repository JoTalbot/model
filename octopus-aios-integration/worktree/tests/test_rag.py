"""Tests for swarm.memory.rag -- retrieval + prompt rendering."""

from __future__ import annotations

import pytest

from swarm.memory.rag import (
    DEFAULT_SYSTEM,
    HybridRetriever,
    RagPromptBuilder,
    RetrievedDoc,
    Retriever,
    build_prompt,
)
from swarm.memory.vector_store import HashingEmbedder, VectorStore


@pytest.fixture
def populated_store() -> VectorStore:
    store = VectorStore(embedder=HashingEmbedder(dims=128))
    store.add(
        id="doc-glass-1",
        text="lobovoe steklo BMW X5 Pilkington with rain sensor",
        metadata={"tag": "catalog"},
    )
    store.add(
        id="doc-glass-2",
        text="lobovoe steklo Mercedes GLE FYG no sensor laminated",
        metadata={"tag": "catalog"},
    )
    store.add(
        id="doc-recipe-1",
        text="how to brew filter coffee at 95C with V60 dripper",
        metadata={"tag": "knowledge"},
    )
    return store


# ---------------------------------------------------------------------------
# Retriever
# ---------------------------------------------------------------------------


def test_retriever_returns_top_k(populated_store):
    r = Retriever(populated_store, top_k=2)
    docs = r.retrieve("BMW lobovoe steklo Pilkington")
    assert 1 <= len(docs) <= 2
    assert docs[0].id == "doc-glass-1"
    assert docs[0].score > 0


def test_retriever_returns_empty_for_blank_query(populated_store):
    r = Retriever(populated_store)
    assert r.retrieve("") == []
    assert r.retrieve("   ") == []


def test_retriever_min_score_filters_low_hits(populated_store):
    r = Retriever(populated_store, min_score=0.99, top_k=10)
    docs = r.retrieve("totally unrelated python ranges")
    assert docs == []


def test_retriever_caps_max_chars(populated_store):
    store = VectorStore(embedder=HashingEmbedder(dims=64))
    long_text = "BMW BMW BMW " + ("payload " * 500)
    store.add(id="doc-long", text=long_text)
    r = Retriever(store, max_chars_per_doc=100)
    docs = r.retrieve("BMW")
    assert len(docs) == 1
    assert len(docs[0].text) <= 101  # +1 for ellipsis char
    assert docs[0].text.endswith("…")


def test_retriever_carries_metadata(populated_store):
    r = Retriever(populated_store)
    docs = r.retrieve("Mercedes GLE")
    assert docs[0].metadata.get("tag") == "catalog"


def test_retrieved_doc_from_match_round_trip():
    store = VectorStore(embedder=HashingEmbedder(dims=64))
    store.add(id="x", text="hello world", metadata={"k": "v"})
    matches = store.search("hello world", top_k=1)
    doc = RetrievedDoc.from_match(matches[0])
    assert doc.id == "x"
    assert doc.text == "hello world"
    assert doc.metadata == {"k": "v"}
    assert doc.source == "vector"


# ---------------------------------------------------------------------------
# build_prompt
# ---------------------------------------------------------------------------


def test_build_prompt_with_docs_includes_context_block():
    docs = [
        RetrievedDoc(id="a", text="alpha fact", score=0.8),
        RetrievedDoc(id="b", text="beta fact", score=0.6),
    ]
    prompt = build_prompt("What is alpha?", docs)
    assert DEFAULT_SYSTEM.split(".")[0] in prompt
    assert "Context:" in prompt
    assert "[1] alpha fact" in prompt
    assert "[2] beta fact" in prompt
    assert "source: a, score=0.800" in prompt
    assert "Question: What is alpha?" in prompt


def test_build_prompt_without_docs_skips_context():
    prompt = build_prompt("Tell me about cars", [])
    assert "Context:" not in prompt
    assert "Question: Tell me about cars" in prompt


def test_build_prompt_custom_system():
    prompt = build_prompt(
        "q",
        [],
        system="Respond only in haiku.",
    )
    assert "Respond only in haiku." in prompt
    assert DEFAULT_SYSTEM not in prompt


def test_build_prompt_include_metadata_flag():
    docs = [RetrievedDoc(id="a", text="x", score=0.5, metadata={"src": "wiki"})]
    raw = build_prompt("q", docs)
    rich = build_prompt("q", docs, include_metadata=True)
    assert "meta=" not in raw
    assert "meta={'src': 'wiki'}" in rich


def test_build_prompt_strips_whitespace_per_doc():
    docs = [RetrievedDoc(id="a", text="  spacey  text  ", score=0.5)]
    prompt = build_prompt("q", docs)
    assert "[1] spacey  text" in prompt
    assert "[1]   spacey" not in prompt


# ---------------------------------------------------------------------------
# RagPromptBuilder (sync path)
# ---------------------------------------------------------------------------


def test_rag_prompt_builder_render_sync(populated_store):
    builder = RagPromptBuilder(Retriever(populated_store, top_k=2))
    prompt = builder.render_sync("Pilkington BMW lobovoe steklo")
    assert "[1]" in prompt
    assert "doc-glass-1" in prompt


# ---------------------------------------------------------------------------
# HybridRetriever
# ---------------------------------------------------------------------------


class FakeRepoRow:
    def __init__(self, ref: str, text: str, tags: list[str], table: str = "notes") -> None:
        self.ref = ref
        self.data = {"text": text}
        self.tags = tags
        self.table = table
        self.attrs = {}


class FakeRepo:
    def __init__(self, rows: list[FakeRepoRow]) -> None:
        self._rows = rows

    async def query(self, *, tags=None, limit=100, **kwargs):
        if not tags:
            return list(self._rows[:limit])
        return [r for r in self._rows if all(t in r.tags for t in tags)][:limit]


async def test_hybrid_retriever_combines_vector_and_tag(populated_store):
    repo = FakeRepo([
        FakeRepoRow("ref:file:tag-1", "GAZ Volga steklo back window", ["catalog", "gaz"]),
        FakeRepoRow("ref:file:tag-2", "totally unrelated", ["chatter"]),
    ])
    hybrid = HybridRetriever(populated_store, repo, top_k=4)
    docs = await hybrid.retrieve("BMW Pilkington", tags=["gaz"])
    ids = [d.id for d in docs]
    assert "doc-glass-1" in ids
    assert "ref:file:tag-1" in ids


async def test_hybrid_retriever_dedups_against_vector_hits(populated_store):
    repo = FakeRepo([FakeRepoRow("doc-glass-1", "dup", ["catalog"])])
    hybrid = HybridRetriever(populated_store, repo, top_k=4)
    docs = await hybrid.retrieve("BMW Pilkington", tags=["catalog"])
    ids = [d.id for d in docs]
    assert ids.count("doc-glass-1") == 1


async def test_hybrid_retriever_works_without_tags(populated_store):
    repo = FakeRepo([])
    hybrid = HybridRetriever(populated_store, repo, top_k=2)
    docs = await hybrid.retrieve("BMW Pilkington")
    assert len(docs) >= 1
    assert all(d.source == "vector" for d in docs)


async def test_hybrid_retriever_handles_repo_failure(populated_store):
    class BrokenRepo:
        async def query(self, **kwargs):
            raise RuntimeError("DHT timeout")

    hybrid = HybridRetriever(populated_store, BrokenRepo(), top_k=2)
    docs = await hybrid.retrieve("BMW", tags=["any"])
    # Vector hits still come through even when the tag side blew up.
    assert any(d.source == "vector" for d in docs)
