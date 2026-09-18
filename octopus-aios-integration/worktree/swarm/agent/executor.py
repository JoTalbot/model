from __future__ import annotations

import logging

from swarm.agent.reasoning import ReasoningEngine
from swarm.events.events import TaskCompleted, TaskFailed

logger = logging.getLogger(__name__)


class TaskExecutor:
    """Executes task objects and persists their result artifact."""

    def __init__(self, node_id: str, memory, reasoning: ReasoningEngine, memory_port=None, bus=None) -> None:
        self.node_id = node_id
        self.memory = memory
        self.memory_port = memory_port
        self.reasoning = reasoning
        self.bus = bus

    async def execute(self, task) -> None:
        from swarm.agent.core import TaskStatus

        task.status = TaskStatus.RUNNING
        try:
            result = await self.reasoning.think(
                f"Execute this task: {task.description}",
                system_prompt="You are an autonomous AI agent in a swarm. Complete the given task.",
            )
            task.result = result
            task.status = TaskStatus.DONE
            result_ref = await self._persist_result(task, result)
            if self.bus is not None:
                await self.bus.publish(TaskCompleted(task.id, result_ref))
        except Exception as exc:
            task.status = TaskStatus.FAILED
            if self.bus is not None:
                await self.bus.publish(TaskFailed(task.id, str(exc)))
            logger.error("Task %s failed: %s", task.id, exc)

    async def _persist_result(self, task, result: str) -> str:
        if self.memory_port is not None:
            from swarm.memory.types import Artifact

            return await self.memory_port.put(
                Artifact(
                    content=result.encode(),
                    mime="text/plain",
                    tags=["task_result", task.id],
                    attrs={"store": "swarm", "block_type": "task_result"},
                )
            )

        from swarm.memory.store import MemoryBlock

        block = MemoryBlock(
            owner_id=self.node_id,
            block_type="task_result",
            content=result.encode(),
            tags=["task_result", task.id],
        )
        block_id = await self.memory.store(block)
        return f"ref:swarm:{block_id}"
