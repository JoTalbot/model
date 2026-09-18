from unittest.mock import AsyncMock, MagicMock

import pytest

from swarm.memory.adapters.local_scratch import LocalScratchAdapter
from swarm.memory.adapters.swarm_store import DhtErasureAdapter
from swarm.memory.composite import CompositeMemoryPort
from swarm.memory.types import (
    Artifact,
    Capabilities,
    MemoryAdapterError,
    PromotionError,
    RefMeta,
)


@pytest.mark.asyncio
async def test_promote_file_to_swarm(tmp_path):
    dm = MagicMock()
    dm.store = AsyncMock(return_value="swarmed-id")

    local = LocalScratchAdapter(tmp_path)
    swarm = DhtErasureAdapter(dm, default_block_type="knowledge", owner_id="n")
    comp = CompositeMemoryPort({"file": local, "swarm": swarm})

    ref = await comp.put(Artifact(content=b"z"))
    assert ref.startswith("ref:file:")

    new_ref = await comp.promote(ref)
    assert new_ref.startswith("ref:swarm:")
    assert new_ref == "ref:swarm:swarmed-id"

    dm.store.assert_awaited()
    stored_block = dm.store.await_args[0][0]
    assert stored_block.content == b"z"
    assert (stored_block.attrs or {}).get("store") == "swarm"


@pytest.mark.asyncio
async def test_put_routes_to_swarm_when_store_attr(tmp_path):
    dm = MagicMock()
    dm.store = AsyncMock(return_value="swarmed-id")

    local = LocalScratchAdapter(tmp_path)
    swarm = DhtErasureAdapter(dm, default_block_type="knowledge", owner_id="n")
    comp = CompositeMemoryPort({"file": local, "swarm": swarm})

    ref = await comp.put(Artifact(content=b"hi", attrs={"store": "swarm"}))
    assert ref == "ref:swarm:swarmed-id"
    assert comp.metrics.puts.get("swarm") == 1
    assert comp.metrics.puts.get("file") is None
    dm.store.assert_awaited_once()


@pytest.mark.asyncio
async def test_put_defaults_to_file(tmp_path):
    local = LocalScratchAdapter(tmp_path)
    comp = CompositeMemoryPort({"file": local})

    ref = await comp.put(Artifact(content=b"local"))
    assert ref.startswith("ref:file:")
    assert comp.metrics.puts.get("file") == 1


@pytest.mark.asyncio
async def test_put_missing_adapter_raises(tmp_path):
    comp = CompositeMemoryPort({"file": LocalScratchAdapter(tmp_path)})
    with pytest.raises(MemoryAdapterError):
        await comp.put(Artifact(content=b"x", attrs={"store": "swarm"}))


@pytest.mark.asyncio
async def test_promote_rejects_non_file_scheme(tmp_path):
    dm = MagicMock()
    swarm = DhtErasureAdapter(dm, default_block_type="knowledge", owner_id="n")
    comp = CompositeMemoryPort(
        {"file": LocalScratchAdapter(tmp_path), "swarm": swarm}
    )
    with pytest.raises(PromotionError):
        await comp.promote("ref:swarm:abc")


@pytest.mark.asyncio
async def test_search_merges():
    cap_search = Capabilities(
        schemes=frozenset({"file"}),
        supports_search=True,
        supports_delete=True,
        supports_promote=False,
    )
    cap_search_swarm = Capabilities(
        schemes=frozenset({"swarm"}),
        supports_search=True,
        supports_delete=True,
        supports_promote=False,
    )
    cap_no_search = Capabilities(
        schemes=frozenset({"https"}),
        supports_search=False,
        supports_delete=False,
        supports_promote=False,
    )

    file_adapter = MagicMock()
    file_adapter.capabilities = MagicMock(return_value=cap_search)
    file_adapter.search = AsyncMock(
        return_value=[
            RefMeta(ref="ref:file:1", scheme="file", tags=["t1"]),
            RefMeta(ref="ref:file:dup", scheme="file", tags=["t1"]),
        ]
    )

    swarm_adapter = MagicMock()
    swarm_adapter.capabilities = MagicMock(return_value=cap_search_swarm)
    swarm_adapter.search = AsyncMock(
        return_value=[
            RefMeta(ref="ref:swarm:2", scheme="swarm", tags=["t1"]),
            RefMeta(ref="ref:file:dup", scheme="file", tags=["t1"]),
        ]
    )

    link_adapter = MagicMock()
    link_adapter.capabilities = MagicMock(return_value=cap_no_search)
    link_adapter.search = AsyncMock(return_value=[])

    comp = CompositeMemoryPort(
        {"file": file_adapter, "swarm": swarm_adapter, "https": link_adapter}
    )

    results = await comp.search(["t1"], None)
    refs = [meta.ref for meta in results]

    assert set(refs) == {"ref:file:1", "ref:file:dup", "ref:swarm:2"}
    assert len(refs) == 3
    link_adapter.search.assert_not_awaited()


@pytest.mark.asyncio
async def test_capabilities_union(tmp_path):
    dm = MagicMock()
    comp = CompositeMemoryPort(
        {
            "file": LocalScratchAdapter(tmp_path),
            "swarm": DhtErasureAdapter(dm, owner_id="n"),
        }
    )
    caps = comp.capabilities()
    assert caps.schemes == frozenset({"file", "swarm"})
    assert caps.supports_search is True
    assert caps.supports_delete is True
    assert caps.supports_promote is True


@pytest.mark.asyncio
async def test_capabilities_no_promote_without_both(tmp_path):
    comp = CompositeMemoryPort({"file": LocalScratchAdapter(tmp_path)})
    assert comp.capabilities().supports_promote is False
