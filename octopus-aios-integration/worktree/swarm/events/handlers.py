from __future__ import annotations

import logging

from swarm.events.events import BlockStored, TaskCompleted, TaskFailed

logger = logging.getLogger(__name__)


async def log_task_completed(event: TaskCompleted) -> None:
    logger.info("Task completed: %s result=%s", event.task_id, event.result_ref)


async def log_task_failed(event: TaskFailed) -> None:
    logger.warning("Task failed: %s error=%s", event.task_id, event.error)


async def log_block_stored(event: BlockStored) -> None:
    logger.info("Block stored: %s", event.block_id)
