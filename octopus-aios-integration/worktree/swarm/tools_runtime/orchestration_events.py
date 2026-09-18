"""Event-aware orchestration helpers for the AIOS vNext runtime."""

from typing import Any

from .event_bus import EventBus
from .event_types import (
    EXECUTION_COMPLETED,
    EXECUTION_FAILED,
    EXECUTION_STARTED,
    MEMORY_UPDATED,
    PLAN_CREATED,
    REFLECTION_COMPLETED,
    REFLECTION_STARTED,
    REPLAN_COMPLETED,
    REPLAN_REQUESTED,
)
from .execution_context import ExecutionContext
from .execution_events import ExecutionEvent


class OrchestrationEvents:
    """Publishes canonical lifecycle events using one execution context."""

    def __init__(self, event_bus: EventBus | None = None):
        self.event_bus = event_bus

    async def publish(self, event_type: str, context: ExecutionContext, **data: Any):
        if self.event_bus:
            await self.event_bus.publish(event_type, ExecutionEvent(event_type, context, data))

    async def started(self, context: ExecutionContext, **data):
        await self.publish(EXECUTION_STARTED, context, **data)

    async def completed(self, context: ExecutionContext, **data):
        await self.publish(EXECUTION_COMPLETED, context, **data)

    async def failed(self, context: ExecutionContext, **data):
        await self.publish(EXECUTION_FAILED, context, **data)

    async def plan_created(self, context: ExecutionContext, **data):
        await self.publish(PLAN_CREATED, context, **data)

    async def reflection_started(self, context: ExecutionContext, **data):
        await self.publish(REFLECTION_STARTED, context, **data)

    async def reflection_completed(self, context: ExecutionContext, **data):
        await self.publish(REFLECTION_COMPLETED, context, **data)

    async def replan_requested(self, context: ExecutionContext, **data):
        await self.publish(REPLAN_REQUESTED, context, **data)

    async def replan_completed(self, context: ExecutionContext, **data):
        await self.publish(REPLAN_COMPLETED, context, **data)

    async def memory_updated(self, context: ExecutionContext, **data):
        await self.publish(MEMORY_UPDATED, context, **data)
