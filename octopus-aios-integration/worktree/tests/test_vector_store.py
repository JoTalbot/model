"""Vector store + persistent vector index tests."""

from __future__ import annotations

import pytest

from swarm.memory.adapters.local_scratch import LocalScratchAdapter
from swarm.memory.composite import CompositeMemoryPort
from swarm.memory.repository import MemoryRepository
from swarm.memory.vector_store import (
    HashingEmbedder,
    PersistentVectorIndex,
    TfIdfEmbedder,
    VectorStore,
    cosine,
    tokenize,
)

# ---------------------------------------------------------------------------
# Tokeniser / similarity helpers
# ---------------------------------------------------------------------------

def test_tokenize_handles_unicode_and_hyphens():
    assert tokenize("Привет, авто-стёкла на Олинского-66!") == [
        "привет",
        "авто-стёкла",
        "на",
        "олинского-66",
    ]


def test_cosine_identical_vectors_is_one():
    v = [0.6, 0.8]
    assert pytest.approx(cosine(v, v), rel=1e-6) == 1.0


def test_cosine_unequal_length_returns_zero():
    assert cosine([1.0], [0.0, 1.0]) == 0.0


# ---------------------------------------------------------------------------
# HashingEmbedder
# ---------------------------------------------------------------------------

def test_hashing_embedder_dims_and_normalised():
    emb = HashingEmbedder(dims=32)
    v = emb.embed("автостекло цена Ивана Олинского")
    assert len(v) == 32
    norm_sq = sum(x * x for x in v)
    # L2-normalised
    assert pytest.approx(norm_sq, abs=1e-6) == 1.0 or norm_sq == 0


def test_hashing_embedder_is_deterministic_across_calls():
    emb = HashingEmbedder(dims=64)
    a = emb.embed("hello world")
    b = emb.embed("hello world")
    assert a == b


# ---------------------------------------------------------------------------
# TfIdfEmbedder
# ---------------------------------------------------------------------------

def test_tfidf_embed_before_fit_is_empty():
    emb = TfIdfEmbedder()
    assert emb.embed("hello") == []


def test_tfidf_fit_and_embed_basic():
    corpus = [
        "автостекло lada granta",
        "автостекло toyota camry",
        "редуктор lada granta",
    ]
    emb = TfIdfEmbedder().fit(corpus)
    v1 = emb.embed("автостекло lada")
    v2 = emb.embed("toyota camry автостекло")
    assert len(v1) == len(emb.vocabulary)
    # both vectors are L2-normalised
    n1 = sum(x * x for x in v1)
    n2 = sum(x * x for x in v2)
    assert pytest.approx(n1, abs=1e-6) == 1.0
    assert pytest.approx(n2, abs=1e-6) == 1.0


# ---------------------------------------------------------------------------
# VectorStore search
# ---------------------------------------------------------------------------

def test_vector_store_search_orders_by_similarity():
    store = VectorStore(HashingEmbedder(dims=128))
    store.add(id="a", text="автостекло lada granta замена")
    store.add(id="b", text="редуктор для lada granta")
    store.add(id="c", text="windshield toyota camry replacement")

    results = store.search("lada granta автостекло", top_k=3)
    assert len(results) >= 2
    assert results[0].record.id == "a"


def test_vector_store_remove_and_len():
    store = VectorStore(HashingEmbedder(dims=32))
    store.add(id="a", text="one")
    store.add(id="b", text="two")
    assert len(store) == 2
    assert store.remove("a") is True
    assert store.remove("a") is False
    assert len(store) == 1


def test_vector_store_rebuild_tfidf():
    store = VectorStore(TfIdfEmbedder())
    store.add(id="1", text="autoglass lada")
    store.add(id="2", text="autoglass toyota")
    store.rebuild_tfidf()
    res = store.search("autoglass lada", top_k=2)
    assert res and res[0].record.id == "1"


def test_vector_store_rebuild_noop_for_hashing():
    store = VectorStore(HashingEmbedder(dims=8))
    store.add(id="x", text="hi")
    # Should not raise nor mutate the (non-existent) vocabulary
    store.rebuild_tfidf()
    assert store.get("x") is not None


# ---------------------------------------------------------------------------
# PersistentVectorIndex over MemoryRepository
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_persistent_vector_index_round_trip(tmp_path):
    port = CompositeMemoryPort({"file": LocalScratchAdapter(tmp_path)})
    repo = MemoryRepository(port)

    store_a = VectorStore(HashingEmbedder(dims=64))
    rec1 = store_a.add(id="r1", text="автостекло lada", metadata={"vin": "X1"})
    rec2 = store_a.add(id="r2", text="windshield toyota", metadata={"vin": "Y2"})
    idx_a = PersistentVectorIndex(store_a, repo)
    await idx_a.save(rec1)
    await idx_a.save(rec2)

    # Brand new in-memory store on the same persisted repo
    store_b = VectorStore(HashingEmbedder(dims=64))
    idx_b = PersistentVectorIndex(store_b, repo)
    restored = await idx_b.load_all()
    assert restored == 2

    res = store_b.search("автостекло lada", top_k=1)
    assert res and res[0].record.id == "r1"
    assert store_b.get("r1").metadata == {"vin": "X1"}


def test_persistent_vector_index_encode_stable():
    rec = type(
        "R",
        (),
        {
            "id": "i",
            "text": "t",
            "vector": [0.1, 0.2],
            "metadata": {"k": "v"},
        },
    )()
    enc1 = PersistentVectorIndex.encode(rec)
    enc2 = PersistentVectorIndex.encode(rec)
    assert enc1 == enc2
    assert '"id": "i"' in enc1
