from unittest.mock import AsyncMock, MagicMock

import pytest

from swarm.memory.adapters.swarm_store import DhtErasureAdapter
from swarm.memory.store import MemoryBlock
from swarm.memory.types import Artifact


@pytest.mark.asyncio
async def test_swarm_put_get_uses_distributed_memory():
    dm = MagicMock()
    dm.store = AsyncMock(return_value="block-uuid-1")
    dm.retrieve = AsyncMock(return_value=None)

    ad = DhtErasureAdapter(dm, default_block_type="knowledge", owner_id="node-a")
    ref = await ad.put(Artifact(content=b"data", tags=["x"], provenance={"source": "t"}))
    assert ref == "ref:swarm:block-uuid-1"
    dm.store.assert_awaited()
    call_kw = dm.store.await_args[0][0]
    assert isinstance(call_kw, MemoryBlock)
    assert call_kw.content == b"data"


@pytest.mark.asyncio
async def test_swarm_get_round_trip():
    block = MemoryBlock(
        owner_id="node-a",
        block_type="knowledge",
        content=b"hello",
        tags=["t1"],
        id="bid-99",
        attrs={"k": "v"},
    )
    dm = MagicMock()
    dm.store = AsyncMock()
    dm.retrieve = AsyncMock(return_value=block)

    ad = DhtErasureAdapter(dm, owner_id="node-a")
    ref = "ref:swarm:bid-99"
    art = await ad.get(ref)
    assert art.content == b"hello"
    assert art.tags == ["t1"]
    assert art.mime == "application/octet-stream"
    assert art.provenance == {}
    assert art.attrs == {"k": "v"}
    dm.retrieve.assert_awaited_once_with("bid-99")
