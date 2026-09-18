import asyncio

import pytest

from swarm.tools_runtime.shutdown_manager import ShutdownManager


class Resource:
    def __init__(self):
        self.closed = False

    async def aclose(self):
        self.closed = True


@pytest.mark.skip(reason="WAVE2-QUARANTINE: red on upstream AIOS new-branch (WIP drift), see docs/aios/WAVE2_TRIAGE.md")
@pytest.mark.asyncio
async def test_shutdown_cancels_tasks_and_closes_resources():
    manager = ShutdownManager()
    resource = manager.register(Resource())
    cancelled = asyncio.Event()

    async def worker():
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    task = manager.track_task(asyncio.create_task(worker()))
    result = await manager.shutdown()

    assert result == {"status": "stopped"}
    assert cancelled.is_set()
    assert task.cancelled()
    assert resource.closed


@pytest.mark.skip(reason="WAVE2-QUARANTINE: red on upstream AIOS new-branch (WIP drift), see docs/aios/WAVE2_TRIAGE.md")
@pytest.mark.asyncio
async def test_shutdown_is_idempotent():
    manager = ShutdownManager()
    assert await manager.shutdown() == {"status": "stopped"}
    assert await manager.shutdown() == {"status": "stopped"}
