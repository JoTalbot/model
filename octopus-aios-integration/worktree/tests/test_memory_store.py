from unittest.mock import AsyncMock

import msgpack
import pytest

from swarm.memory.erasure import ErasureCoder
from swarm.memory.store import DistributedMemory, MemoryBlock


@pytest.fixture
def mock_kademlia():
    storage = {}

    async def mock_get(key):
        return storage.get(key)

    async def mock_set(key, value):
        storage[key] = value
        return True

    node = AsyncMock()
    node.get = mock_get
    node.set = mock_set
    return node


@pytest.fixture
def mock_rpc():
    client = AsyncMock()
    client.call = AsyncMock(return_value={"status": "ok"})
    return client


@pytest.fixture
def memory(mock_kademlia, mock_rpc):
    return DistributedMemory(
        kademlia=mock_kademlia,
        rpc_client=mock_rpc,
        coder=ErasureCoder(data_shards=4, parity_shards=2),
        node_id="test-node",
    )


@pytest.mark.asyncio
async def test_store_and_retrieve(memory):
    block = MemoryBlock(
        owner_id="test-node",
        block_type="knowledge",
        content=b"The meaning of life is 42",
        tags=["test", "philosophy"],
    )
    block_id = await memory.store(block)
    assert block_id is not None

    retrieved = await memory.retrieve(block_id)
    assert retrieved is not None
    assert retrieved.content == b"The meaning of life is 42"
    assert retrieved.tags == ["test", "philosophy"]


@pytest.mark.asyncio
async def test_store_creates_tag_index(memory):
    block = MemoryBlock(
        owner_id="test-node",
        block_type="task_result",
        content=b"Price data",
        tags=["prices", "autoglass"],
    )
    block_id = await memory.store(block)
    results = await memory.search(tags=["autoglass"])
    assert len(results) >= 1
    assert any(r.id == block_id for r in results)


@pytest.mark.asyncio
async def test_delete_removes_block(memory):
    block = MemoryBlock(
        owner_id="test-node",
        block_type="dialog",
        content=b"Chat message",
        tags=["chat"],
    )
    block_id = await memory.store(block)
    deleted = await memory.delete(block_id)
    assert deleted is True
    result = await memory.retrieve(block_id)
    assert result is None


@pytest.mark.asyncio
async def test_memory_block_defaults():
    block = MemoryBlock(
        owner_id="node-1",
        block_type="knowledge",
        content=b"data",
        tags=[],
    )
    assert block.id is not None
    assert block.timestamp > 0
    assert block.ttl is None


@pytest.mark.asyncio
async def test_store_retrieve_round_trip_with_attrs():
    k = AsyncMock()
    storage = {}

    async def mock_set(key, value):
        storage[key] = value

    async def mock_get(key):
        return storage.get(key)

    k.set = mock_set
    k.get = mock_get
    coder = ErasureCoder(data_shards=4, parity_shards=2)
    mem = DistributedMemory(k, AsyncMock(), coder, node_id="n1")

    attrs = {"schema_version": 1, "dur": "scratch"}
    block = MemoryBlock(
        owner_id="n1",
        block_type="knowledge",
        content=b"payload",
        tags=["t1"],
        attrs=attrs,
    )
    bid = await mem.store(block)
    out = await mem.retrieve(bid)
    assert out is not None
    assert out.attrs == attrs
    meta = msgpack.unpackb(storage[f"meta:{bid}"], raw=False)
    assert meta.get("attrs") == attrs
