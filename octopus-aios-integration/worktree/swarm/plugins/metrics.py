from __future__ import annotations

from collections import Counter

from swarm.events.events import BlockStored, TaskCompleted, TaskFailed
from swarm.plugins.base import Plugin


class MetricsPlugin(Plugin):
    name = "metrics"

    def __init__(self) -> None:
        self.counters: Counter[str] = Counter()

    async def setup(self, container) -> None:
        container.bus.subscribe(TaskCompleted, self.on_task_done)
        container.bus.subscribe(TaskFailed, self.on_task_failed)
        container.bus.subscribe(BlockStored, self.on_block_stored)

    async def on_task_done(self, event: TaskCompleted) -> None:
        self.counters["task.completed"] += 1

    async def on_task_failed(self, event: TaskFailed) -> None:
        self.counters["task.failed"] += 1

    async def on_block_stored(self, event: BlockStored) -> None:
        self.counters["block.stored"] += 1
