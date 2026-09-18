"""Тесты для swarm.events.bus и swarm.events.handlers."""


import pytest

from swarm.events.bus import EventBus
from swarm.events.events import (
    BlockStored,
    NodeJoined,
    TaskCompleted,
    TaskFailed,
)
from swarm.events.handlers import (
    log_block_stored,
    log_task_completed,
    log_task_failed,
)


class TestEventBus:
    @pytest.mark.asyncio
    async def test_publish_to_subscriber(self):
        bus = EventBus()
        received = []
        bus.subscribe(NodeJoined, lambda e: received.append(e))
        await bus.publish(NodeJoined(node_id="node-1"))
        assert len(received) == 1
        assert received[0].node_id == "node-1"

    @pytest.mark.asyncio
    async def test_publish_async_handler(self):
        bus = EventBus()
        received = []

        async def handler(e):
            received.append(e)

        bus.subscribe(TaskCompleted, handler)
        await bus.publish(TaskCompleted(task_id="t1", result_ref="ref:1"))
        assert len(received) == 1
        assert received[0].task_id == "t1"

    @pytest.mark.asyncio
    async def test_multiple_subscribers(self):
        bus = EventBus()
        r1, r2 = [], []
        bus.subscribe(NodeJoined, lambda e: r1.append(e))
        bus.subscribe(NodeJoined, lambda e: r2.append(e))
        await bus.publish(NodeJoined(node_id="x"))
        assert len(r1) == 1
        assert len(r2) == 1

    @pytest.mark.asyncio
    async def test_no_crosstalk(self):
        """Событие одного типа не вызывает подписчиков другого."""
        bus = EventBus()
        received = []
        bus.subscribe(NodeJoined, lambda e: received.append(e))
        await bus.publish(TaskFailed(task_id="t", error="x"))
        assert received == []

    @pytest.mark.asyncio
    async def test_no_subscribers(self):
        """Публикация без подписчиков — не падает."""
        bus = EventBus()
        await bus.publish(BlockStored(block_id="b1"))


class TestHandlers:
    @pytest.mark.asyncio
    async def test_log_task_completed(self):
        await log_task_completed(TaskCompleted(task_id="t1", result_ref="r"))

    @pytest.mark.asyncio
    async def test_log_task_failed(self):
        await log_task_failed(TaskFailed(task_id="t2", error="oops"))

    @pytest.mark.asyncio
    async def test_log_block_stored(self):
        await log_block_stored(BlockStored(block_id="b1"))
