"""SyncEngine — CRDT-based multi-device memory synchronization via Gossip.

Lifecycle:
1. ``SyncEngine`` wraps a ``MemoryIndexCRDT`` and listens for gossip
   messages of type ``memory_sync``.
2. When the local node writes (put/delete), call ``track_put`` /
   ``track_delete`` to update the local CRDT.
3. Periodically (or on-demand), ``broadcast_state`` serializes the CRDT
   and injects it into the Gossip outbox.
4. On incoming ``memory_sync`` gossip, the engine deserializes the remote
   CRDT and merges it into the local one.

The engine does NOT move actual blob data — only metadata refs. After merge,
the caller can compare ``get_active_refs()`` with local storage to decide
which blobs to pull from peers via RPC.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import Any

from swarm.memory.crdt import MemoryIndexCRDT

logger = logging.getLogger(__name__)

GOSSIP_MSG_TYPE = "memory_sync"


class SyncEngine:
    """Движок CRDT-синхронизации памяти через Gossip.

    Parameters
    ----------
    node_id : str
        Идентификатор текущего узла.
    gossip : object | None
        ``GossipProtocol`` (опционально; без него sync работает только локально).
    sync_interval : float
        Интервал автоматической рассылки состояния (сек). 0 — выключен.
    """

    def __init__(
        self,
        node_id: str,
        *,
        gossip: Any | None = None,
        sync_interval: float = 30.0,
    ) -> None:
        self.node_id = node_id
        self._crdt = MemoryIndexCRDT()
        self._gossip = gossip
        self._sync_interval = sync_interval
        self._task: asyncio.Task | None = None
        self._merge_count: int = 0
        self._last_sync: float = 0.0

    @property
    def crdt(self) -> MemoryIndexCRDT:
        return self._crdt

    # ── Трекинг локальных операций ──

    def track_put(self, ref: str, meta: dict | None = None) -> None:
        """Отслеживать put-операцию."""
        data = {
            "node_id": self.node_id,
            "op": "put",
            **(meta or {}),
        }
        self._crdt.update_record(ref, data)

    def track_delete(self, ref: str) -> None:
        """Отслеживать delete-операцию."""
        self._crdt.delete_record(ref)

    # ── Gossip-интеграция ──

    async def broadcast_state(self) -> None:
        """Отправить текущее CRDT-состояние через Gossip."""
        if self._gossip is None:
            return

        from swarm.network.gossip import GossipMessage

        payload = {
            "from_node": self.node_id,
            "crdt": self._crdt.serialize(),
            "ts": time.time(),
        }
        msg = GossipMessage(
            msg_type=GOSSIP_MSG_TYPE,
            payload=payload,
        )
        await self._gossip.inject(msg)
        self._last_sync = time.time()
        logger.debug("Sync broadcast: version=%d refs=%d", self._crdt.version, self._crdt.active_count)

    async def handle_gossip(self, msg: Any) -> None:
        """Обработать входящее gossip-сообщение memory_sync."""
        if not hasattr(msg, "msg_type") or msg.msg_type != GOSSIP_MSG_TYPE:
            return

        payload = msg.payload or {}
        remote_data = payload.get("crdt")
        if not remote_data:
            return

        from_node = payload.get("from_node", "?")
        remote_crdt = MemoryIndexCRDT.deserialize(remote_data)
        changes = self._crdt.merge(remote_crdt)
        self._merge_count += 1

        if changes > 0:
            logger.info(
                "Sync merge from %s: %d changes, version now %d",
                from_node,
                changes,
                self._crdt.version,
            )

    # ── Автоматическая синхронизация ──

    async def start(self) -> None:
        """Запустить фоновую рассылку CRDT-состояния."""
        if self._sync_interval > 0:
            self._task = asyncio.create_task(self._sync_loop())

    async def stop(self) -> None:
        """Остановить фоновую рассылку."""
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _sync_loop(self) -> None:
        while True:
            await asyncio.sleep(self._sync_interval)
            try:
                await self.broadcast_state()
            except Exception as exc:
                logger.warning("Sync broadcast failed: %s", exc)

    # ── Статистика ──

    def stats(self) -> dict:
        """Снимок статистики для мониторинга."""
        return {
            "node_id": self.node_id,
            "merge_count": self._merge_count,
            "last_sync": self._last_sync,
            "sync_interval": self._sync_interval,
            "gossip_connected": self._gossip is not None,
            **self._crdt.stats(),
        }

    def missing_refs(self, local_refs: set[str]) -> list[str]:
        """Ref'ы, которые есть в CRDT, но отсутствуют локально.

        Полезно для определения, какие блобы нужно скачать с пиров.
        """
        active = set(self._crdt.get_active_refs())
        return sorted(active - local_refs)
