"""Runtime observability collector for the swarm node.

Subscribes to :class:`EventBus` and exposes an aggregated
:meth:`status` snapshot that the API layer can serve as JSON.
"""

from __future__ import annotations

import contextlib
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from swarm.events.events import (
    BlockRetrieved,
    BlockStored,
    GossipReceived,
    LLMCallCompleted,
    LLMCallFailed,
    MemoryGetFailed,
    MemoryGetOk,
    MemoryPut,
    NodeJoined,
    NodeLeft,
    PeerDiscovered,
    ShardRepairCompleted,
    TaskCompleted,
    TaskCreated,
    TaskFailed,
)

if TYPE_CHECKING:
    pass


@dataclass
class NodeStatus:
    node_id: str
    started_at: float
    port: int
    peers: list[str]
    tasks_pending: int
    tasks_completed: int
    tasks_failed: int
    memory_schemes_active: int
    memory_puts: int
    memory_gets_ok: int
    memory_gets_failed: int
    llm_calls_total: int
    llm_calls_failed: int
    llm_tokens_in: int
    llm_tokens_out: int
    gossip_messages_seen: int
    blocks_stored: int
    blocks_retrieved: int
    nodes_known: int
    shards_repaired: int
    peers_discovered: int

    @property
    def uptime_seconds(self) -> float:
        return time.time() - self.started_at

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "started_at": self.started_at,
            "uptime_seconds": round(self.uptime_seconds, 1),
            "port": self.port,
            "peers": self.peers,
            "peers_count": len(self.peers),
            "tasks_pending": self.tasks_pending,
            "tasks_completed": self.tasks_completed,
            "tasks_failed": self.tasks_failed,
            "memory_schemes_active": self.memory_schemes_active,
            "memory_puts": self.memory_puts,
            "memory_gets_ok": self.memory_gets_ok,
            "memory_gets_failed": self.memory_gets_failed,
            "llm_calls_total": self.llm_calls_total,
            "llm_calls_failed": self.llm_calls_failed,
            "llm_tokens_in": self.llm_tokens_in,
            "llm_tokens_out": self.llm_tokens_out,
            "gossip_messages_seen": self.gossip_messages_seen,
            "blocks_stored": self.blocks_stored,
            "blocks_retrieved": self.blocks_retrieved,
            "nodes_known": self.nodes_known,
            "shards_repaired": self.shards_repaired,
            "peers_discovered": self.peers_discovered,
        }


class ObservabilityCollector:
    """Aggregates runtime state from all AppContainer components.

    Wire it up once during ``AppRuntime.start()``::

        collector = ObservabilityCollector(container)
        # later:
        status = await collector.status()
    """

    def __init__(self, container) -> None:
        self._c = container
        self._started_at = time.time()

        # Event counters
        self._tasks_created = 0
        self._tasks_completed = 0
        self._tasks_failed = 0
        self._blocks_stored = 0
        self._blocks_retrieved = 0
        self._llm_calls = 0
        self._llm_calls_failed = 0
        self._llm_tokens_in = 0
        self._llm_tokens_out = 0
        self._memory_puts = 0
        self._memory_gets_ok = 0
        self._memory_gets_failed = 0
        self._gossip_received = 0
        self._shards_repaired = 0
        self._peers_discovered = 0
        self._nodes_joined: set[str] = set()
        self._nodes_left: set[str] = set()

        bus = container.bus
        bus.subscribe(TaskCreated, self._on_task_created)
        bus.subscribe(TaskCompleted, self._on_task_completed)
        bus.subscribe(TaskFailed, self._on_task_failed)
        bus.subscribe(BlockStored, self._on_block_stored)
        bus.subscribe(BlockRetrieved, self._on_block_retrieved)
        bus.subscribe(NodeJoined, self._on_node_joined)
        bus.subscribe(NodeLeft, self._on_node_left)
        bus.subscribe(LLMCallCompleted, self._on_llm_call)
        bus.subscribe(LLMCallFailed, self._on_llm_failed)
        bus.subscribe(MemoryPut, self._on_memory_put)
        bus.subscribe(MemoryGetOk, self._on_memory_get_ok)
        bus.subscribe(MemoryGetFailed, self._on_memory_get_failed)
        bus.subscribe(GossipReceived, self._on_gossip)
        bus.subscribe(ShardRepairCompleted, self._on_shard_repair)
        bus.subscribe(PeerDiscovered, self._on_peer_discovered)

    # ---- handlers ----

    async def _on_task_created(self, event: TaskCreated) -> None:
        self._tasks_created += 1

    async def _on_task_completed(self, event: TaskCompleted) -> None:
        self._tasks_completed += 1

    async def _on_task_failed(self, event: TaskFailed) -> None:
        self._tasks_failed += 1

    async def _on_block_stored(self, event: BlockStored) -> None:
        self._blocks_stored += 1

    async def _on_block_retrieved(self, event: BlockRetrieved) -> None:
        self._blocks_retrieved += 1

    async def _on_node_joined(self, event: NodeJoined) -> None:
        self._nodes_joined.add(event.node_id)
        self._nodes_left.discard(event.node_id)

    async def _on_node_left(self, event: NodeLeft) -> None:
        self._nodes_left.add(event.node_id)
        self._nodes_joined.discard(event.node_id)

    async def _on_llm_call(self, event: LLMCallCompleted) -> None:
        self._llm_calls += 1
        self._llm_tokens_in += event.tokens_in
        self._llm_tokens_out += event.tokens_out

    async def _on_llm_failed(self, event: LLMCallFailed) -> None:
        self._llm_calls_failed += 1

    async def _on_memory_put(self, event: MemoryPut) -> None:
        self._memory_puts += 1

    async def _on_memory_get_ok(self, event: MemoryGetOk) -> None:
        self._memory_gets_ok += 1

    async def _on_memory_get_failed(self, event: MemoryGetFailed) -> None:
        self._memory_gets_failed += 1

    async def _on_gossip(self, event: GossipReceived) -> None:
        self._gossip_received += 1

    async def _on_shard_repair(self, event: ShardRepairCompleted) -> None:
        self._shards_repaired += event.shards_recovered

    async def _on_peer_discovered(self, event: PeerDiscovered) -> None:
        self._peers_discovered += 1

    # ---- public ----

    async def status(self) -> NodeStatus:
        peers: list[str] = []
        with contextlib.suppress(Exception):
            peers = await self._c.kad.get_peers()

        memory_schemes = 0
        try:
            mp = getattr(self._c.agent, "memory_port", None)
            if mp is not None:
                metrics = getattr(mp, "metrics", None)
                if metrics is not None:
                    memory_schemes = len(metrics.schemes())
        except Exception:
            pass

        gossip_seen = 0
        with contextlib.suppress(Exception):
            gossip_seen = len(self._c.gossip._seen)

        return NodeStatus(
            node_id=self._c.kad.node_id or "unknown",
            started_at=self._started_at,
            port=self._c.port,
            peers=peers,
            tasks_pending=self._c.agent.task_queue.qsize(),
            tasks_completed=self._tasks_completed,
            tasks_failed=self._tasks_failed,
            memory_schemes_active=memory_schemes,
            memory_puts=self._memory_puts,
            memory_gets_ok=self._memory_gets_ok,
            memory_gets_failed=self._memory_gets_failed,
            llm_calls_total=self._llm_calls,
            llm_calls_failed=self._llm_calls_failed,
            llm_tokens_in=self._llm_tokens_in,
            llm_tokens_out=self._llm_tokens_out,
            gossip_messages_seen=gossip_seen,
            blocks_stored=self._blocks_stored,
            blocks_retrieved=self._blocks_retrieved,
            nodes_known=len(self._nodes_joined),
            shards_repaired=self._shards_repaired,
            peers_discovered=self._peers_discovered,
        )


__all__ = ["NodeStatus", "ObservabilityCollector"]
