"""Small async event bus for correlated AIOS runtime events."""

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

Handler = Callable[[Any], Awaitable[None]]


class EventBus:
    def __init__(self):
        self._handlers: defaultdict[str, list[Handler]] = defaultdict(list)

    def subscribe(self, event_type: str, handler: Handler):
        self._handlers[event_type].append(handler)

    async def publish(self, event_type: str, event: Any):
        handlers = tuple(self._handlers.get(event_type, ()))
        if handlers:
            results = await asyncio.gather(*(handler(event) for handler in handlers), return_exceptions=True)
            # Subscribers are observers: one broken observer must not fail execution.
            for result in results:
                if isinstance(result, Exception):
                    continue
