from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable, Any


@dataclass
class GhostResult:
    node_id: str
    result: Any
    success: bool


class GhostExecutor:
    """Redundant execution engine.

    Same task executes on multiple ephemeral workers.
    Consensus/verification layer can later compare outputs.
    """

    async def execute(
        self,
        workers: list[str],
        task: Callable[[], Awaitable[Any]],
    ) -> list[GhostResult]:
        async def wrapped(worker_id: str) -> GhostResult:
            try:
                result = await task()
                return GhostResult(worker_id, result, True)
            except Exception as exc:
                return GhostResult(worker_id, repr(exc), False)

        return await asyncio.gather(*[
            wrapped(worker) for worker in workers
        ])
