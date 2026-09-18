"""Server-Sent Events bridge from EventBus to HTTP clients.

Each connected client gets a dedicated :class:`asyncio.Queue`.  When an
event fires on the bus the bridge serialises it once and fans it out to
all queues.  Slow consumers that let their queue fill up are silently
dropped — the swarm never blocks on a dashboard viewer.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import asdict

from swarm.events.bus import EventBus

# Import all known event types so we can subscribe to them.
from swarm.events.events import (
    AdapterHealthChanged,
    BlockRetrieved,
    BlockStored,
    ConfigReloaded,
    GossipReceived,
    GossipSent,
    LLMCallCompleted,
    LLMCallFailed,
    LLMCallStarted,
    MemoryGetFailed,
    MemoryGetOk,
    MemoryPut,
    NodeJoined,
    NodeLeft,
    PeerDiscovered,
    ShardRepairCompleted,
    ShardRepairFailed,
    ShardRepairStarted,
    TaskCompleted,
    TaskCreated,
    TaskFailed,
)

_ALL_EVENTS = [
    # Node lifecycle
    NodeJoined,
    NodeLeft,
    # Tasks
    TaskCreated,
    TaskCompleted,
    TaskFailed,
    # Blocks
    BlockStored,
    BlockRetrieved,
    # Gossip
    GossipReceived,
    GossipSent,
    # Memory
    MemoryPut,
    MemoryGetOk,
    MemoryGetFailed,
    # LLM
    LLMCallStarted,
    LLMCallCompleted,
    LLMCallFailed,
    # Shard repair
    ShardRepairStarted,
    ShardRepairCompleted,
    ShardRepairFailed,
    # Peer discovery
    PeerDiscovered,
    # Config
    ConfigReloaded,
    # Adapter health
    AdapterHealthChanged,
]


def _event_to_dict(event: object) -> dict:
    """Best-effort serialisation of a dataclass event."""
    if hasattr(event, "__dataclass_fields__"):
        return asdict(event)  # type: ignore[arg-type]
    return {"repr": repr(event)}


class SSEBridge:
    """Forward EventBus events to connected SSE clients."""

    def __init__(self, bus: EventBus, *, max_queue: int = 256) -> None:
        self._bus = bus
        self._max_queue = max_queue
        self._clients: list[asyncio.Queue[dict]] = []

        for event_type in _ALL_EVENTS:
            bus.subscribe(event_type, self._forward)

    async def _forward(self, event: object) -> None:
        data = {
            "type": type(event).__name__,
            "payload": _event_to_dict(event),
            "ts": time.time(),
        }
        dead: list[asyncio.Queue] = []
        for q in list(self._clients):
            try:
                q.put_nowait(data)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            with contextlib.suppress(ValueError):
                self._clients.remove(q)

    def connect(self) -> asyncio.Queue[dict]:
        """Register a new SSE consumer; returns its queue."""
        q: asyncio.Queue[dict] = asyncio.Queue(maxsize=self._max_queue)
        self._clients.append(q)
        return q

    def disconnect(self, q: asyncio.Queue[dict]) -> None:
        with contextlib.suppress(ValueError):
            self._clients.remove(q)

    @property
    def client_count(self) -> int:
        return len(self._clients)


__all__ = ["SSEBridge"]
