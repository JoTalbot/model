import asyncio

import pytest

from swarm.memory.erasure import ErasureCoder
from swarm.memory.store import DistributedMemory, MemoryBlock
from swarm.network.gossip import GossipMessage, GossipProtocol
from swarm.network.kademlia import KademliaNode
from swarm.network.rpc import RPCClient


@pytest.mark.asyncio
async def test_two_node_gossip_and_memory():
    """Integration: two nodes share data through DHT and communicate via gossip."""
    received_gossip = []

    async def on_gossip_b(msg):
        received_gossip.append(msg)

    kad_a = KademliaNode(port=15000)
    kad_b = KademliaNode(port=15001)
    await kad_a.start()
    await kad_b.start(bootstrap_addr=("127.0.0.1", 15000))
    await asyncio.sleep(1.0)

    gossip_a = GossipProtocol(host="127.0.0.1", port=15100, interval=0.3, fanout=1)
    gossip_b = GossipProtocol(
        host="127.0.0.1", port=15101, on_message=on_gossip_b, interval=0.3, fanout=1,
    )
    gossip_a.add_peer("127.0.0.1", 15101)
    await gossip_a.start()
    await gossip_b.start()

    coder = ErasureCoder(data_shards=4, parity_shards=2)
    rpc_client = RPCClient()

    mem_a = DistributedMemory(
        kademlia=kad_a, rpc_client=rpc_client, coder=coder, node_id="node-a",
    )
    mem_b = DistributedMemory(
        kademlia=kad_b, rpc_client=rpc_client, coder=coder, node_id="node-b",
    )

    try:
        block = MemoryBlock(
            owner_id="node-a",
            block_type="knowledge",
            content=b"Autoglass prices: windshield 5000 RUB",
            tags=["prices", "autoglass"],
        )
        block_id = await mem_a.store(block)
        await asyncio.sleep(1.0)

        retrieved = await mem_b.retrieve(block_id)
        assert retrieved is not None
        assert retrieved.content == b"Autoglass prices: windshield 5000 RUB"

        msg = GossipMessage(msg_type="TASK_BROADCAST", payload={"task": "parse more"})
        await gossip_a.inject(msg)
        await asyncio.sleep(1.5)

        assert len(received_gossip) >= 1
        assert received_gossip[0].payload["task"] == "parse more"
    finally:
        await gossip_a.stop()
        await gossip_b.stop()
        await kad_a.stop()
        await kad_b.stop()
