from unittest.mock import AsyncMock, patch

import msgpack
import pytest

from swarm.memory.erasure import ErasureCoder
from swarm.memory.store import DistributedMemory, MemoryBlock, ShardRepairSettings


@pytest.mark.asyncio
async def test_scan_and_repair_round_counts_healthy_blocks():
    k = AsyncMock()
    storage: dict[str, bytes | None] = {}

    async def mock_set(key, value):
        storage[key] = value

    async def mock_get(key):
        return storage.get(key)

    k.set = mock_set
    k.get = mock_get
    coder = ErasureCoder(data_shards=4, parity_shards=2)
    mem = DistributedMemory(k, AsyncMock(), coder, node_id="n1")

    block = MemoryBlock(
        owner_id="n1",
        block_type="knowledge",
        content=b"payload",
        tags=["t"],
    )
    bid = await mem.store(block)
    n = await mem.scan_and_repair_round()
    assert n == 1
    assert await mem.repair_shards_once(bid) is True


@pytest.mark.asyncio
async def test_repair_fails_when_shards_missing():
    k = AsyncMock()
    storage: dict[str, bytes | None] = {}

    async def mock_set(key, value):
        storage[key] = value

    async def mock_get(key):
        return storage.get(key)

    k.set = mock_set
    k.get = mock_get
    coder = ErasureCoder(data_shards=4, parity_shards=2)
    mem = DistributedMemory(k, AsyncMock(), coder, node_id="n1")

    block = MemoryBlock(
        owner_id="n1",
        block_type="knowledge",
        content=b"x" * 200,
        tags=["t"],
    )
    bid = await mem.store(block)
    # Need < data_shards present: 4+2 coding tolerates up to 2 missing shards.
    for i in range(3):
        storage[f"shard:{bid}:{i}"] = None
    assert await mem.retrieve(bid) is None
    assert await mem.repair_shards_once(bid) is False


@pytest.mark.asyncio
async def test_repair_pulls_missing_shards_via_rpc():
    k = AsyncMock()
    storage: dict[str, bytes | None] = {}

    async def mock_set(key, value):
        storage[key] = value

    async def mock_get(key):
        return storage.get(key)

    k.set = mock_set
    k.get = mock_get
    k.get_peers = AsyncMock(return_value=[])

    coder = ErasureCoder(data_shards=4, parity_shards=2)
    block = MemoryBlock(
        owner_id="n1",
        block_type="knowledge",
        content=b"y" * 200,
        tags=["t"],
    )
    good_shards = coder.encode(block.content)

    async def rpc_call(host, port, method, params):
        assert method == "memory_shard_get"
        assert host == "127.0.0.1"
        assert port == 17000
        idx = params["shard_index"]
        return {"ok": True, "shard": good_shards[idx]}

    rpc = AsyncMock()
    rpc.call = AsyncMock(side_effect=rpc_call)

    repair = ShardRepairSettings(
        local_rpc_host="127.0.0.1",
        local_rpc_port=17000,
        max_peers_per_shard=16,
    )
    mem = DistributedMemory(k, rpc, coder, node_id="n1", shard_repair=repair)

    bid = await mem.store(block)
    for i in range(3):
        storage[f"shard:{bid}:{i}"] = None

    assert await mem.retrieve(bid) is None
    assert await mem.repair_shards_once(bid) is True
    out = await mem.retrieve(bid)
    assert out is not None
    assert out.content == block.content
    rpc.call.assert_awaited()


@pytest.mark.asyncio
async def test_repair_decode_failure_does_not_persist_bad_shards():
    k = AsyncMock()
    storage: dict[str, bytes | None] = {}

    async def mock_set(key, value):
        storage[key] = value

    async def mock_get(key):
        return storage.get(key)

    k.set = mock_set
    k.get = mock_get
    k.get_peers = AsyncMock(return_value=[])

    coder = ErasureCoder(data_shards=4, parity_shards=2)
    block = MemoryBlock(
        owner_id="n1",
        block_type="knowledge",
        content=b"z" * 200,
        tags=["t"],
    )
    good_shards = coder.encode(block.content)

    async def rpc_call(host, port, method, params):
        return {"ok": True, "shard": good_shards[params["shard_index"]]}

    rpc = AsyncMock()
    rpc.call = AsyncMock(side_effect=rpc_call)

    repair = ShardRepairSettings(
        local_rpc_host="127.0.0.1",
        local_rpc_port=17001,
    )
    mem = DistributedMemory(k, rpc, coder, node_id="n1", shard_repair=repair)

    bid = await mem.store(block)
    for i in range(3):
        storage[f"shard:{bid}:{i}"] = None

    with patch.object(ErasureCoder, "decode", side_effect=ValueError("forced decode failure")):
        assert await mem.repair_shards_once(bid) is False

    assert await mem.retrieve(bid) is None
    for i in range(3):
        assert storage.get(f"shard:{bid}:{i}") is None


@pytest.mark.asyncio
async def test_store_embeds_replica_hints_when_endpoint_configured():
    k = AsyncMock()
    storage: dict[str, bytes | None] = {}

    async def mock_set(key, value):
        storage[key] = value

    async def mock_get(key):
        return storage.get(key)

    k.set = mock_set
    k.get = mock_get

    coder = ErasureCoder(data_shards=4, parity_shards=2)
    repair = ShardRepairSettings(
        local_rpc_host="10.0.0.5",
        local_rpc_port=10000,
    )
    mem = DistributedMemory(
        k, AsyncMock(), coder, node_id="node-xyz", shard_repair=repair
    )
    bid = await mem.store(
        MemoryBlock(
            owner_id="n1",
            block_type="knowledge",
            content=b"a",
            tags=["t"],
        )
    )
    meta = msgpack.unpackb(storage[f"meta:{bid}"], raw=False)
    hints = meta.get("replica_hints") or []
    assert hints == [
        {"node_id": "node-xyz", "rpc_host": "10.0.0.5", "rpc_port": 10000}
    ]


@pytest.mark.asyncio
async def test_repair_uses_config_seed_kad_to_rpc_port():
    k = AsyncMock()
    storage: dict[str, bytes | None] = {}

    async def mock_set(key, value):
        storage[key] = value

    async def mock_get(key):
        return storage.get(key)

    k.set = mock_set
    k.get = mock_get
    k.get_peers = AsyncMock(return_value=[])

    coder = ErasureCoder(data_shards=4, parity_shards=2)
    block = MemoryBlock(
        owner_id="n1",
        block_type="knowledge",
        content=b"w" * 200,
        tags=["t"],
    )
    good_shards = coder.encode(block.content)
    seen_ports: list[int] = []

    async def rpc_call(host, port, method, params):
        seen_ports.append(port)
        idx = params["shard_index"]
        return {"ok": True, "shard": good_shards[idx]}

    rpc = AsyncMock()
    rpc.call = AsyncMock(side_effect=rpc_call)

    repair = ShardRepairSettings(
        seeds=[("192.168.0.2", 9000)],
        rpc_port_offset=2000,
        local_rpc_host=None,
        local_rpc_port=None,
    )
    mem = DistributedMemory(k, rpc, coder, node_id="n1", shard_repair=repair)
    bid = await mem.store(block)
    for i in range(3):
        storage[f"shard:{bid}:{i}"] = None

    assert await mem.repair_shards_once(bid) is True
    assert 11000 in seen_ports  # 9000 + 2000


@pytest.mark.asyncio
async def test_repair_tries_second_rpc_peer_when_first_returns_empty():
    """Simulates two replica RPC endpoints: first answers ok but empty shard bytes."""
    k = AsyncMock()
    storage: dict[str, bytes | None] = {}

    async def mock_set(key, value):
        storage[key] = value

    async def mock_get(key):
        return storage.get(key)

    k.set = mock_set
    k.get = mock_get
    k.get_peers = AsyncMock(return_value=[])

    coder = ErasureCoder(data_shards=4, parity_shards=2)
    block = MemoryBlock(
        owner_id="n1",
        block_type="knowledge",
        content=b"m" * 200,
        tags=["t"],
    )
    good_shards = coder.encode(block.content)
    call_order: list[tuple[str, int, int]] = []

    async def rpc_call(host, port, method, params):
        idx = params["shard_index"]
        call_order.append((host, port, idx))
        if host == "192.168.1.10":
            return {"ok": True, "shard": b""}
        if host == "192.168.1.20":
            return {"ok": True, "shard": good_shards[idx]}
        return {"ok": False, "shard": None}

    rpc = AsyncMock()
    rpc.call = AsyncMock(side_effect=rpc_call)

    repair = ShardRepairSettings(
        seeds=[("192.168.1.10", 8000), ("192.168.1.20", 8000)],
        rpc_port_offset=2000,
    )
    mem = DistributedMemory(k, rpc, coder, node_id="n1", shard_repair=repair)
    bid = await mem.store(block)
    for i in range(3):
        storage[f"shard:{bid}:{i}"] = None

    assert await mem.repair_shards_once(bid) is True
    out = await mem.retrieve(bid)
    assert out is not None
    assert out.content == block.content
    bad_host_calls = sum(1 for h, _p, _i in call_order if h == "192.168.1.10")
    good_host_calls = sum(1 for h, _p, _i in call_order if h == "192.168.1.20")
    assert bad_host_calls == 3
    assert good_host_calls == 3
