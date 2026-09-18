"""Тесты для swarm.memory.tag_index, encoding, graph_rag, retry."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from swarm.memory.encoding import MemoryCodec
from swarm.memory.graph_rag import GraphRAG
from swarm.memory.retry import RetryPolicy, compute_delay, is_transient_error
from swarm.memory.tag_index import TagIndex

# ── TagIndex ──────────────────────────────────────────────────────────────


class MockKademlia:
    """Простой in-memory мок для Kademlia DHT."""

    def __init__(self):
        self._store: dict[str, bytes | None] = {}

    async def get(self, key: str) -> bytes | None:
        return self._store.get(key)

    async def set(self, key: str, value: bytes | None) -> None:
        self._store[key] = value


class TestTagIndex:
    @pytest.mark.asyncio
    async def test_add_and_query(self):
        kad = MockKademlia()
        idx = TagIndex(kad)

        await idx.add("block-1", ["glass", "lada"])
        await idx.add("block-2", ["glass", "bmw"])

        result = await idx.ids_for(["glass"])
        assert "block-1" in result
        assert "block-2" in result

    @pytest.mark.asyncio
    async def test_query_specific_tag(self):
        kad = MockKademlia()
        idx = TagIndex(kad)

        await idx.add("b1", ["tag-a"])
        await idx.add("b2", ["tag-b"])

        result = await idx.ids_for(["tag-a"])
        assert result == {"b1"}

    @pytest.mark.asyncio
    async def test_no_duplicates(self):
        kad = MockKademlia()
        idx = TagIndex(kad)

        await idx.add("b1", ["t"])
        await idx.add("b1", ["t"])  # повторное добавление

        result = await idx.ids_for(["t"])
        assert result == {"b1"}

    @pytest.mark.asyncio
    async def test_remove(self):
        kad = MockKademlia()
        idx = TagIndex(kad)

        await idx.add("b1", ["t"])
        await idx.add("b2", ["t"])
        await idx.remove("b1", ["t"])

        result = await idx.ids_for(["t"])
        assert result == {"b2"}

    @pytest.mark.asyncio
    async def test_empty_query(self):
        kad = MockKademlia()
        idx = TagIndex(kad)
        result = await idx.ids_for(["nonexistent"])
        assert result == set()


# ── MemoryCodec ───────────────────────────────────────────────────────────


class TestMemoryCodec:
    def test_pack_unpack_meta(self):
        from swarm.memory.erasure import ErasureCoder

        kad = MockKademlia()
        coder = ErasureCoder(data_shards=4, parity_shards=2)
        codec = MemoryCodec(kad, coder)

        block = MagicMock()
        block.id = "test-block"
        block.owner_id = "node-1"
        block.block_type = "data"
        block.timestamp = 123.0
        block.ttl = 0
        block.tags = ["a", "b"]
        block.attrs = {"key": "val"}
        block.content = b"hello"

        packed = codec.pack_meta(block, [{"node": "n1"}])
        unpacked = codec.unpack_meta(packed)

        assert unpacked["id"] == "test-block"
        assert unpacked["tags"] == ["a", "b"]
        assert unpacked["replica_hints"] == [{"node": "n1"}]

    def test_encode_decode(self):
        from swarm.memory.erasure import ErasureCoder

        kad = MockKademlia()
        coder = ErasureCoder(data_shards=4, parity_shards=2)
        codec = MemoryCodec(kad, coder)

        original = b"test data for encoding"
        shards = codec.encode(original)
        assert len(shards) == 6

        shard_map = {i: s for i, s in enumerate(shards)}
        decoded = codec.decode(shard_map, len(original))
        assert decoded == original

    @pytest.mark.asyncio
    async def test_write_read_meta(self):
        from swarm.memory.erasure import ErasureCoder

        kad = MockKademlia()
        coder = ErasureCoder(data_shards=4, parity_shards=2)
        codec = MemoryCodec(kad, coder)

        block = MagicMock()
        block.id = "b1"
        block.owner_id = "n"
        block.block_type = "d"
        block.timestamp = 1.0
        block.ttl = 0
        block.tags = []
        block.attrs = {}
        block.content = b""

        await codec.write_meta(block, [])
        meta = await codec.read_meta("b1")
        assert meta is not None
        assert meta["id"] == "b1"

    @pytest.mark.asyncio
    async def test_read_meta_missing(self):
        from swarm.memory.erasure import ErasureCoder

        kad = MockKademlia()
        codec = MemoryCodec(kad, ErasureCoder(4, 2))
        assert await codec.read_meta("nonexistent") is None

    @pytest.mark.asyncio
    async def test_write_read_shards(self):
        from swarm.memory.erasure import ErasureCoder

        kad = MockKademlia()
        coder = ErasureCoder(data_shards=4, parity_shards=2)
        codec = MemoryCodec(kad, coder)

        shards = await codec.write_shards("b1", b"shard data here!!")
        assert len(shards) == 6

        read_back = await codec.read_shards("b1")
        assert len(read_back) == 6


# ── GraphRAG ──────────────────────────────────────────────────────────────


class TestGraphRAG:
    @pytest.mark.asyncio
    async def test_retrieve_empty(self, tmp_path):
        from swarm.memory.adapters.local_scratch import LocalScratchAdapter
        from swarm.memory.composite import CompositeMemoryPort
        from swarm.memory.repository import MemoryRepository
        from swarm.memory.vector_store import HashingEmbedder, VectorStore

        port = CompositeMemoryPort({"file": LocalScratchAdapter(tmp_path)})
        repo = MemoryRepository(port)
        vs = VectorStore(HashingEmbedder())

        rag = GraphRAG(repo, vs)
        ctx = await rag.retrieve_context("запрос без данных")
        assert isinstance(ctx, str)

    @pytest.mark.asyncio
    async def test_query_with_graph(self):
        from swarm.memory.vector_store import VectorStore

        repo = MagicMock()
        vs = VectorStore()
        vs.search = MagicMock(return_value=[])

        llm = AsyncMock()
        llm.complete = AsyncMock(return_value="ответ от LLM")

        rag = GraphRAG(repo, vs)
        result = await rag.query_with_graph(llm, "вопрос")
        assert result == "ответ от LLM"
        llm.complete.assert_called_once()


# ── RetryPolicy ───────────────────────────────────────────────────────────


class TestRetryPolicy:
    def test_defaults(self):
        p = RetryPolicy()
        assert p.max_attempts == 3
        assert p.base_delay == 0.25

    def test_is_transient_httpx(self):
        import httpx
        assert is_transient_error(httpx.ConnectError("refused")) is True

    def test_is_transient_timeout(self):
        assert is_transient_error(TimeoutError()) is True

    def test_not_transient_ref_not_found(self):
        from swarm.memory.types import RefNotFoundError
        assert is_transient_error(RefNotFoundError("x")) is False

    def test_not_transient_value_error(self):
        assert is_transient_error(ValueError("bad")) is False

    def test_compute_delay(self):
        p = RetryPolicy(base_delay=1.0, max_delay=10.0)
        d = compute_delay(0, p)
        assert 0 <= d <= 1.0  # jitter

        d2 = compute_delay(3, p)
        assert 0 <= d2 <= 10.0
