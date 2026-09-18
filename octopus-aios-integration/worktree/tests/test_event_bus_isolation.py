import pytest

from swarm.tools_runtime.event_bus import EventBus


@pytest.mark.asyncio
async def test_failed_subscriber_does_not_fail_publish():
    bus = EventBus()
    seen = []

    async def failing(_event):
        raise RuntimeError("subscriber failed")

    async def healthy(event):
        seen.append(event)

    bus.subscribe("execution.completed", failing)
    bus.subscribe("execution.completed", healthy)

    await bus.publish("execution.completed", {"execution_id": "exec-1"})

    assert seen == [{"execution_id": "exec-1"}]
