"""Тесты для swarm.observability — ObservabilityCollector и NodeStatus."""

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from swarm.events.bus import EventBus
from swarm.events.events import (
    BlockStored,
    GossipReceived,
    LLMCallCompleted,
    LLMCallFailed,
    MemoryGetFailed,
    MemoryGetOk,
    MemoryPut,
    NodeJoined,
    NodeLeft,
    PeerDiscovered,
    ShardRepairCompleted,
    TaskCompleted,
    TaskCreated,
    TaskFailed,
)
from swarm.observability import NodeStatus, ObservabilityCollector


def _mock_container():
    bus = EventBus()
    container = MagicMock()
    container.bus = bus
    container.port = 8000
    container.kad.node_id = "test-node"
    container.kad.get_peers = AsyncMock(return_value=["peer-1", "peer-2"])
    container.gossip._seen = {"msg-1": None, "msg-2": None}
    container.agent.task_queue.qsize.return_value = 3
    container.agent.memory_port = None
    return container


class TestNodeStatus:
    def test_to_dict(self):
        ns = NodeStatus(
            node_id="n1",
            started_at=time.time() - 100,
            port=8000,
            peers=["p1"],
            tasks_pending=2,
            tasks_completed=5,
            tasks_failed=1,
            memory_schemes_active=3,
            memory_puts=10,
            memory_gets_ok=20,
            memory_gets_failed=2,
            llm_calls_total=15,
            llm_calls_failed=3,
            llm_tokens_in=5000,
            llm_tokens_out=3000,
            gossip_messages_seen=100,
            blocks_stored=8,
            blocks_retrieved=6,
            nodes_known=4,
            shards_repaired=2,
            peers_discovered=7,
        )
        d = ns.to_dict()
        assert d["node_id"] == "n1"
        assert d["peers_count"] == 1
        assert d["uptime_seconds"] >= 99
        assert d["tasks_completed"] == 5

    def test_uptime(self):
        ns = NodeStatus(
            node_id="x", started_at=time.time() - 60,
            port=0, peers=[], tasks_pending=0, tasks_completed=0,
            tasks_failed=0, memory_schemes_active=0, memory_puts=0,
            memory_gets_ok=0, memory_gets_failed=0, llm_calls_total=0,
            llm_calls_failed=0, llm_tokens_in=0, llm_tokens_out=0,
            gossip_messages_seen=0, blocks_stored=0, blocks_retrieved=0,
            nodes_known=0, shards_repaired=0, peers_discovered=0,
        )
        assert ns.uptime_seconds >= 59


class TestObservabilityCollector:
    @pytest.mark.asyncio
    async def test_subscribes_to_events(self):
        container = _mock_container()
        collector = ObservabilityCollector(container)

        bus = container.bus
        await bus.publish(TaskCreated(task_id="t1"))
        await bus.publish(TaskCompleted(task_id="t2", result_ref="r"))
        await bus.publish(TaskFailed(task_id="t3", error="err"))
        await bus.publish(BlockStored(block_id="b1"))
        await bus.publish(NodeJoined(node_id="n1"))
        await bus.publish(NodeLeft(node_id="n2"))
        await bus.publish(LLMCallCompleted(model="m", tokens_in=100, tokens_out=50))
        await bus.publish(LLMCallFailed(model="m", error="timeout"))
        await bus.publish(MemoryPut(scheme="file", ref="r"))
        await bus.publish(MemoryGetOk(scheme="file", ref="r"))
        await bus.publish(MemoryGetFailed(scheme="file", ref="r", error="e"))
        await bus.publish(GossipReceived(msg_id="g1", msg_type="t"))
        await bus.publish(ShardRepairCompleted(block_id="s1", shards_recovered=3))
        await bus.publish(PeerDiscovered(host="10.0.0.1", port=8000))

        status = await collector.status()

        assert status.tasks_completed == 1
        assert status.tasks_failed == 1
        assert status.blocks_stored == 1
        assert status.llm_calls_total == 1
        assert status.llm_calls_failed == 1
        assert status.llm_tokens_in == 100
        assert status.llm_tokens_out == 50
        assert status.memory_puts == 1
        assert status.memory_gets_ok == 1
        assert status.memory_gets_failed == 1
        assert status.shards_repaired == 3
        assert status.peers_discovered == 1
        assert status.nodes_known == 1  # n1 joined, n2 left (but n2 was never joined)

    @pytest.mark.asyncio
    async def test_status_returns_node_status(self):
        container = _mock_container()
        collector = ObservabilityCollector(container)
        status = await collector.status()
        assert isinstance(status, NodeStatus)
        assert status.port == 8000
        assert len(status.peers) == 2

    @pytest.mark.asyncio
    async def test_node_join_and_leave(self):
        container = _mock_container()
        collector = ObservabilityCollector(container)
        bus = container.bus

        await bus.publish(NodeJoined(node_id="a"))
        await bus.publish(NodeJoined(node_id="b"))
        await bus.publish(NodeLeft(node_id="a"))

        status = await collector.status()
        assert status.nodes_known == 1  # только b
