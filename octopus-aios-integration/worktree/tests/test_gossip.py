import asyncio

import pytest

from swarm.network.gossip import GossipMessage, GossipProtocol


@pytest.mark.asyncio
async def test_gossip_message_creation():
    msg = GossipMessage(msg_type="NODE_JOIN", payload={"node_id": "abc"})
    assert msg.msg_type == "NODE_JOIN"
    assert msg.payload == {"node_id": "abc"}
    assert msg.id is not None


@pytest.mark.asyncio
async def test_gossip_deduplication():
    received = []

    async def handler(msg: GossipMessage):
        received.append(msg)

    g = GossipProtocol(host="127.0.0.1", port=18500, on_message=handler)
    await g.start()

    try:
        msg = GossipMessage(msg_type="TEST", payload={"data": 1})
        await g.inject(msg)
        await g.inject(msg)
        await asyncio.sleep(0.1)
        assert len(received) == 1
    finally:
        await g.stop()


@pytest.mark.asyncio
async def test_gossip_propagation_between_two_nodes():
    received_on_b = []

    async def handler_a(msg: GossipMessage):
        pass

    async def handler_b(msg: GossipMessage):
        received_on_b.append(msg)

    ga = GossipProtocol(
        host="127.0.0.1", port=18510, on_message=handler_a, interval=0.2, fanout=1,
    )
    gb = GossipProtocol(
        host="127.0.0.1", port=18511, on_message=handler_b, interval=0.2, fanout=1,
    )
    ga.add_peer("127.0.0.1", 18511)

    await ga.start()
    await gb.start()

    try:
        msg = GossipMessage(msg_type="TASK_BROADCAST", payload={"task": "parse"})
        await ga.inject(msg)
        await asyncio.sleep(1.0)
        assert len(received_on_b) == 1
        assert received_on_b[0].payload == {"task": "parse"}
    finally:
        await ga.stop()
        await gb.stop()


@pytest.mark.asyncio
async def test_gossip_seen_capacity():
    received = []

    async def handler(msg: GossipMessage):
        received.append(msg)

    g = GossipProtocol(
        host="127.0.0.1", port=18520, on_message=handler, seen_capacity=5,
    )
    await g.start()

    try:
        for i in range(10):
            msg = GossipMessage(msg_type="TEST", payload={"i": i})
            await g.inject(msg)
        assert len(received) == 10
        assert len(g._seen) <= 5
    finally:
        await g.stop()
