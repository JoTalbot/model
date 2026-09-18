import asyncio

import pytest

from swarm.network.kademlia import KademliaNode


@pytest.mark.asyncio
async def test_kademlia_start_and_stop():
    node = KademliaNode(port=17000)
    await node.start()
    assert node.node_id is not None
    await node.stop()


@pytest.mark.asyncio
async def test_kademlia_set_and_get():
    node = KademliaNode(port=17001)
    await node.start()

    try:
        await node.set("test_key", b"test_value")
        result = await node.get("test_key")
        assert result == b"test_value"
    finally:
        await node.stop()


@pytest.mark.asyncio
async def test_kademlia_get_missing_key():
    node = KademliaNode(port=17002)
    await node.start()

    try:
        result = await node.get("nonexistent")
        assert result is None
    finally:
        await node.stop()


@pytest.mark.asyncio
async def test_kademlia_two_nodes_share_data():
    node_a = KademliaNode(port=17010)
    node_b = KademliaNode(port=17011)
    await node_a.start()
    await node_b.start(bootstrap_addr=("127.0.0.1", 17010))

    try:
        await asyncio.sleep(0.5)
        await node_a.set("shared_key", b"shared_value")
        await asyncio.sleep(0.5)
        result = await node_b.get("shared_key")
        assert result == b"shared_value"
    finally:
        await node_a.stop()
        await node_b.stop()
