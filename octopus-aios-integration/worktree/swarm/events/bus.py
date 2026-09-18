from __future__ import annotations

import inspect
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

EventT = TypeVar("EventT")
Handler = Callable[[Any], Awaitable[None] | None]


class EventBus:
    """Small async pub/sub bus for decoupling platform components."""

    def __init__(self) -> None:
        self._subs: defaultdict[type, list[Handler]] = defaultdict(list)

    def subscribe(self, event_type: type[EventT], handler: Handler) -> None:
        self._subs[event_type].append(handler)

    async def publish(self, event: object) -> None:
        for handler in list(self._subs[type(event)]):
            result = handler(event)
            if inspect.isawaitable(result):
                await result
