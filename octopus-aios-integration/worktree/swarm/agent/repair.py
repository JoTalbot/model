from __future__ import annotations

import asyncio
import contextlib
import logging

logger = logging.getLogger(__name__)


class RepairLoop:
    """Periodic memory repair runner kept outside the core agent facade."""

    def __init__(self, memory, interval_seconds: int, *, bus=None) -> None:
        self.memory = memory
        self.interval_seconds = interval_seconds
        self._bus = bus
        self._task: asyncio.Task | None = None
        self._running = False

        # ── Counters ──
        self.rounds_completed: int = 0
        self.rounds_failed: int = 0
        self.total_blocks_ok: int = 0

    async def _emit(self, event: object) -> None:
        if self._bus is not None:
            await self._bus.publish(event)

    def start(self) -> None:
        if self.interval_seconds <= 0 or not hasattr(self.memory, "scan_and_repair_round"):
            return
        if self._task is None:
            self._running = True
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(self.interval_seconds)
                if not self._running:
                    break

                from swarm.events.events import ShardRepairStarted
                await self._emit(ShardRepairStarted(block_id="*"))

                n = await self.memory.scan_and_repair_round()
                self.rounds_completed += 1
                self.total_blocks_ok += n or 0

                if n:
                    logger.info("Memory repair round: %d block(s) healthy", n)
                    from swarm.events.events import ShardRepairCompleted
                    await self._emit(ShardRepairCompleted(
                        block_id="*",
                        shards_recovered=n,
                    ))

            except asyncio.CancelledError:
                break
            except Exception as exc:
                self.rounds_failed += 1
                logger.warning("Memory repair round failed: %s", exc)

                from swarm.events.events import ShardRepairFailed
                await self._emit(ShardRepairFailed(block_id="*", error=str(exc)))

    def stats(self) -> dict:
        """Return a snapshot of repair statistics."""
        return {
            "interval_seconds": self.interval_seconds,
            "rounds_completed": self.rounds_completed,
            "rounds_failed": self.rounds_failed,
            "total_blocks_ok": self.total_blocks_ok,
            "running": self._running,
        }
